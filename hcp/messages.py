"""
HCP message types and the :class:`Message` envelope.

Every piece of data exchanged over HCP is wrapped in a ``Message``.  The
``payload`` field holds a type-specific dataclass whose type is determined by
``Message.type``.

Message flow (happy path)
-------------------------
::

    Agent                            Capability
      |                                  |
      |--- HANDSHAKE ------------------->|
      |<-- HANDSHAKE (ack) --------------|
      |                                  |
      |--- SAFETY_CHECK ---------------->|
      |<-- SAFETY_RESPONSE (approved) ---|
      |                                  |
      |--- TASK ------------------------>|
      |<-- EVENT (progress) -------------|
      |<-- RESULT ----------------------|
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from hcp.exceptions import MessageValidationError, VersionMismatchError

PROTOCOL_VERSION = "1.0"
SUPPORTED_VERSIONS = {"1.0"}


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MessageType(str, Enum):
    """All message types defined by the HCP specification."""

    HANDSHAKE = "HANDSHAKE"
    SAFETY_CHECK = "SAFETY_CHECK"
    SAFETY_RESPONSE = "SAFETY_RESPONSE"
    TASK = "TASK"
    EVENT = "EVENT"
    RESULT = "RESULT"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"


class EndpointType(str, Enum):
    """Identifies whether an endpoint is an AI agent or a capability."""

    AGENT = "AGENT"
    CAPABILITY = "CAPABILITY"


class ResultStatus(str, Enum):
    """Terminal statuses for a task result."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Endpoint descriptor
# ---------------------------------------------------------------------------


@dataclass
class EndpointInfo:
    """Identifies one side of a communication channel."""

    id: str
    type: EndpointType

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "type": self.type.value}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "EndpointInfo":
        return cls(id=data["id"], type=EndpointType(data["type"]))


# ---------------------------------------------------------------------------
# Payload dataclasses
# ---------------------------------------------------------------------------


@dataclass
class HandshakePayload:
    """Exchanged at connection time to negotiate capabilities and versions."""

    capabilities: list[str] = field(default_factory=list)
    """Names of capabilities the sender exposes (empty for agents)."""
    protocol_versions: list[str] = field(default_factory=lambda: [PROTOCOL_VERSION])
    """Protocol versions the sender supports."""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": self.capabilities,
            "protocol_versions": self.protocol_versions,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HandshakePayload":
        return cls(
            capabilities=data.get("capabilities", []),
            protocol_versions=data.get("protocol_versions", [PROTOCOL_VERSION]),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SafetyCheckPayload:
    """Sent by an agent to request a pre-invocation safety assessment."""

    task_name: str
    """Name of the capability/tool to be invoked."""
    required_permissions: list[str] = field(default_factory=list)
    """Permissions the task will exercise (e.g. ``"fs:write"``, ``"net:egress"``)."""
    required_env_vars: list[str] = field(default_factory=list)
    """Environment variables that must be present."""
    resource_access: list[str] = field(default_factory=list)
    """External resources (URLs, file paths, service names) that will be accessed."""
    sandbox_config: dict[str, Any] = field(default_factory=dict)
    """Optional sandbox/container constraints to apply."""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "required_permissions": self.required_permissions,
            "required_env_vars": self.required_env_vars,
            "resource_access": self.resource_access,
            "sandbox_config": self.sandbox_config,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyCheckPayload":
        return cls(
            task_name=data["task_name"],
            required_permissions=data.get("required_permissions", []),
            required_env_vars=data.get("required_env_vars", []),
            resource_access=data.get("resource_access", []),
            sandbox_config=data.get("sandbox_config", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SafetyResponsePayload:
    """Returned by a capability to indicate whether it is safe to invoke."""

    approved: bool
    reason: str = ""
    """Human-readable explanation, required when ``approved`` is ``False``."""
    approved_permissions: list[str] = field(default_factory=list)
    """Subset of requested permissions that are actually granted."""
    environment_valid: bool = True
    """``True`` if all required env vars were found."""
    missing_env_vars: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "approved_permissions": self.approved_permissions,
            "environment_valid": self.environment_valid,
            "missing_env_vars": self.missing_env_vars,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyResponsePayload":
        return cls(
            approved=data["approved"],
            reason=data.get("reason", ""),
            approved_permissions=data.get("approved_permissions", []),
            environment_valid=data.get("environment_valid", True),
            missing_env_vars=data.get("missing_env_vars", []),
        )


@dataclass
class TaskPayload:
    """Carries an invocation request from an agent to a capability."""

    task_id: str
    """Unique ID for this task invocation (set by the sender)."""
    name: str
    """Name of the tool/function to execute."""
    args: dict[str, Any] = field(default_factory=dict)
    """Keyword arguments for the tool."""
    timeout: float = 30.0
    """Maximum allowed execution time in seconds."""
    priority: int = 5
    """0 (lowest) – 9 (highest)."""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "args": self.args,
            "timeout": self.timeout,
            "priority": self.priority,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPayload":
        return cls(
            task_id=data["task_id"],
            name=data["name"],
            args=data.get("args", {}),
            timeout=float(data.get("timeout", 30.0)),
            priority=int(data.get("priority", 5)),
            metadata=data.get("metadata", {}),
        )


@dataclass
class EventPayload:
    """Asynchronous notification emitted by a capability during task execution."""

    task_id: str
    event_type: str
    """Free-form event type string (e.g. ``"progress"``, ``"log"``, ``"warning"``)."""
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "event_type": self.event_type,
            "data": self.data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventPayload":
        return cls(
            task_id=data["task_id"],
            event_type=data["event_type"],
            data=data.get("data", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ResultPayload:
    """Terminal outcome of a task execution."""

    task_id: str
    status: ResultStatus
    output: Any = None
    """Return value of the capability (must be JSON-serialisable)."""
    error: str = ""
    """Error message, populated when ``status != SUCCESS``."""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResultPayload":
        return cls(
            task_id=data["task_id"],
            status=ResultStatus(data["status"]),
            output=data.get("output"),
            error=data.get("error", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ErrorPayload:
    """Protocol-level error (not a task failure)."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ErrorPayload":
        return cls(
            code=data["code"],
            message=data["message"],
            details=data.get("details", {}),
        )


@dataclass
class HeartbeatPayload:
    """Periodic liveness signal."""

    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HeartbeatPayload":
        return cls(
            sequence=int(data.get("sequence", 0)),
            metadata=data.get("metadata", {}),
        )


# Mapping from MessageType → payload class (for deserialisation)
_PAYLOAD_CLASSES: dict[MessageType, type] = {
    MessageType.HANDSHAKE: HandshakePayload,
    MessageType.SAFETY_CHECK: SafetyCheckPayload,
    MessageType.SAFETY_RESPONSE: SafetyResponsePayload,
    MessageType.TASK: TaskPayload,
    MessageType.EVENT: EventPayload,
    MessageType.RESULT: ResultPayload,
    MessageType.ERROR: ErrorPayload,
    MessageType.HEARTBEAT: HeartbeatPayload,
}

# Union type for all payload types
AnyPayload = (
    HandshakePayload
    | SafetyCheckPayload
    | SafetyResponsePayload
    | TaskPayload
    | EventPayload
    | ResultPayload
    | ErrorPayload
    | HeartbeatPayload
)


# ---------------------------------------------------------------------------
# Message envelope
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """
    The top-level envelope that wraps every HCP message.

    Parameters
    ----------
    type:
        The :class:`MessageType` that governs how ``payload`` is interpreted.
    sender:
        :class:`EndpointInfo` describing the originating endpoint.
    recipient:
        :class:`EndpointInfo` describing the destination endpoint.
    payload:
        A typed payload object matching ``type``.
    id:
        Unique message identifier (UUID4).  Auto-generated when omitted.
    correlation_id:
        Used to correlate responses with their originating requests.
    version:
        Protocol version string.  Defaults to :data:`PROTOCOL_VERSION`.
    timestamp:
        UTC creation time.  Auto-generated when omitted.
    signature:
        HMAC-SHA256 hex-digest set by :func:`~hcp.security.sign_message`.
    metadata:
        Arbitrary key/value pairs for extension data.
    """

    type: MessageType
    sender: EndpointInfo
    recipient: EndpointInfo
    payload: AnyPayload
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = ""
    version: str = PROTOCOL_VERSION
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )
    signature: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Raise :class:`~hcp.exceptions.MessageValidationError` if the message
        is structurally invalid, or :class:`~hcp.exceptions.VersionMismatchError`
        if the protocol version is not supported.
        """
        if not self.id:
            raise MessageValidationError("Message.id must not be empty")
        if self.version not in SUPPORTED_VERSIONS:
            raise VersionMismatchError(
                f"Unsupported protocol version: {self.version!r}. "
                f"Supported: {SUPPORTED_VERSIONS}"
            )
        if not isinstance(self.sender, EndpointInfo):
            raise MessageValidationError("Message.sender must be an EndpointInfo")
        if not isinstance(self.recipient, EndpointInfo):
            raise MessageValidationError("Message.recipient must be an EndpointInfo")
        if not self.sender.id:
            raise MessageValidationError("sender.id must not be empty")
        if not self.recipient.id:
            raise MessageValidationError("recipient.id must not be empty")
        expected_cls = _PAYLOAD_CLASSES.get(self.type)
        if expected_cls is not None and not isinstance(self.payload, expected_cls):
            raise MessageValidationError(
                f"Payload type mismatch: expected {expected_cls.__name__} "
                f"for message type {self.type.value}, "
                f"got {type(self.payload).__name__}"
            )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the message."""
        return {
            "id": self.id,
            "type": self.type.value,
            "version": self.version,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "signature": self.signature,
            "sender": self.sender.to_dict(),
            "recipient": self.recipient.to_dict(),
            "payload": self.payload.to_dict(),
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialise the message to a JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Deserialise a message from a plain dictionary."""
        msg_type = MessageType(data["type"])
        payload_cls = _PAYLOAD_CLASSES[msg_type]
        return cls(
            id=data["id"],
            type=msg_type,
            version=data.get("version", PROTOCOL_VERSION),
            timestamp=data.get("timestamp", ""),
            correlation_id=data.get("correlation_id", ""),
            signature=data.get("signature", ""),
            sender=EndpointInfo.from_dict(data["sender"]),
            recipient=EndpointInfo.from_dict(data["recipient"]),
            payload=payload_cls.from_dict(data["payload"]),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        """Deserialise a message from a JSON string."""
        return cls.from_dict(json.loads(raw))
