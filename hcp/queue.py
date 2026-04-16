"""
Async message queue for HCP.

:class:`HCPQueue` is a lightweight, in-process, topic-routed async queue that
implements the transport abstraction required by the protocol.  For production
deployments the :class:`QueueAdapter` abstract base class provides the
extension point for plugging in external brokers (Redis Streams, RabbitMQ,
Kafka, …).

Routing
-------
Messages are delivered to *subscribers* that have been registered for a
specific ``recipient.id``.  A subscriber registered with ``recipient_id="*"``
receives a copy of every message (broadcast).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Awaitable, Callable

from hcp.exceptions import QueueError
from hcp.messages import Message


# ---------------------------------------------------------------------------
# Callback type alias
# ---------------------------------------------------------------------------

MessageHandler = Callable[[Message], Awaitable[None]]


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class QueueAdapter(ABC):
    """
    Extension point for plugging HCP into an external message broker.

    Implementors must provide :meth:`publish` and :meth:`consume`.
    """

    @abstractmethod
    async def publish(self, message: Message) -> None:
        """Send *message* to the underlying broker."""

    @abstractmethod
    async def consume(self, recipient_id: str, handler: MessageHandler) -> None:
        """
        Begin consuming messages addressed to *recipient_id* from the broker,
        dispatching each to *handler*.
        """


# ---------------------------------------------------------------------------
# In-process queue
# ---------------------------------------------------------------------------


class HCPQueue:
    """
    In-process async message queue for HCP.

    Features
    --------
    * Delivers messages to handlers registered for a ``recipient_id``.
    * Supports wildcard subscription (``recipient_id="*"``) for monitoring.
    * Optional external :class:`QueueAdapter` for bridging to a real broker.
    * Non-blocking :meth:`publish` (handlers run as background tasks).

    Parameters
    ----------
    adapter:
        Optional external broker adapter.  When provided, :meth:`publish`
        additionally forwards the message to the external broker.
    maxsize:
        Maximum number of pending messages in the internal buffer before
        :meth:`publish` blocks.  ``0`` means unbounded.
    """

    def __init__(
        self,
        adapter: QueueAdapter | None = None,
        maxsize: int = 0,
    ) -> None:
        self._adapter = adapter
        # recipient_id → list of async handlers
        self._subscribers: defaultdict[str, list[MessageHandler]] = defaultdict(list)
        self._queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=maxsize)
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the internal dispatcher loop."""
        if self._running:
            return
        self._running = True
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        """Drain the queue and stop the dispatcher loop."""
        self._running = False
        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None

    # ------------------------------------------------------------------
    # Publish / Subscribe
    # ------------------------------------------------------------------

    def subscribe(self, recipient_id: str, handler: MessageHandler) -> None:
        """
        Register an async *handler* to receive messages for *recipient_id*.

        Use ``recipient_id="*"`` to receive all messages.

        Parameters
        ----------
        recipient_id:
            The endpoint ID to listen on, or ``"*"`` for all messages.
        handler:
            An async callable ``async def handler(message: Message) -> None``.
        """
        self._subscribers[recipient_id].append(handler)

    def unsubscribe(self, recipient_id: str, handler: MessageHandler) -> None:
        """Remove a previously registered *handler* for *recipient_id*."""
        if recipient_id in self._subscribers:
            try:
                self._subscribers[recipient_id].remove(handler)
            except ValueError:
                pass

    async def publish(self, message: Message) -> None:
        """
        Enqueue *message* for delivery.

        If an :class:`QueueAdapter` is configured the message is also forwarded
        to the external broker.

        Parameters
        ----------
        message:
            A valid :class:`~hcp.messages.Message`.

        Raises
        ------
        :class:`~hcp.exceptions.QueueError`
            If the queue is not running.
        """
        if not self._running:
            raise QueueError("Queue is not running. Call start() first.")
        await self._queue.put(message)
        if self._adapter is not None:
            await self._adapter.publish(message)

    # ------------------------------------------------------------------
    # Internal dispatch loop
    # ------------------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                message = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            await self._dispatch(message)
            self._queue.task_done()

    async def _dispatch(self, message: Message) -> None:
        """Deliver *message* to all matching handlers."""
        recipient_id = message.recipient.id
        targets = (
            list(self._subscribers.get(recipient_id, []))
            + list(self._subscribers.get("*", []))
        )
        if not targets:
            return
        results = await asyncio.gather(
            *[handler(message) for handler in targets],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                # Log but do not crash the dispatcher
                import logging
                logging.getLogger(__name__).error(
                    "Handler raised an exception for message %s: %s",
                    message.id,
                    result,
                    exc_info=result,
                )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    async def request(
        self,
        message: Message,
        timeout: float = 10.0,
    ) -> Message:
        """
        Publish *message* and wait for a correlated response.

        This helper registers a one-shot subscriber on the *sender's*
        ``recipient_id`` that listens for a message with a matching
        ``correlation_id``.

        Parameters
        ----------
        message:
            The request message to send.
        timeout:
            Seconds to wait before raising :class:`asyncio.TimeoutError`.

        Returns
        -------
        Message
            The first response whose ``correlation_id`` matches ``message.id``.
        """
        future: asyncio.Future[Message] = asyncio.get_event_loop().create_future()

        async def _handler(msg: Message) -> None:
            if not future.done() and msg.correlation_id == message.id:
                future.set_result(msg)

        self.subscribe(message.sender.id, _handler)
        try:
            await self.publish(message)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.unsubscribe(message.sender.id, _handler)
