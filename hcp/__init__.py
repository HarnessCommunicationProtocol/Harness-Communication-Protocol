"""
HCP – Harness Communication Protocol
=====================================

An open message-queue-based protocol that enables secure communication between
AI agents and executable capabilities.

Quick start::

    from hcp import HCPQueue, Agent, Capability, CapabilityManifest

Public API surface
------------------
* :class:`~hcp.messages.Message` and all message-type dataclasses
* :class:`~hcp.queue.HCPQueue`
* :class:`~hcp.agent.Agent`
* :class:`~hcp.capability.Capability`
* :class:`~hcp.security.CapabilityManifest`, :func:`~hcp.security.sign_message`,
  :func:`~hcp.security.verify_message`
* All exceptions from :mod:`hcp.exceptions`
"""

from hcp.agent import Agent
from hcp.capability import Capability
from hcp.exceptions import (
    CapabilityNotFoundError,
    HCPError,
    MessageValidationError,
    QueueError,
    SafetyCheckError,
    SignatureError,
    TimeoutError,
    VersionMismatchError,
)
from hcp.messages import (
    EndpointInfo,
    EndpointType,
    ErrorPayload,
    EventPayload,
    HandshakePayload,
    HeartbeatPayload,
    Message,
    MessageType,
    ResultPayload,
    ResultStatus,
    SafetyCheckPayload,
    SafetyResponsePayload,
    TaskPayload,
)
from hcp.queue import HCPQueue
from hcp.security import CapabilityManifest, sign_message, verify_message

__version__ = "0.1.0"
__all__ = [
    # Core classes
    "Agent",
    "Capability",
    "HCPQueue",
    # Messages
    "Message",
    "MessageType",
    "EndpointInfo",
    "EndpointType",
    "TaskPayload",
    "EventPayload",
    "ResultPayload",
    "ResultStatus",
    "HandshakePayload",
    "SafetyCheckPayload",
    "SafetyResponsePayload",
    "ErrorPayload",
    "HeartbeatPayload",
    # Security
    "CapabilityManifest",
    "sign_message",
    "verify_message",
    # Exceptions
    "HCPError",
    "MessageValidationError",
    "SignatureError",
    "SafetyCheckError",
    "CapabilityNotFoundError",
    "QueueError",
    "TimeoutError",
    "VersionMismatchError",
]
