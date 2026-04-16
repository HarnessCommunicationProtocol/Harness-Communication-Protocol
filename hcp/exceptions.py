"""Protocol-specific exceptions for HCP."""


class HCPError(Exception):
    """Base exception for all HCP errors."""


class MessageValidationError(HCPError):
    """Raised when a message fails schema or field validation."""


class SignatureError(HCPError):
    """Raised when message signature verification fails."""


class SafetyCheckError(HCPError):
    """Raised when a capability fails its pre-invocation safety check."""


class CapabilityNotFoundError(HCPError):
    """Raised when a referenced capability is not registered."""


class QueueError(HCPError):
    """Raised when the message queue encounters an unrecoverable condition."""


class TimeoutError(HCPError):  # noqa: A001
    """Raised when a task or safety-check times out."""


class VersionMismatchError(HCPError):
    """Raised when the protocol version in a message is not supported."""
