"""Tests for hcp.capability – safety handling, task execution, error cases."""

import asyncio
from typing import Any

import pytest

from hcp.capability import Capability
from hcp.messages import (
    EndpointInfo,
    EndpointType,
    Message,
    MessageType,
    ResultStatus,
    SafetyCheckPayload,
    TaskPayload,
)
from hcp.queue import HCPQueue
from hcp.security import CapabilityManifest


# ---------------------------------------------------------------------------
# Concrete capability for testing
# ---------------------------------------------------------------------------

class MathCapability(Capability):
    async def execute(self, task_name: str, args: dict[str, Any]) -> Any:
        if task_name == "add":
            return args["a"] + args["b"]
        if task_name == "divide":
            return args["a"] / args["b"]
        raise NotImplementedError(f"Unknown task: {task_name}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def queue():
    q = HCPQueue()
    await q.start()
    yield q
    await q.stop()


@pytest.fixture
async def math_cap(queue):
    manifest = CapabilityManifest(
        name="math",
        allowed_permissions=["math"],
    )
    cap = MathCapability(
        capability_id="math",
        queue=queue,
        manifest=manifest,
    )
    await cap.register()
    yield cap
    await cap.unregister()


def make_task_msg(
    task_name: str,
    args: dict,
    sender_id: str = "agent-1",
    recipient_id: str = "math",
    timeout: float = 5.0,
) -> Message:
    import uuid
    return Message(
        type=MessageType.TASK,
        sender=EndpointInfo(id=sender_id, type=EndpointType.AGENT),
        recipient=EndpointInfo(id=recipient_id, type=EndpointType.CAPABILITY),
        payload=TaskPayload(
            task_id=str(uuid.uuid4()),
            name=task_name,
            args=args,
            timeout=timeout,
        ),
    )


def make_safety_msg(
    task_name: str,
    permissions: list[str],
    sender_id: str = "agent-1",
    recipient_id: str = "math",
) -> Message:
    return Message(
        type=MessageType.SAFETY_CHECK,
        sender=EndpointInfo(id=sender_id, type=EndpointType.AGENT),
        recipient=EndpointInfo(id=recipient_id, type=EndpointType.CAPABILITY),
        payload=SafetyCheckPayload(
            task_name=task_name,
            required_permissions=permissions,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCapabilityRegister:
    async def test_register_idempotent(self, queue):
        cap = MathCapability(
            capability_id="m2",
            queue=queue,
            manifest=CapabilityManifest(name="m2"),
        )
        await cap.register()
        await cap.register()  # second call is no-op
        await cap.unregister()

    async def test_unregister_idempotent(self, queue):
        cap = MathCapability(
            capability_id="m3",
            queue=queue,
            manifest=CapabilityManifest(name="m3"),
        )
        await cap.unregister()  # never registered – no exception


class TestCapabilityTaskHandling:
    async def test_successful_task(self, queue, math_cap):
        results: list[Message] = []

        async def collector(msg: Message) -> None:
            results.append(msg)

        queue.subscribe("agent-1", collector)
        task_msg = make_task_msg("add", {"a": 3, "b": 4})
        await queue.publish(task_msg)
        await asyncio.sleep(0.2)

        assert len(results) == 1
        result = results[0].payload
        assert result.status == ResultStatus.SUCCESS
        assert result.output == 7

    async def test_task_exception_returns_failure(self, queue, math_cap):
        results: list[Message] = []

        async def collector(msg: Message) -> None:
            results.append(msg)

        queue.subscribe("agent-1", collector)
        # divide by zero
        task_msg = make_task_msg("divide", {"a": 1, "b": 0})
        await queue.publish(task_msg)
        await asyncio.sleep(0.2)

        assert len(results) == 1
        result = results[0].payload
        assert result.status == ResultStatus.FAILURE
        assert result.error != ""

    async def test_unknown_task_returns_failure(self, queue, math_cap):
        results: list[Message] = []

        async def collector(msg: Message) -> None:
            results.append(msg)

        queue.subscribe("agent-1", collector)
        task_msg = make_task_msg("unknown_op", {})
        await queue.publish(task_msg)
        await asyncio.sleep(0.2)

        assert len(results) == 1
        assert results[0].payload.status == ResultStatus.FAILURE

    async def test_task_timeout_returns_timeout_status(self, queue):
        class SlowCap(Capability):
            async def execute(self, task_name: str, args: dict) -> Any:
                await asyncio.sleep(10)

        cap = SlowCap(
            capability_id="slow",
            queue=queue,
            manifest=CapabilityManifest(name="slow"),
        )
        await cap.register()
        results: list[Message] = []

        async def collector(msg: Message) -> None:
            results.append(msg)

        queue.subscribe("agent-1", collector)
        task_msg = make_task_msg("run", {}, recipient_id="slow", timeout=0.1)
        await queue.publish(task_msg)
        await asyncio.sleep(0.5)

        assert len(results) == 1
        assert results[0].payload.status == ResultStatus.TIMEOUT
        await cap.unregister()


class TestCapabilitySafetyCheck:
    async def test_safety_check_approved(self, queue, math_cap):
        responses: list[Message] = []

        async def collector(msg: Message) -> None:
            responses.append(msg)

        queue.subscribe("agent-1", collector)
        safety_msg = make_safety_msg("add", ["math"])
        await queue.publish(safety_msg)
        await asyncio.sleep(0.2)

        assert len(responses) == 1
        assert responses[0].type == MessageType.SAFETY_RESPONSE
        assert responses[0].payload.approved is True

    async def test_safety_check_rejected(self, queue, math_cap):
        responses: list[Message] = []

        async def collector(msg: Message) -> None:
            responses.append(msg)

        queue.subscribe("agent-1", collector)
        safety_msg = make_safety_msg("delete_all", ["fs:delete"])
        await queue.publish(safety_msg)
        await asyncio.sleep(0.2)

        assert len(responses) == 1
        assert responses[0].payload.approved is False


class TestCapabilityHandshake:
    async def test_handshake_response(self, queue, math_cap):
        responses: list[Message] = []

        async def collector(msg: Message) -> None:
            responses.append(msg)

        queue.subscribe("agent-1", collector)
        from hcp.messages import HandshakePayload
        hs_msg = Message(
            type=MessageType.HANDSHAKE,
            sender=EndpointInfo(id="agent-1", type=EndpointType.AGENT),
            recipient=EndpointInfo(id="math", type=EndpointType.CAPABILITY),
            payload=HandshakePayload(),
        )
        await queue.publish(hs_msg)
        await asyncio.sleep(0.2)

        assert len(responses) == 1
        assert responses[0].type == MessageType.HANDSHAKE
        assert "math" in responses[0].payload.capabilities
