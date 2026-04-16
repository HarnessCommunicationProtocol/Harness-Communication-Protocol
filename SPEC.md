# Harness Communication Protocol (HCP) Specification

**Version:** 1.0  
**Status:** Draft  
**License:** Apache 2.0

---

## Table of Contents

1. [Overview](#overview)
2. [Goals](#goals)
3. [Concepts](#concepts)
4. [Transport Model](#transport-model)
5. [Message Envelope](#message-envelope)
6. [Message Types](#message-types)
7. [Message Flow](#message-flow)
8. [Security Model](#security-model)
9. [Capability Manifest](#capability-manifest)
10. [Safety Validation](#safety-validation)
11. [Error Handling](#error-handling)
12. [Versioning](#versioning)
13. [Extension Points](#extension-points)

---

## Overview

The **Harness Communication Protocol (HCP)** is an open, message-queue-based
protocol that enables secure, standardised communication between AI agents and
executable capabilities (harnesses). It provides:

* A typed, versioned **message envelope** for all protocol traffic.
* A **pre-invocation safety validation** step so that capabilities can
  accept or reject requests before any code runs.
* A clear **handshake** flow for capability discovery and version negotiation.
* Asynchronous **event streaming** from capabilities back to agents.
* Optional **HMAC-SHA256 message signing** for endpoint authentication and
  integrity protection.
* A **pluggable transport layer** that defaults to an in-process async queue
  and can be backed by any external broker (Redis, RabbitMQ, Kafka, etc.).

---

## Goals

| # | Goal |
|---|------|
| G1 | Enable AI agents to discover and invoke tool capabilities in a uniform way. |
| G2 | Validate execution safety and environment readiness *before* invocation. |
| G3 | Provide a secure channel with optional message authentication. |
| G4 | Support asynchronous, event-driven task execution. |
| G5 | Be transport-agnostic; work over any message queue. |
| G6 | Be language-agnostic; the spec is the contract. |

---

## Concepts

### Agent

An AI entity (e.g. a language-model orchestrator, autonomous bot, or
workflow engine) that **dispatches tasks** to capabilities and **consumes
results and events**.  Agents are identified by a unique `agent_id` string.

### Capability (Harness)

An executable unit that **implements one or more named tools**.  A capability
is identified by a unique `capability_id`.  It:

1. Declares its security profile via a **Capability Manifest**.
2. Responds to **Safety Check** requests before executing tasks.
3. Executes **Tasks** and publishes **Results**.
4. May emit **Events** during execution (progress, logs, warnings).

### Message Queue

The shared transport channel over which all HCP messages flow.  The queue is
topic-routed: each message is addressed to a specific `recipient.id`, and only
subscribers registered for that ID (or the wildcard `"*"`) receive it.

---

## Transport Model

HCP is **transport-agnostic**.  The reference implementation ships with an
in-process async queue (`HCPQueue`) suitable for single-process deployments.
For distributed deployments, implement the `QueueAdapter` abstract interface:

```python
class QueueAdapter(ABC):
    async def publish(self, message: Message) -> None: ...
    async def consume(self, recipient_id: str, handler: MessageHandler) -> None: ...
```

Routing semantics:

* A message addressed to `recipient_id = "cap-1"` is delivered to all
  subscribers registered for `"cap-1"`.
* A subscriber registered for `"*"` receives a copy of every message
  (monitoring / logging use case).
* Subscriptions are not durable by default; durability is a broker concern.

---

## Message Envelope

Every HCP message is wrapped in a top-level JSON envelope:

```json
{
  "id":             "<uuid4>",
  "type":           "<MessageType>",
  "version":        "1.0",
  "timestamp":      "<ISO 8601 UTC>",
  "correlation_id": "<uuid4 | empty>",
  "signature":      "<hmac-sha256 hex | empty>",
  "sender": {
    "id":   "<endpoint-id>",
    "type": "AGENT | CAPABILITY"
  },
  "recipient": {
    "id":   "<endpoint-id>",
    "type": "AGENT | CAPABILITY"
  },
  "payload": { ... },
  "metadata": { ... }
}
```

### Field Descriptions

| Field | Required | Description |
|-------|----------|-------------|
| `id` | ✅ | UUID4 uniquely identifying this message. |
| `type` | ✅ | One of the defined `MessageType` values. |
| `version` | ✅ | Protocol version string (currently `"1.0"`). |
| `timestamp` | ✅ | UTC creation time in ISO 8601 format. |
| `correlation_id` | ❌ | ID of the message this is a response to. |
| `signature` | ❌ | HMAC-SHA256 hex digest (see [Security Model](#security-model)). |
| `sender` | ✅ | Originating endpoint `{id, type}`. |
| `recipient` | ✅ | Destination endpoint `{id, type}`. |
| `payload` | ✅ | Type-specific payload object (see below). |
| `metadata` | ❌ | Arbitrary key/value extension data. |

---

## Message Types

### `HANDSHAKE`

Exchanged at connection time to negotiate capabilities and protocol versions.

**Payload:**
```json
{
  "capabilities":       ["<capability-name>", ...],
  "protocol_versions":  ["1.0"],
  "metadata":           {}
}
```

Agents send a HANDSHAKE with an empty `capabilities` list.  Capabilities
respond with their supported capability names.

---

### `SAFETY_CHECK`

Sent by an agent to request a pre-invocation safety assessment.  The
capability responds with a `SAFETY_RESPONSE`.

**Payload:**
```json
{
  "task_name":            "<string>",
  "required_permissions": ["<permission>", ...],
  "required_env_vars":    ["<env-var>", ...],
  "resource_access":      ["<resource>", ...],
  "sandbox_config":       {},
  "metadata":             {}
}
```

`required_permissions` uses a dot-notation namespace (examples: `"fs:read"`,
`"net:egress"`, `"math"`).

---

### `SAFETY_RESPONSE`

Returned by a capability in response to a `SAFETY_CHECK`.

**Payload:**
```json
{
  "approved":             true | false,
  "reason":               "<string>",
  "approved_permissions": ["<permission>", ...],
  "environment_valid":    true | false,
  "missing_env_vars":     ["<env-var>", ...]
}
```

When `approved` is `false`, the agent **must not** send a `TASK` for this
invocation.  The `reason` field provides a human-readable explanation.

---

### `TASK`

Dispatches an execution request from an agent to a capability.

**Payload:**
```json
{
  "task_id":  "<uuid4>",
  "name":     "<tool-name>",
  "args":     { "<key>": "<value>", ... },
  "timeout":  30.0,
  "priority": 5,
  "metadata": {}
}
```

`priority` is an integer 0–9 where 9 is the highest priority.

---

### `EVENT`

Asynchronous notification emitted by a capability during task execution.
Multiple `EVENT` messages may be sent for a single `TASK`.

**Payload:**
```json
{
  "task_id":    "<uuid4>",
  "event_type": "<string>",
  "data":       {},
  "metadata":   {}
}
```

Common `event_type` values: `"progress"`, `"log"`, `"warning"`, `"status"`.

---

### `RESULT`

Terminal outcome of a task execution.  Exactly one `RESULT` is published
per `TASK`.

**Payload:**
```json
{
  "task_id":  "<uuid4>",
  "status":   "SUCCESS | FAILURE | TIMEOUT | REJECTED",
  "output":   "<any JSON-serialisable value>",
  "error":    "<string | empty>",
  "metadata": {}
}
```

| Status | Meaning |
|--------|---------|
| `SUCCESS` | Task completed successfully; `output` contains the return value. |
| `FAILURE` | Task raised an exception; `error` contains the message. |
| `TIMEOUT` | Task exceeded `TaskPayload.timeout`; `error` contains details. |
| `REJECTED` | Task was refused by a safety check inside the capability. |

---

### `ERROR`

Protocol-level error (not a task failure).  Examples: signature failure,
unknown message type, internal capability error unrelated to a task.

**Payload:**
```json
{
  "code":    "<string>",
  "message": "<string>",
  "details": {}
}
```

---

### `HEARTBEAT`

Periodic liveness signal.  Either side may send heartbeats.

**Payload:**
```json
{
  "sequence": 0,
  "metadata": {}
}
```

---

## Message Flow

### Happy Path

```
Agent                                   Capability
  |                                          |
  |-------- HANDSHAKE ---------------------->|
  |<------- HANDSHAKE (ack) -----------------|
  |                                          |
  |-------- SAFETY_CHECK ------------------->|
  |<------- SAFETY_RESPONSE (approved=true) -|
  |                                          |
  |-------- TASK --------------------------->|
  |<------- EVENT (progress, optional) ------|
  |<------- EVENT (log, optional) -----------|
  |<------- RESULT (SUCCESS) ---------------|
```

### Rejected Safety Check

```
Agent                                   Capability
  |                                          |
  |-------- SAFETY_CHECK ------------------->|
  |<------- SAFETY_RESPONSE (approved=false) |
  |  [Agent does NOT send TASK]              |
```

### Protocol Error

```
Agent                                   Capability
  |                                          |
  |-------- TASK (unsigned) ---------------->|
  |<------- ERROR (SIGNATURE_ERROR) ---------|
```

---

## Security Model

### HMAC-SHA256 Message Signing

When security is required, every message is signed with an HMAC-SHA256 digest:

1. The **sender** calls `sign_message(message, shared_secret)` before
   publishing.
2. The **recipient** calls `verify_message(message, shared_secret)` on
   arrival.  If verification fails, the message is rejected and an `ERROR`
   response is sent.

The digest is computed over the **canonical JSON** of all envelope fields
**except** `signature` itself, with dictionary keys sorted alphabetically.

The shared secret must be exchanged out-of-band (e.g. environment variable,
secrets manager, mTLS certificate).

### Threat Model

| Threat | Mitigation |
|--------|------------|
| Message tampering | HMAC-SHA256 signature |
| Replay attacks | Timestamp + `id` uniqueness (application-layer replay detection recommended) |
| Unauthorized invocation | Pre-invocation safety check + capability manifest |
| Environment misconfiguration | Safety validator checks required env vars before execution |
| Capability overreach | Manifest declares and enforces allowed permissions |

---

## Capability Manifest

Every capability declares its security profile in a `CapabilityManifest`:

```json
{
  "name":                 "<capability-name>",
  "allowed_permissions":  ["<permission>", ...],
  "required_env_vars":    ["<env-var>", ...],
  "resource_access":      ["<resource>", ...],
  "description":          "<string>",
  "metadata":             {}
}
```

The manifest is the **source of truth** for safety validation.  Requests that
ask for permissions not listed in `allowed_permissions` are automatically
rejected.

---

## Safety Validation

The `SafetyValidator` performs two checks against the `CapabilityManifest`:

1. **Permission Audit** – every permission in `SafetyCheckPayload.required_permissions`
   must appear in `CapabilityManifest.allowed_permissions`.
2. **Environment Audit** – every variable in `SafetyCheckPayload.required_env_vars`
   must be set in the process environment.

Both checks must pass for `approved = true`.

---

## Error Handling

### Task Errors

Task-level errors are communicated via `ResultPayload.status`:

* `FAILURE` – exception raised by the capability's `execute()` method.
* `TIMEOUT` – execution exceeded `TaskPayload.timeout`.
* `REJECTED` – a `SafetyCheckError` was raised inside `execute()`.

### Protocol Errors

Protocol-level errors (signature failures, unknown message types, internal
errors) are communicated via a dedicated `ERROR` message.

### Capability Resilience

A capability **must not** crash or stop processing due to a single task
failure.  The base `Capability` class catches all exceptions in `execute()`
and converts them to `RESULT` messages with `status=FAILURE`.

---

## Versioning

The protocol version is carried in every message envelope (`version` field).
Currently only `"1.0"` is defined.

Backward-incompatible changes increment the major version.  Additive changes
(new optional fields, new message types) increment the minor version.

Recipients **must** reject messages whose `version` they do not support and
respond with an `ERROR` message.

---

## Extension Points

| Extension Point | How to Use |
|-----------------|------------|
| **Custom transport** | Implement `QueueAdapter.publish` and `QueueAdapter.consume` |
| **Custom safety logic** | Override `SafetyValidator.validate` or add pre-check hooks |
| **Custom capability** | Subclass `Capability` and implement `execute` |
| **Metadata** | Use the `metadata` dict on any envelope or payload object |
| **New message types** | Add to `MessageType` enum and register in `_PAYLOAD_CLASSES` |
