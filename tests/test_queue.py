"""Tests for hcp.queue – publish, subscribe, routing, request/reply."""

import asyncio

import pytest

from hcp.exceptions import QueueError
from hcp.messages import (
    EndpointInfo,
    EndpointType,
    HeartbeatPayload,
    Message,
    MessageType,
    TaskPayload,
)
from hcp.queue import HCPQueue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task_msg(sender_id="agent-1", recipient_id="cap-1") -> Message:
    return Message(
        type=MessageType.TASK,
        sender=EndpointInfo(id=sender_id, type=EndpointType.AGENT),
        recipient=EndpointInfo(id=recipient_id, type=EndpointType.CAPABILITY),
        payload=TaskPayload(task_id="t1", name="run", args={}),
    )


def make_heartbeat_msg(sender_id="agent-1", recipient_id="cap-1") -> Message:
    return Message(
        type=MessageType.HEARTBEAT,
        sender=EndpointInfo(id=sender_id, type=EndpointType.AGENT),
        recipient=EndpointInfo(id=recipient_id, type=EndpointType.CAPABILITY),
        payload=HeartbeatPayload(),
    )


# ---------------------------------------------------------------------------
# Queue lifecycle
# ---------------------------------------------------------------------------

class TestHCPQueueLifecycle:
    async def test_publish_before_start_raises(self):
        q = HCPQueue()
        with pytest.raises(QueueError):
            await q.publish(make_task_msg())

    async def test_start_stop(self):
        q = HCPQueue()
        await q.start()
        await q.stop()  # should not raise

    async def test_double_start_is_safe(self):
        q = HCPQueue()
        await q.start()
        await q.start()  # idempotent
        await q.stop()

    async def test_double_stop_is_safe(self):
        q = HCPQueue()
        await q.start()
        await q.stop()
        await q.stop()  # idempotent – no exception


# ---------------------------------------------------------------------------
# Subscribe / Publish
# ---------------------------------------------------------------------------

class TestHCPQueueRouting:
    async def test_message_delivered_to_subscriber(self):
        q = HCPQueue()
        await q.start()
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        q.subscribe("cap-1", handler)
        msg = make_task_msg(recipient_id="cap-1")
        await q.publish(msg)
        await asyncio.sleep(0.2)
        assert len(received) == 1
        assert received[0].id == msg.id
        await q.stop()

    async def test_message_not_delivered_to_wrong_subscriber(self):
        q = HCPQueue()
        await q.start()
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        q.subscribe("cap-2", handler)
        await q.publish(make_task_msg(recipient_id="cap-1"))
        await asyncio.sleep(0.2)
        assert received == []
        await q.stop()

    async def test_wildcard_subscriber_receives_all(self):
        q = HCPQueue()
        await q.start()
        all_msgs: list[Message] = []

        async def handler(msg: Message) -> None:
            all_msgs.append(msg)

        q.subscribe("*", handler)
        await q.publish(make_task_msg(recipient_id="cap-1"))
        await q.publish(make_task_msg(recipient_id="cap-2"))
        await asyncio.sleep(0.2)
        assert len(all_msgs) == 2
        await q.stop()

    async def test_multiple_subscribers_same_id(self):
        q = HCPQueue()
        await q.start()
        counts = [0, 0]

        async def h1(msg: Message) -> None:
            counts[0] += 1

        async def h2(msg: Message) -> None:
            counts[1] += 1

        q.subscribe("cap-1", h1)
        q.subscribe("cap-1", h2)
        await q.publish(make_task_msg(recipient_id="cap-1"))
        await asyncio.sleep(0.2)
        assert counts == [1, 1]
        await q.stop()

    async def test_unsubscribe_stops_delivery(self):
        q = HCPQueue()
        await q.start()
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        q.subscribe("cap-1", handler)
        q.unsubscribe("cap-1", handler)
        await q.publish(make_task_msg(recipient_id="cap-1"))
        await asyncio.sleep(0.2)
        assert received == []
        await q.stop()

    async def test_handler_exception_does_not_crash_queue(self):
        q = HCPQueue()
        await q.start()
        good_received: list[Message] = []

        async def bad_handler(msg: Message) -> None:
            raise RuntimeError("boom")

        async def good_handler(msg: Message) -> None:
            good_received.append(msg)

        q.subscribe("cap-1", bad_handler)
        q.subscribe("cap-1", good_handler)
        await q.publish(make_task_msg(recipient_id="cap-1"))
        await asyncio.sleep(0.2)
        assert len(good_received) == 1  # good handler still got the message
        await q.stop()


# ---------------------------------------------------------------------------
# Request / Reply
# ---------------------------------------------------------------------------

class TestHCPQueueRequest:
    async def test_request_returns_correlated_response(self):
        q = HCPQueue()
        await q.start()

        # Simulate a capability that echoes back
        async def echo_handler(msg: Message) -> None:
            response = Message(
                type=MessageType.HEARTBEAT,
                sender=msg.recipient,
                recipient=msg.sender,
                correlation_id=msg.id,
                payload=HeartbeatPayload(),
            )
            await q.publish(response)

        q.subscribe("cap-1", echo_handler)

        msg = make_heartbeat_msg(sender_id="agent-1", recipient_id="cap-1")
        response = await q.request(msg, timeout=2.0)
        assert response.correlation_id == msg.id
        await q.stop()

    async def test_request_times_out(self):
        q = HCPQueue()
        await q.start()
        msg = make_heartbeat_msg(sender_id="agent-1", recipient_id="nobody")
        with pytest.raises(asyncio.TimeoutError):
            await q.request(msg, timeout=0.1)
        await q.stop()
