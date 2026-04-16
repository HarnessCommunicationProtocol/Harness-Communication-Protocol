"""
AI Agent base class.

An :class:`Agent` connects to the shared :class:`~hcp.queue.HCPQueue`, sends
:class:`~hcp.messages.TaskPayload` messages to capabilities, and collects
:class:`~hcp.messages.ResultPayload` responses.

Typical usage
-------------
::

    import asyncio
    from hcp import Agent, HCPQueue

    async def main():
        queue = HCPQueue()
        await queue.start()

        agent = Agent(agent_id="agent-1", queue=queue)
        await agent.connect()

        result = await agent.invoke(
            capability_id="calculator",
            task_name="add",
            args={"a": 1, "b": 2},
        )
        print(result.output)   # 3

        await agent.disconnect()
        await queue.stop()

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable

from hcp.exceptions import SafetyCheckError, TimeoutError
from hcp.messages import (
    EndpointInfo,
    EndpointType,
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

# Callback type: async def on_event(event: EventPayload) -> None
EventCallback = Callable[[EventPayload], Awaitable[None]]


class Agent:
    """
    AI Agent that dispatches tasks to capabilities via HCP.

    Parameters
    ----------
    agent_id:
        Unique identifier for this agent instance.
    queue:
        Shared :class:`~hcp.queue.HCPQueue`.
    secret:
        Optional shared secret for signing outbound messages and verifying
        inbound messages.  When ``None``, signing is disabled.
    default_timeout:
        Default task timeout in seconds.
    """

    def __init__(
        self,
        agent_id: str,
        queue: HCPQueue,
        secret: bytes | str | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        self.agent_id = agent_id
        self._queue = queue
        self._secret = secret
        self._default_timeout = default_timeout
        self._endpoint = EndpointInfo(id=agent_id, type=EndpointType.AGENT)
        self._pending: dict[str, asyncio.Future[ResultPayload]] = {}
        self._event_callbacks: list[EventCallback] = []
        self._connected = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Subscribe to the queue and start receiving messages."""
        if self._connected:
            return
        self._queue.subscribe(self.agent_id, self._on_message)
        self._connected = True

    async def disconnect(self) -> None:
        """Unsubscribe from the queue."""
        if not self._connected:
            return
        self._queue.unsubscribe(self.agent_id, self._on_message)
        self._connected = False

    # ------------------------------------------------------------------
    # Event subscriptions
    # ------------------------------------------------------------------

    def on_event(self, callback: EventCallback) -> None:
        """Register a callback to be called for every incoming EVENT message."""
        self._event_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    async def handshake(self, capability_id: str, timeout: float = 5.0) -> HandshakePayload:
        """
        Send a HANDSHAKE to *capability_id* and return its response payload.

        Parameters
        ----------
        capability_id:
            ID of the capability to shake hands with.
        timeout:
            Seconds to wait for the response.
        """
        msg = Message(
            type=MessageType.HANDSHAKE,
            sender=self._endpoint,
            recipient=EndpointInfo(id=capability_id, type=EndpointType.CAPABILITY),
            payload=HandshakePayload(),
        )
        self._maybe_sign(msg)
        response = await self._queue.request(msg, timeout=timeout)
        return response.payload  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Safety check
    # ------------------------------------------------------------------

    async def safety_check(
        self,
        capability_id: str,
        task_name: str,
        required_permissions: list[str] | None = None,
        required_env_vars: list[str] | None = None,
        resource_access: list[str] | None = None,
        sandbox_config: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """
        Request a pre-invocation safety assessment from *capability_id*.

        Returns ``True`` when the capability approves the invocation, raises
        :class:`~hcp.exceptions.SafetyCheckError` otherwise.
        """
        payload = SafetyCheckPayload(
            task_name=task_name,
            required_permissions=required_permissions or [],
            required_env_vars=required_env_vars or [],
            resource_access=resource_access or [],
            sandbox_config=sandbox_config or {},
        )
        msg = Message(
            type=MessageType.SAFETY_CHECK,
            sender=self._endpoint,
            recipient=EndpointInfo(id=capability_id, type=EndpointType.CAPABILITY),
            payload=payload,
        )
        self._maybe_sign(msg)
        response = await self._queue.request(msg, timeout=timeout)
        sr = response.payload  # SafetyResponsePayload
        if not sr.approved:  # type: ignore[union-attr]
            raise SafetyCheckError(sr.reason)  # type: ignore[union-attr]
        return True

    # ------------------------------------------------------------------
    # Task invocation
    # ------------------------------------------------------------------

    async def invoke(
        self,
        capability_id: str,
        task_name: str,
        args: dict[str, Any] | None = None,
        timeout: float | None = None,
        priority: int = 5,
        run_safety_check: bool = False,
    ) -> ResultPayload:
        """
        Dispatch a task to *capability_id* and wait for the result.

        Parameters
        ----------
        capability_id:
            Destination capability identifier.
        task_name:
            Name of the tool/function to execute.
        args:
            Keyword arguments forwarded to the capability.
        timeout:
            Override the default task timeout.
        priority:
            Task priority 0–9 (9 = highest).
        run_safety_check:
            When ``True``, perform a safety check before sending the task.

        Returns
        -------
        ResultPayload
            The execution result.

        Raises
        ------
        :class:`~hcp.exceptions.SafetyCheckError`
            If ``run_safety_check=True`` and the capability rejects the request.
        :class:`~hcp.exceptions.TimeoutError`
            If the capability does not respond within *timeout* seconds.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout

        if run_safety_check:
            await self.safety_check(
                capability_id=capability_id,
                task_name=task_name,
                timeout=effective_timeout,
            )

        task_id = str(uuid.uuid4())
        future: asyncio.Future[ResultPayload] = asyncio.get_event_loop().create_future()
        self._pending[task_id] = future

        payload = TaskPayload(
            task_id=task_id,
            name=task_name,
            args=args or {},
            timeout=effective_timeout,
            priority=priority,
        )
        msg = Message(
            type=MessageType.TASK,
            sender=self._endpoint,
            recipient=EndpointInfo(id=capability_id, type=EndpointType.CAPABILITY),
            payload=payload,
        )
        self._maybe_sign(msg)
        await self._queue.publish(msg)

        try:
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except asyncio.TimeoutError:
            self._pending.pop(task_id, None)
            raise TimeoutError(
                f"Task {task_id!r} to {capability_id!r} timed out "
                f"after {effective_timeout}s"
            )
        finally:
            self._pending.pop(task_id, None)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat(self, capability_id: str) -> None:
        """Send a HEARTBEAT to *capability_id* (fire-and-forget)."""
        from hcp.messages import HeartbeatPayload

        msg = Message(
            type=MessageType.HEARTBEAT,
            sender=self._endpoint,
            recipient=EndpointInfo(id=capability_id, type=EndpointType.CAPABILITY),
            payload=HeartbeatPayload(),
        )
        self._maybe_sign(msg)
        await self._queue.publish(msg)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_sign(self, message: Message) -> None:
        if self._secret is not None:
            from hcp.security import sign_message
            sign_message(message, self._secret)

    async def _on_message(self, message: Message) -> None:
        if message.type == MessageType.RESULT:
            result: ResultPayload = message.payload  # type: ignore[assignment]
            future = self._pending.get(result.task_id)
            if future is not None and not future.done():
                future.set_result(result)
        elif message.type == MessageType.EVENT:
            event: EventPayload = message.payload  # type: ignore[assignment]
            for cb in self._event_callbacks:
                await cb(event)
        elif message.type == MessageType.ERROR:
            # Resolve any pending future with a FAILURE result
            error = message.payload
            for task_id, future in list(self._pending.items()):
                if not future.done():
                    future.set_result(
                        ResultPayload(
                            task_id=task_id,
                            status=ResultStatus.FAILURE,
                            error=str(getattr(error, "message", error)),
                        )
                    )
