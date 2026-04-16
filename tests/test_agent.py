"""Tests for hcp.agent – task dispatch, safety check, event handling."""

import asyncio

import pytest

from hcp.agent import Agent
from hcp.capability import Capability
from hcp.messages import (
    EndpointInfo,
    EndpointType,
    Message,
    MessageType,
    ResultPayload,
    ResultStatus,
    SafetyResponsePayload,
    TaskPayload,
)
from hcp.queue import HCPQueue
from hcp.security import CapabilityManifest


# ---------------------------------------------------------------------------
# Minimal stub capability
# ---------------------------------------------------------------------------

class EchoCapability(Capability):
    """Returns the args dict as output."""

    async def execute(self, task_name: str, args: dict) -> object:
        return {"echo": args}


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
async def agent(queue):
    a = Agent(agent_id="agent-1", queue=queue, default_timeout=5.0)
    await a.connect()
    yield a
    await a.disconnect()


@pytest.fixture
async def capability(queue):
    manifest = CapabilityManifest(
        name="echo",
        allowed_permissions=["read"],
        required_env_vars=[],
    )
    cap = EchoCapability(
        capability_id="echo",
        queue=queue,
        manifest=manifest,
    )
    await cap.register()
    yield cap
    await cap.unregister()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentConnect:
    async def test_connect_idempotent(self, queue):
        a = Agent(agent_id="a1", queue=queue)
        await a.connect()
        await a.connect()  # second call is no-op
        await a.disconnect()

    async def test_disconnect_idempotent(self, queue):
        a = Agent(agent_id="a1", queue=queue)
        await a.disconnect()  # never connected – no exception


class TestAgentInvoke:
    async def test_successful_invocation(self, agent, capability):
        result = await agent.invoke("echo", "run", args={"x": 42})
        assert result.status == ResultStatus.SUCCESS
        assert result.output == {"echo": {"x": 42}}

    async def test_invoke_times_out(self, queue, agent):
        """Capability that sleeps longer than the timeout."""

        class SlowCap(Capability):
            async def execute(self, task_name: str, args: dict) -> object:
                await asyncio.sleep(10)
                return "done"

        slow = SlowCap(
            capability_id="slow",
            queue=queue,
            manifest=CapabilityManifest(name="slow"),
        )
        await slow.register()
        from hcp.exceptions import TimeoutError as HCPTimeout
        with pytest.raises(HCPTimeout):
            await agent.invoke("slow", "run", timeout=0.2)
        await slow.unregister()

    async def test_invoke_failure_propagated(self, queue, agent):
        class BrokenCap(Capability):
            async def execute(self, task_name: str, args: dict) -> object:
                raise ValueError("intentional error")

        broken = BrokenCap(
            capability_id="broken",
            queue=queue,
            manifest=CapabilityManifest(name="broken"),
        )
        await broken.register()
        result = await agent.invoke("broken", "run")
        assert result.status == ResultStatus.FAILURE
        assert "intentional error" in result.error
        await broken.unregister()


class TestAgentSafetyCheck:
    async def test_safety_check_approved(self, agent, capability):
        approved = await agent.safety_check(
            capability_id="echo",
            task_name="echo",
            required_permissions=["read"],
        )
        assert approved is True

    async def test_safety_check_rejected_raises(self, agent, capability):
        from hcp.exceptions import SafetyCheckError
        with pytest.raises(SafetyCheckError):
            await agent.safety_check(
                capability_id="echo",
                task_name="echo",
                required_permissions=["fs:delete"],
            )

    async def test_invoke_with_safety_check(self, agent, capability):
        result = await agent.invoke(
            "echo", "run", args={"v": 1}, run_safety_check=True
        )
        assert result.status == ResultStatus.SUCCESS


class TestAgentHandshake:
    async def test_handshake_returns_payload(self, agent, capability):
        hs = await agent.handshake("echo")
        assert "echo" in hs.capabilities


class TestAgentEventHandling:
    async def test_event_callback_invoked(self, queue, agent):
        events = []

        class EventCap(Capability):
            async def execute(self, task_name: str, args: dict) -> object:
                await self.emit_event(
                    recipient_id="agent-1",
                    task_id=args.get("_task_id", "t"),
                    event_type="progress",
                    data={"pct": 50},
                )
                return "done"

        event_cap = EventCap(
            capability_id="ev-cap",
            queue=queue,
            manifest=CapabilityManifest(name="ev-cap"),
        )
        await event_cap.register()

        async def on_event(event):
            events.append(event)

        agent.on_event(on_event)
        await agent.invoke("ev-cap", "run")
        await asyncio.sleep(0.1)
        assert len(events) == 1
        assert events[0].event_type == "progress"
        await event_cap.unregister()
