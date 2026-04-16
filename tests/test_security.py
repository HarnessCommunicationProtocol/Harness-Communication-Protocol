"""Tests for hcp.security – signing, verification, manifest, and safety validator."""

import os

import pytest

from hcp.exceptions import SafetyCheckError, SignatureError
from hcp.messages import (
    EndpointInfo,
    EndpointType,
    Message,
    MessageType,
    SafetyCheckPayload,
    TaskPayload,
)
from hcp.security import CapabilityManifest, SafetyValidator, sign_message, verify_message

SECRET = b"super-secret-key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task_msg() -> Message:
    return Message(
        type=MessageType.TASK,
        sender=EndpointInfo(id="agent-1", type=EndpointType.AGENT),
        recipient=EndpointInfo(id="cap-1", type=EndpointType.CAPABILITY),
        payload=TaskPayload(task_id="t1", name="greet", args={"name": "world"}),
    )


def make_manifest(**kwargs) -> CapabilityManifest:
    defaults = dict(
        name="my-cap",
        allowed_permissions=["math", "fs:read"],
        required_env_vars=[],
    )
    defaults.update(kwargs)
    return CapabilityManifest(**defaults)


# ---------------------------------------------------------------------------
# Signing & Verification
# ---------------------------------------------------------------------------

class TestSigning:
    def test_sign_sets_signature(self):
        msg = make_task_msg()
        assert msg.signature == ""
        sign_message(msg, SECRET)
        assert msg.signature != ""

    def test_verify_passes_after_sign(self):
        msg = make_task_msg()
        sign_message(msg, SECRET)
        verify_message(msg, SECRET)  # should not raise

    def test_verify_fails_wrong_secret(self):
        msg = make_task_msg()
        sign_message(msg, SECRET)
        with pytest.raises(SignatureError):
            verify_message(msg, b"wrong-secret")

    def test_verify_fails_tampered_payload(self):
        msg = make_task_msg()
        sign_message(msg, SECRET)
        msg.payload.name = "hacked"  # type: ignore[union-attr]
        with pytest.raises(SignatureError):
            verify_message(msg, SECRET)

    def test_verify_fails_no_signature(self):
        msg = make_task_msg()
        with pytest.raises(SignatureError):
            verify_message(msg, SECRET)

    def test_sign_with_string_secret(self):
        msg = make_task_msg()
        sign_message(msg, "string-secret")
        verify_message(msg, "string-secret")

    def test_sign_is_idempotent(self):
        """Signing the same message twice yields the same signature."""
        msg1 = make_task_msg()
        msg2 = make_task_msg()
        msg1.id = msg2.id = "fixed-id"
        msg1.timestamp = msg2.timestamp = "2024-01-01T00:00:00+00:00"
        sign_message(msg1, SECRET)
        sign_message(msg2, SECRET)
        assert msg1.signature == msg2.signature


# ---------------------------------------------------------------------------
# CapabilityManifest
# ---------------------------------------------------------------------------

class TestCapabilityManifest:
    def test_round_trip(self):
        m = make_manifest(description="A test cap", metadata={"owner": "team-a"})
        assert CapabilityManifest.from_dict(m.to_dict()) == m

    def test_defaults(self):
        m = CapabilityManifest(name="bare")
        assert m.allowed_permissions == []
        assert m.required_env_vars == []
        assert m.resource_access == []


# ---------------------------------------------------------------------------
# SafetyValidator
# ---------------------------------------------------------------------------

class TestSafetyValidator:
    def test_approved_when_all_permissions_allowed(self):
        manifest = make_manifest(allowed_permissions=["math", "fs:read"])
        validator = SafetyValidator(manifest)
        check = SafetyCheckPayload(
            task_name="add",
            required_permissions=["math"],
        )
        result = validator.validate(check)
        assert result.approved is True
        assert result.approved_permissions == ["math"]

    def test_rejected_when_permission_not_in_manifest(self):
        manifest = make_manifest(allowed_permissions=["math"])
        validator = SafetyValidator(manifest)
        check = SafetyCheckPayload(
            task_name="delete_all",
            required_permissions=["fs:write"],
        )
        result = validator.validate(check)
        assert result.approved is False
        assert "fs:write" in result.reason

    def test_approved_when_no_permissions_required(self):
        manifest = make_manifest(allowed_permissions=[])
        validator = SafetyValidator(manifest)
        check = SafetyCheckPayload(task_name="ping")
        result = validator.validate(check)
        assert result.approved is True

    def test_rejected_when_env_var_missing(self):
        manifest = make_manifest(required_env_vars=["DEFINITELY_NOT_SET_XYZ"])
        validator = SafetyValidator(manifest)
        check = SafetyCheckPayload(
            task_name="fetch",
            required_env_vars=["DEFINITELY_NOT_SET_XYZ"],
        )
        # Ensure it's not set
        os.environ.pop("DEFINITELY_NOT_SET_XYZ", None)
        result = validator.validate(check)
        assert result.approved is False
        assert not result.environment_valid
        assert "DEFINITELY_NOT_SET_XYZ" in result.missing_env_vars

    def test_approved_when_env_var_present(self, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "secret")
        manifest = make_manifest()
        validator = SafetyValidator(manifest)
        check = SafetyCheckPayload(
            task_name="call_api",
            required_env_vars=["MY_API_KEY"],
        )
        result = validator.validate(check)
        assert result.environment_valid is True
        assert result.missing_env_vars == []

    def test_validate_or_raise_raises_on_failure(self):
        manifest = make_manifest(allowed_permissions=[])
        validator = SafetyValidator(manifest)
        check = SafetyCheckPayload(
            task_name="danger",
            required_permissions=["root"],
        )
        with pytest.raises(SafetyCheckError):
            validator.validate_or_raise(check)

    def test_validate_or_raise_returns_response_on_success(self):
        manifest = make_manifest(allowed_permissions=["safe"])
        validator = SafetyValidator(manifest)
        check = SafetyCheckPayload(
            task_name="safe_op",
            required_permissions=["safe"],
        )
        response = validator.validate_or_raise(check)
        assert response.approved is True
