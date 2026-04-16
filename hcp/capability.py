"""
Capability (Harness) base class.

A :class:`Capability` listens on the queue for incoming messages addressed to
its ``capability_id``, performs pre-invocation safety validation, executes the
requested task, and publishes a :class:`~hcp.messages.ResultPayload` back to
the originating agent.

Subclass it and implement :meth:`execute` to create your own capability::

    from hcp import Capability, CapabilityManifest, HCPQueue

    class Calculator(Capability):
        async def execute(self, task_name: str, args: dict) -> object:
            if task_name == "add":
                return args["a"] + args["b"]
            raise NotImplementedError(task_name)

    async def main():
        queue = HCPQueue()
        await queue.start()

        manifest = CapabilityManifest(
            name="calculator",
            allowed_permissions=["math"],
        )
        calc = Calculator(capability_id="calculator", queue=queue, manifest=manifest)
        await calc.register()
        # … serve until shutdown …
        await queue.stop()
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from hcp.exceptions import SafetyCheckError
from hcp.messages import (
    EndpointInfo,
    EndpointType,
    ErrorPayload,
    EventPayload,
    HandshakePayload,
    Message,
    MessageType,
    ResultPayload,
    ResultStatus,
    SafetyCheckPayload,
    TaskPayload,
)
from hcp.queue import HCPQueue
from hcp.security import CapabilityManifest, SafetyValidator

logger = logging.getLogger(__name__)


class Capability(ABC):
    """
    Base class for all HCP capabilities (harnesses).

    Parameters
    ----------
    capability_id:
        Unique identifier for this capability instance.
    queue:
        The shared :class:`~hcp.queue.HCPQueue`.
    manifest:
        Declares what this capability is permitted to do.
    secret:
        Optional shared secret for verifying inbound messages and signing
        outbound messages.  When ``None``, verification is skipped.
    """

    def __init__(
        self,
        capability_id: str,
        queue: HCPQueue,
        manifest: CapabilityManifest,
        secret: bytes | str | None = None,
    ) -> None:
        self.capability_id = capability_id
        self._queue = queue
        self._manifest = manifest
        self._secret = secret
        self._validator = SafetyValidator(manifest)
        self._endpoint = EndpointInfo(id=capability_id, type=EndpointType.CAPABILITY)
        self._registered = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def register(self) -> None:
        """Subscribe to the queue and start receiving messages."""
        if self._registered:
            return
        self._queue.subscribe(self.capability_id, self._on_message)
        self._registered = True

    async def unregister(self) -> None:
        """Unsubscribe from the queue."""
        if not self._registered:
            return
        self._queue.unsubscribe(self.capability_id, self._on_message)
        self._registered = False

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, task_name: str, args: dict[str, Any]) -> Any:
        """
        Execute the named tool.

        Parameters
        ----------
        task_name:
            The name of the capability's tool to invoke.
        args:
            Keyword arguments provided by the agent.

        Returns
        -------
        Any
            JSON-serialisable result to return to the agent.

        Raises
        ------
        Exception
            Any exception will be caught and converted to a FAILURE result.
        """

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    async def emit_event(
        self,
        recipient_id: str,
        task_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish an EVENT message back to *recipient_id*.

        Parameters
        ----------
        recipient_id:
            ID of the agent (or other endpoint) to send the event to.
        task_id:
            ID of the task this event relates to.
        event_type:
            Free-form event type (e.g. ``"progress"``, ``"log"``).
        data:
            Arbitrary event data payload.
        """
        msg = Message(
            type=MessageType.EVENT,
            sender=self._endpoint,
            recipient=EndpointInfo(id=recipient_id, type=EndpointType.AGENT),
            payload=EventPayload(
                task_id=task_id,
                event_type=event_type,
                data=data or {},
            ),
        )
        self._maybe_sign(msg)
        await self._queue.publish(msg)

    # ------------------------------------------------------------------
    # Internal message handler
    # ------------------------------------------------------------------

    async def _on_message(self, message: Message) -> None:
        if self._secret is not None:
            try:
                from hcp.security import verify_message
                verify_message(message, self._secret)
            except Exception as exc:
                logger.warning("Signature verification failed for %s: %s", message.id, exc)
                await self._send_error(message.sender.id, "SIGNATURE_ERROR", str(exc))
                return

        if message.type == MessageType.HANDSHAKE:
            await self._handle_handshake(message)
        elif message.type == MessageType.SAFETY_CHECK:
            await self._handle_safety_check(message)
        elif message.type == MessageType.TASK:
            await self._handle_task(message)
        elif message.type == MessageType.HEARTBEAT:
            logger.debug("Heartbeat from %s", message.sender.id)
        else:
            logger.debug("Unhandled message type %s from %s", message.type, message.sender.id)

    async def _handle_handshake(self, message: Message) -> None:
        response = Message(
            type=MessageType.HANDSHAKE,
            sender=self._endpoint,
            recipient=message.sender,
            correlation_id=message.id,
            payload=HandshakePayload(
                capabilities=[self.capability_id],
            ),
        )
        self._maybe_sign(response)
        await self._queue.publish(response)

    async def _handle_safety_check(self, message: Message) -> None:
        check: SafetyCheckPayload = message.payload  # type: ignore[assignment]
        safety_response = self._validator.validate(check)
        response = Message(
            type=MessageType.SAFETY_RESPONSE,
            sender=self._endpoint,
            recipient=message.sender,
            correlation_id=message.id,
            payload=safety_response,
        )
        self._maybe_sign(response)
        await self._queue.publish(response)

    async def _handle_task(self, message: Message) -> None:
        task: TaskPayload = message.payload  # type: ignore[assignment]
        sender_id = message.sender.id

        try:
            output = await asyncio.wait_for(
                self.execute(task.name, task.args),
                timeout=task.timeout,
            )
            result = ResultPayload(
                task_id=task.task_id,
                status=ResultStatus.SUCCESS,
                output=output,
            )
        except asyncio.TimeoutError:
            result = ResultPayload(
                task_id=task.task_id,
                status=ResultStatus.TIMEOUT,
                error=f"Task '{task.name}' timed out after {task.timeout}s",
            )
        except SafetyCheckError as exc:
            result = ResultPayload(
                task_id=task.task_id,
                status=ResultStatus.REJECTED,
                error=str(exc),
            )
        except Exception as exc:
            logger.exception("Task '%s' raised an exception", task.name)
            result = ResultPayload(
                task_id=task.task_id,
                status=ResultStatus.FAILURE,
                error=str(exc),
            )

        response = Message(
            type=MessageType.RESULT,
            sender=self._endpoint,
            recipient=message.sender,
            correlation_id=message.id,
            payload=result,
        )
        self._maybe_sign(response)
        await self._queue.publish(response)

    async def _send_error(
        self, recipient_id: str, code: str, detail: str
    ) -> None:
        msg = Message(
            type=MessageType.ERROR,
            sender=self._endpoint,
            recipient=EndpointInfo(id=recipient_id, type=EndpointType.AGENT),
            payload=ErrorPayload(code=code, message=detail),
        )
        self._maybe_sign(msg)
        await self._queue.publish(msg)

    def _maybe_sign(self, message: Message) -> None:
        if self._secret is not None:
            from hcp.security import sign_message
            sign_message(message, self._secret)
