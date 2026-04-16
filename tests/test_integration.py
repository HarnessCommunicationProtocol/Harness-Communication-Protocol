"""
End-to-end integration tests.

These tests wire up a full Agent ↔ Capability pair through HCPQueue and
exercise realistic multi-step flows including handshake, safety check,
task dispatch, event streaming, and result collection.
"""

import asyncio
from typing import Any

import pytest

from hcp import (
    Agent,
    Capability,
    CapabilityManifest,
    HCPQueue,
    sign_message,
    verify_message,
)
from hcp.messages import ResultStatus


# ---------------------------------------------------------------------------
# Capabilities used in tests
# ---------------------------------------------------------------------------

class CalculatorCapability(Capability):
    async def execute(self, task_name: str, args: dict[str, Any]) -> Any:
        if task_name == "add":
            return args["a"] + args["b"]
        if task_name == "multiply":
            return args["a"] * args["b"]
        raise NotImplementedError(task_name)


class CounterCapability(Capability):
    """Emits progress events then returns a count."""

    async def execute(self, task_name: str, args: dict[str, Any]) -> Any:
        n = int(args.get("n", 3))
        for i in range(n):
            await self.emit_event(
                recipient_id=args["agent_id"],
                task_id=args["task_id"],
                event_type="tick",
                data={"i": i},
            )
        return n


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
async def calc_cap(queue):
    cap = CalculatorCapability(
        capability_id="calc",
        queue=queue,
        manifest=CapabilityManifest(
            name="calc",
            allowed_permissions=["math"],
        ),
    )
    await cap.register()
    yield cap
    await cap.unregister()


@pytest.fixture
async def agent(queue):
    a = Agent(agent_id="agent-1", queue=queue, default_timeout=5.0)
    await a.connect()
    yield a
    await a.disconnect()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEndToEnd:
    async def test_add(self, agent, calc_cap):
        result = await agent.invoke("calc", "add", args={"a": 10, "b": 32})
        assert result.status == ResultStatus.SUCCESS
        assert result.output == 42

    async def test_multiply(self, agent, calc_cap):
        result = await agent.invoke("calc", "multiply", args={"a": 6, "b": 7})
        assert result.status == ResultStatus.SUCCESS
        assert result.output == 42

    async def test_unknown_task_returns_failure(self, agent, calc_cap):
        result = await agent.invoke("calc", "sqrt", args={"x": 9})
        assert result.status == ResultStatus.FAILURE

    async def test_full_flow_handshake_safety_task(self, agent, calc_cap):
        # 1. Handshake
        hs = await agent.handshake("calc")
        assert "calc" in hs.capabilities

        # 2. Safety check
        approved = await agent.safety_check(
            capability_id="calc",
            task_name="add",
            required_permissions=["math"],
        )
        assert approved is True

        # 3. Task
        result = await agent.invoke("calc", "add", args={"a": 1, "b": 1})
        assert result.output == 2

    async def test_event_streaming(self, queue):
        """Agent receives progress events during a long task."""
        cap = CounterCapability(
            capability_id="counter",
            queue=queue,
            manifest=CapabilityManifest(name="counter"),
        )
        await cap.register()

        a = Agent(agent_id="agent-2", queue=queue, default_timeout=5.0)
        await a.connect()

        ticks: list[dict] = []

        async def on_event(event):
            ticks.append(event.data)

        a.on_event(on_event)

        import uuid
        task_id = str(uuid.uuid4())
        result = await a.invoke(
            "counter",
            "count",
            args={"n": 3, "agent_id": "agent-2", "task_id": task_id},
        )
        await asyncio.sleep(0.2)
        assert result.status == ResultStatus.SUCCESS
        assert result.output == 3
        assert len(ticks) == 3

        await a.disconnect()
        await cap.unregister()


class TestSignedEndToEnd:
    """Verify that signing + verification works across agent/capability."""

    SECRET = b"shared-secret-42"

    async def test_signed_add(self, queue):
        cap = CalculatorCapability(
            capability_id="signed-calc",
            queue=queue,
            manifest=CapabilityManifest(name="signed-calc", allowed_permissions=["math"]),
            secret=self.SECRET,
        )
        await cap.register()

        a = Agent(
            agent_id="signed-agent",
            queue=queue,
            secret=self.SECRET,
            default_timeout=5.0,
        )
        await a.connect()

        result = await a.invoke("signed-calc", "add", args={"a": 5, "b": 5})
        assert result.status == ResultStatus.SUCCESS
        assert result.output == 10

        await a.disconnect()
        await cap.unregister()

    async def test_unsigned_message_rejected_by_signed_capability(self, queue):
        """Capability with a secret rejects unsigned messages."""
        cap = CalculatorCapability(
            capability_id="strict-calc",
            queue=queue,
            manifest=CapabilityManifest(name="strict-calc"),
            secret=self.SECRET,
        )
        await cap.register()

        # Agent without secret sends unsigned message
        a = Agent(agent_id="unsigned-agent", queue=queue, default_timeout=2.0)
        await a.connect()

        # The capability should emit an ERROR message instead of a RESULT
        errors: list = []
        from hcp.messages import Message, MessageType

        async def collector(msg: Message) -> None:
            if msg.type == MessageType.ERROR:
                errors.append(msg)

        queue.subscribe("unsigned-agent", collector)
        result = await a.invoke("strict-calc", "add", args={"a": 1, "b": 1})
        await asyncio.sleep(0.2)

        # The agent should have received an ERROR (which sets result to FAILURE)
        assert result.status == ResultStatus.FAILURE

        await a.disconnect()
        await cap.unregister()
