"""
Message signing, verification, and capability manifests.

Security model
--------------
* Every message is optionally signed with an HMAC-SHA256 digest computed over
  the canonical JSON representation of the message body (all fields except
  ``signature`` itself).
* The shared secret must be exchanged out-of-band between the agent and the
  capability before communication begins.
* A :class:`CapabilityManifest` declares what a capability is allowed to do,
  which the :class:`~hcp.capability.Capability` base class uses to respond to
  :class:`~hcp.messages.SafetyCheckPayload` requests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Any

from hcp.exceptions import SafetyCheckError, SignatureError
from hcp.messages import Message, SafetyCheckPayload, SafetyResponsePayload


# ---------------------------------------------------------------------------
# Message signing & verification
# ---------------------------------------------------------------------------


def _canonical_bytes(message: Message) -> bytes:
    """Return a stable, signature-free byte representation of *message*."""
    data = message.to_dict()
    data.pop("signature", None)
    return json.dumps(data, sort_keys=True, default=str).encode()


def sign_message(message: Message, secret: bytes | str) -> Message:
    """
    Compute and attach an HMAC-SHA256 signature to *message*.

    Parameters
    ----------
    message:
        The message to sign.  ``message.signature`` is overwritten.
    secret:
        Shared secret (bytes or UTF-8 string).

    Returns
    -------
    Message
        The same *message* object with ``signature`` set.
    """
    if isinstance(secret, str):
        secret = secret.encode()
    digest = hmac.new(secret, _canonical_bytes(message), hashlib.sha256).hexdigest()
    message.signature = digest
    return message


def verify_message(message: Message, secret: bytes | str) -> None:
    """
    Verify the HMAC-SHA256 signature of *message*.

    Parameters
    ----------
    message:
        The message whose ``signature`` field will be checked.
    secret:
        The same shared secret used when signing.

    Raises
    ------
    :class:`~hcp.exceptions.SignatureError`
        If the signature is absent or does not match.
    """
    if not message.signature:
        raise SignatureError("Message has no signature")
    if isinstance(secret, str):
        secret = secret.encode()
    stored = message.signature
    message.signature = ""
    try:
        expected = hmac.new(secret, _canonical_bytes(message), hashlib.sha256).hexdigest()
    finally:
        message.signature = stored
    if not hmac.compare_digest(stored, expected):
        raise SignatureError("Message signature verification failed")


# ---------------------------------------------------------------------------
# Capability manifest
# ---------------------------------------------------------------------------


@dataclass
class CapabilityManifest:
    """
    Declares the security profile of a single capability.

    Attributes
    ----------
    name:
        Unique capability name (matches the ``task_name`` in
        :class:`~hcp.messages.SafetyCheckPayload`).
    allowed_permissions:
        Permissions this capability is authorised to use.
    required_env_vars:
        Environment variables that *must* be present for the capability to
        function correctly.
    resource_access:
        Resources the capability is allowed to access.
    description:
        Human-readable description of what the capability does.
    metadata:
        Arbitrary extension data.
    """

    name: str
    allowed_permissions: list[str] = field(default_factory=list)
    required_env_vars: list[str] = field(default_factory=list)
    resource_access: list[str] = field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "allowed_permissions": self.allowed_permissions,
            "required_env_vars": self.required_env_vars,
            "resource_access": self.resource_access,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityManifest":
        return cls(
            name=data["name"],
            allowed_permissions=data.get("allowed_permissions", []),
            required_env_vars=data.get("required_env_vars", []),
            resource_access=data.get("resource_access", []),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Safety validator
# ---------------------------------------------------------------------------


class SafetyValidator:
    """
    Validates a :class:`~hcp.messages.SafetyCheckPayload` against a
    :class:`CapabilityManifest`.

    Parameters
    ----------
    manifest:
        The authoritative capability manifest.
    """

    def __init__(self, manifest: CapabilityManifest) -> None:
        self._manifest = manifest

    def validate(self, check: SafetyCheckPayload) -> SafetyResponsePayload:
        """
        Run all safety checks and return a :class:`~hcp.messages.SafetyResponsePayload`.

        Checks performed:

        1. **Permission audit** – every requested permission must appear in
           :attr:`CapabilityManifest.allowed_permissions`.
        2. **Environment audit** – every ``required_env_var`` in the request
           must be set in the process environment.

        Parameters
        ----------
        check:
            The incoming safety-check payload to validate.

        Returns
        -------
        SafetyResponsePayload
            Contains ``approved=True`` only when both audits pass.
        """
        reasons: list[str] = []

        # 1. Permission check
        disallowed = [
            p for p in check.required_permissions
            if p not in self._manifest.allowed_permissions
        ]
        if disallowed:
            reasons.append(
                f"Permissions not allowed by manifest: {disallowed}"
            )

        # 2. Environment check
        missing_env = [
            v for v in check.required_env_vars
            if not os.environ.get(v)
        ]
        if missing_env:
            reasons.append(
                f"Missing required environment variables: {missing_env}"
            )

        approved = not reasons
        approved_permissions = (
            [p for p in check.required_permissions if p in self._manifest.allowed_permissions]
            if approved
            else []
        )

        return SafetyResponsePayload(
            approved=approved,
            reason="; ".join(reasons) if reasons else "All checks passed",
            approved_permissions=approved_permissions,
            environment_valid=not missing_env,
            missing_env_vars=missing_env,
        )

    def validate_or_raise(self, check: SafetyCheckPayload) -> SafetyResponsePayload:
        """Like :meth:`validate` but raises :class:`~hcp.exceptions.SafetyCheckError`
        when the check does not pass."""
        response = self.validate(check)
        if not response.approved:
            raise SafetyCheckError(response.reason)
        return response
