"""Tests for hcp.messages – envelope construction, serialisation, validation."""

import json
import uuid

import pytest

from hcp.exceptions import MessageValidationError, VersionMismatchError
from hcp.messages import (
    EndpointInfo,
    EndpointType,
    ErrorPayload,
    EventPayload,
    HandshakePayload,
    HeartbeatPayload,
    Message,
    MessageType,
    PROTOCOL_VERSION,
    ResultPayload,
    ResultStatus,
    SafetyCheckPayload,
    SafetyResponsePayload,
    TaskPayload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent() -> EndpointInfo:
    return EndpointInfo(id="agent-1", type=EndpointType.AGENT)


def make_capability() -> EndpointInfo:
    return EndpointInfo(id="cap-1", type=EndpointType.CAPABILITY)


def make_task_message(**kwargs) -> Message:
    defaults = dict(
        type=MessageType.TASK,
        sender=make_agent(),
        recipient=make_capability(),
        payload=TaskPayload(
            task_id=str(uuid.uuid4()),
            name="greet",
            args={"name": "world"},
        ),
    )
    defaults.update(kwargs)
    return Message(**defaults)


# ---------------------------------------------------------------------------
# EndpointInfo
# ---------------------------------------------------------------------------

class TestEndpointInfo:
    def test_round_trip(self):
        ep = EndpointInfo(id="my-agent", type=EndpointType.AGENT)
        assert EndpointInfo.from_dict(ep.to_dict()) == ep

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            EndpointInfo.from_dict({"id": "x", "type": "UNKNOWN"})


# ---------------------------------------------------------------------------
# Payload round-trips
# ---------------------------------------------------------------------------

class TestPayloads:
    def test_handshake_round_trip(self):
        p = HandshakePayload(capabilities=["calc"], protocol_versions=["1.0"])
        assert HandshakePayload.from_dict(p.to_dict()) == p

    def test_safety_check_round_trip(self):
        p = SafetyCheckPayload(
            task_name="add",
            required_permissions=["math"],
            required_env_vars=["HOME"],
        )
        assert SafetyCheckPayload.from_dict(p.to_dict()) == p

    def test_safety_response_round_trip(self):
        p = SafetyResponsePayload(
            approved=True,
            reason="All checks passed",
            approved_permissions=["math"],
        )
        assert SafetyResponsePayload.from_dict(p.to_dict()) == p

    def test_task_round_trip(self):
        p = TaskPayload(task_id="t1", name="run", args={"x": 1}, timeout=60, priority=7)
        assert TaskPayload.from_dict(p.to_dict()) == p

    def test_event_round_trip(self):
        p = EventPayload(task_id="t1", event_type="progress", data={"pct": 50})
        assert EventPayload.from_dict(p.to_dict()) == p

    def test_result_round_trip(self):
        p = ResultPayload(task_id="t1", status=ResultStatus.SUCCESS, output=42)
        assert ResultPayload.from_dict(p.to_dict()) == p

    def test_error_round_trip(self):
        p = ErrorPayload(code="E001", message="bad input", details={"field": "x"})
        assert ErrorPayload.from_dict(p.to_dict()) == p

    def test_heartbeat_round_trip(self):
        p = HeartbeatPayload(sequence=5)
        assert HeartbeatPayload.from_dict(p.to_dict()) == p


# ---------------------------------------------------------------------------
# Message envelope
# ---------------------------------------------------------------------------

class TestMessage:
    def test_auto_id_and_timestamp(self):
        msg = make_task_message()
        assert msg.id
        assert msg.timestamp
        assert msg.version == PROTOCOL_VERSION

    def test_to_dict_keys(self):
        msg = make_task_message()
        d = msg.to_dict()
        for key in ("id", "type", "version", "timestamp", "sender", "recipient", "payload"):
            assert key in d

    def test_json_round_trip(self):
        msg = make_task_message()
        msg2 = Message.from_json(msg.to_json())
        assert msg.id == msg2.id
        assert msg.type == msg2.type
        assert msg.payload.name == msg2.payload.name  # type: ignore[union-attr]

    def test_from_dict_round_trip_all_types(self):
        payloads = [
            (MessageType.HANDSHAKE, HandshakePayload()),
            (MessageType.SAFETY_CHECK, SafetyCheckPayload(task_name="foo")),
            (MessageType.SAFETY_RESPONSE, SafetyResponsePayload(approved=True)),
            (MessageType.TASK, TaskPayload(task_id="t1", name="x")),
            (MessageType.EVENT, EventPayload(task_id="t1", event_type="e")),
            (MessageType.RESULT, ResultPayload(task_id="t1", status=ResultStatus.SUCCESS)),
            (MessageType.ERROR, ErrorPayload(code="C", message="m")),
            (MessageType.HEARTBEAT, HeartbeatPayload()),
        ]
        for msg_type, payload in payloads:
            msg = Message(
                type=msg_type,
                sender=make_agent(),
                recipient=make_capability(),
                payload=payload,
            )
            assert Message.from_dict(msg.to_dict()).type == msg_type

    def test_json_is_valid_json(self):
        msg = make_task_message()
        parsed = json.loads(msg.to_json())
        assert parsed["type"] == "TASK"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def test_validate_ok(self):
        make_task_message().validate()  # should not raise

    def test_validate_empty_id_raises(self):
        msg = make_task_message()
        msg.id = ""
        with pytest.raises(MessageValidationError):
            msg.validate()

    def test_validate_unsupported_version_raises(self):
        msg = make_task_message()
        msg.version = "99.0"
        with pytest.raises(VersionMismatchError):
            msg.validate()

    def test_validate_wrong_payload_type_raises(self):
        msg = make_task_message()
        msg.payload = HeartbeatPayload()  # wrong type for TASK message
        with pytest.raises(MessageValidationError):
            msg.validate()

    def test_validate_empty_sender_id_raises(self):
        msg = make_task_message()
        msg.sender = EndpointInfo(id="", type=EndpointType.AGENT)
        with pytest.raises(MessageValidationError):
            msg.validate()

    def test_validate_empty_recipient_id_raises(self):
        msg = make_task_message()
        msg.recipient = EndpointInfo(id="", type=EndpointType.CAPABILITY)
        with pytest.raises(MessageValidationError):
            msg.validate()

    def test_correlation_id(self):
        orig = make_task_message()
        response = make_task_message(correlation_id=orig.id)
        assert response.correlation_id == orig.id
