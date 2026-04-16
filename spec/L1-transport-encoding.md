---
layout: default
title: "L1: Transport & Encoding"
parent: English
nav_order: 6
---

[English](L1-transport-encoding) | [中文](zh/L1-transport-encoding)
{: .text-right }

# L1: Transport & Encoding Layer

## Purpose

L1 defines how HCP messages are encoded, framed, and delivered over the network. HCP standardizes on **AMQP 0-9-1** as its transport protocol, avoiding fragmentation in the ecosystem — every HCP-compliant harness speaks the same wire protocol.

## Why AMQP

HCP requires reliable, asynchronous, bidirectional message passing with durable delivery. AMQP provides all of these natively:

- **Standardized**: AMQP 0-9-1 is a mature wire-level protocol with broad implementation support (RabbitMQ, LavinMQ, Apache Qpid, etc.)
- **Exchange + Queue routing**: Naturally maps to HCP's command and event channels without custom routing logic
- **Durable delivery**: Messages can be persisted to disk, surviving broker restarts
- **Acknowledgment**: Consumer-side ACK ensures at-least-once delivery
- **Widely supported**: Client libraries exist for virtually every language and platform

By fixing the transport layer, callee harnesses need only one protocol implementation, and any caller can communicate with any callee through a shared AMQP broker.

## Message Envelope

Every HCP message is wrapped in a standard envelope, carried as the AMQP message body:

```json
{
  "hcp_version": "1.0",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-01-15T08:30:00.000Z",
  "session_id": null,
  "type": "task_submit",
  "payload": { }
}
```

### Envelope Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `hcp_version` | string | Yes | Protocol version. Format: `MAJOR.MINOR` |
| `message_id` | string (UUID v4) | Yes | Unique identifier for this message |
| `timestamp` | string (ISO 8601) | Yes | When the message was created, UTC |
| `session_id` | string (UUID v4) \| null | Conditional | Session identifier. `null` only in the initial `task_submit` message. All subsequent messages MUST include a valid session ID |
| `type` | string (enum) | Yes | Message type. See [Message Types](#message-types) |
| `payload` | object | Yes | Layer-specific content. Structure depends on `type` |

### AMQP Message Properties Mapping

HCP envelope fields map to AMQP message properties for broker-level routing and deduplication:

| AMQP Property | HCP Source | Purpose |
|---------------|-----------|---------|
| `message_id` | `message_id` | Broker-level deduplication |
| `timestamp` | `timestamp` | Message creation time |
| `correlation_id` | `session_id` | Session correlation for routing |
| `content_type` | `"application/json"` | Always JSON |
| `content_encoding` | `"utf-8"` | Always UTF-8 |
| `delivery_mode` | `2` (persistent) | Durable delivery |
| `type` | `type` | Message type for consumer filtering |

### Message Types

Messages are categorized by direction:

**Caller → Callee (Command Channel)**

| Type | Description | Session Required |
|------|-------------|-----------------|
| `task_submit` | Submit a new task | No (session created by callee) |
| `abort` | Request task abortion | Yes |

**Callee → Caller (Event Channel)**

| Type | Description |
|------|-------------|
| `task_accepted` | Task passed safety check, session created |
| `task_rejected` | Task failed safety check |
| `event` | Session lifecycle event (progress, checkpoint, etc.) |
| `task_completed` | Task finished successfully |
| `task_failed` | Task terminated due to error |

## AMQP Topology

HCP defines a standard AMQP topology that all implementations MUST follow.

### Overview

```
Caller Harness                    AMQP Broker                     Callee Harness
                         ┌──────────────────────────┐
     ┌───── publish ────►│  hcp.commands (exchange)  │──── consume ────►┐
     │                   │  type: direct             │                  │
     │                   ├──────────────────────────┤                  │
     │                   │                          │                  │
     │                   │  Queue:                  │                  │
     │                   │  hcp.cmd.{callee_id}     │                  │
     │                   ├──────────────────────────┤                  │
     │                   │                          │                  │
     │◄──── consume ─────│  hcp.events (exchange)   │◄── publish ──────┘
     │                   │  type: topic             │
     │                   │                          │
     │                   │  Queue:                  │
     │                   │  hcp.evt.{caller_id}     │
     │                   │  binding: {caller_id}.#  │
     └                   └──────────────────────────┘
```

### Exchanges

| Exchange | Type | Durable | Description |
|----------|------|---------|-------------|
| `hcp.commands` | `direct` | Yes | Carries command messages from callers to callees |
| `hcp.events` | `topic` | Yes | Carries event messages from callees to callers |

### Queues

| Queue | Bound To | Routing/Binding Key | Durable | Description |
|-------|----------|-------------------|---------|-------------|
| `hcp.cmd.{callee_id}` | `hcp.commands` | `{callee_id}` | Yes | Command queue for a specific callee harness |
| `hcp.evt.{caller_id}` | `hcp.events` | `{caller_id}.#` | Yes | Event queue for a specific caller harness |

### Routing Keys

**Command Channel** (`hcp.commands` exchange, direct routing):

```
Routing key: {callee_id}
```

The caller publishes to `hcp.commands` with routing key set to the target callee's ID. The broker routes to the callee's command queue.

**Event Channel** (`hcp.events` exchange, topic routing):

```
Routing key: {caller_id}.{session_id}.{message_type}
```

The callee publishes to `hcp.events` with a routing key that includes the caller ID, session ID, and message type. This enables:

- **Per-caller routing**: Each caller's queue binds with `{caller_id}.#` to receive only its own events
- **Per-session filtering**: Consumers can optionally bind with `{caller_id}.{session_id}.#` for session-specific queues
- **Per-type filtering**: Consumers can bind with `{caller_id}.*.task_completed` to receive only completion events

### Topology Example

```
Caller "alpha" submitting to Callee "lab-cvd":

Command:
  Exchange: hcp.commands
  Routing key: lab-cvd
  Queue: hcp.cmd.lab-cvd

Events:
  Exchange: hcp.events
  Routing key: alpha.session-xyz.event
  Queue: hcp.evt.alpha (bound with "alpha.#")
```

## Delivery Guarantees

### Command Channel

- **Delivery**: At-least-once. The caller MUST publish with `delivery_mode: 2` (persistent) and the callee MUST use manual ACK (`basic.ack`).
- **Ordering**: AMQP guarantees per-queue FIFO ordering. Since all commands to a callee go to a single queue, ordering is preserved.
- **Retry**: If the caller does not receive a `task_accepted` or `task_rejected` within a configurable timeout, it SHOULD republish the `task_submit` with the same `message_id`. The callee MUST deduplicate on `message_id`.

### Event Channel

- **Delivery**: At-least-once with ordering. The callee MUST publish with `delivery_mode: 2` and the caller MUST use manual ACK.
- **Durability**: Event queues are durable. Events published while the caller is disconnected are retained in the queue until the caller reconnects and consumes them.
- **Idempotency**: Each event carries a unique `message_id`. Consumers SHOULD deduplicate on `message_id`.
- **Ordering**: Events for a session are published sequentially by the callee. AMQP per-queue FIFO guarantees they arrive in order.

## Stream Continuity

A core requirement of HCP is that the event stream between callee and caller remains **stable and lossless** even when the caller crashes, restarts, or experiences network interruption. HCP achieves this entirely through standard AMQP message state mechanisms — no custom replay protocol is needed.

### The Problem

In a long-running task (potentially hours or days), the caller may:
1. Crash and restart mid-stream
2. Lose network connectivity temporarily
3. Be intentionally restarted (e.g., deployment, scaling)

In all cases, the event stream must resume from exactly where it left off — no lost events, no gaps, no duplicate processing.

### The Mechanism: AMQP ACK-Based Stream Continuity

AMQP provides three message states that HCP leverages:

```
                        ┌──────────────┐
                        │   READY      │  Message in queue, not yet delivered
                        └──────┬───────┘
                               │ broker delivers to consumer
                               ▼
                        ┌──────────────┐
                        │ UNACKED      │  Delivered but not acknowledged
                        └──┬───────┬───┘
                           │       │
                  basic.ack│       │ consumer disconnects
                           │       │ (crash / network loss)
                           ▼       ▼
                   ┌──────────┐  ┌──────────────┐
                   │ CONSUMED │  │ REQUEUED     │  Returns to READY,
                   │ (done)   │  │ (→ READY)    │  redelivered to next consumer
                   └──────────┘  └──────────────┘
```

**The key guarantee**: Messages in UNACKED state are **never lost**. If the consumer disconnects before sending `basic.ack`, the broker automatically requeues the message, making it available for redelivery.

### Caller Consumer Configuration

Callers MUST configure their event channel consumer as follows:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `no_ack` | `false` | **Manual ACK mode.** The caller explicitly acknowledges each event after processing. This is the foundation of stream continuity. |
| `prefetch_count` | 1–100 (recommended: 10) | Controls how many unACKed messages the broker delivers ahead. Higher values improve throughput; lower values reduce redelivery on crash. |
| `exclusive` | `false` | Allows the consumer to reconnect to the same queue after restart. |

### ACK Strategy

The caller MUST follow this ACK strategy:

```
Caller receives event from broker
       │
       ▼
Process the event
(update local state, render to UI, persist to store, etc.)
       │
       ▼
Processing succeeded?
├── Yes → basic.ack(delivery_tag)
│         Message removed from queue permanently.
│         Broker advances delivery cursor.
│
└── No (processing error) → basic.nack(delivery_tag, requeue=true)
          Message returns to READY state.
          Broker will redeliver.
```

**Critical rule**: The caller MUST NOT acknowledge an event until it has **fully processed** it (persisted, rendered, forwarded, etc.). Acknowledging before processing risks data loss on crash.

### Caller Crash and Recovery

```
Timeline:

Caller running normally
│
│  event seq=1  ──► process ──► basic.ack     ✓ consumed
│  event seq=2  ──► process ──► basic.ack     ✓ consumed
│  event seq=3  ──► process ──► basic.ack     ✓ consumed
│  event seq=4  ──► delivered (UNACKED)
│  event seq=5  ──► delivered (UNACKED)        prefetch window
│
│  ╳ CALLER CRASHES
│
│  Broker detects TCP disconnect
│  │
│  ├─ event seq=4 ──► UNACKED → REQUEUED → READY
│  └─ event seq=5 ──► UNACKED → REQUEUED → READY
│
│  Meanwhile, callee continues execution:
│  event seq=6 ──► published → READY (queued behind seq=4,5)
│  event seq=7 ──► published → READY
│
│  Caller restarts
│  │
│  ├─ Connect to broker
│  ├─ Declare consumer on hcp.evt.{caller_id}
│  └─ Broker delivers from queue head:
│
│  event seq=4  ──► redelivered (redelivered=true)
│  event seq=5  ──► redelivered (redelivered=true)
│  event seq=6  ──► first delivery
│  event seq=7  ──► first delivery
│  ... stream continues seamlessly
```

The caller's event stream resumes from exactly where it left off. No events are lost. No custom replay protocol is needed.

### Handling Redelivered Messages

When a message is redelivered, AMQP sets the `redelivered` flag to `true` in the delivery metadata. Callers SHOULD handle redeliveries:

1. **Idempotent processing** (recommended): Design event processing to be idempotent. Processing the same event twice produces the same result. This is the simplest approach.

2. **Deduplication by message_id**: Maintain a set of recently processed `message_id` values. On redelivery, check if the `message_id` has already been processed and skip if so.

3. **Deduplication by L2 sequence**: Use the L2 event `sequence` number. Track the last processed sequence per session. On redelivery, skip events with `sequence <= last_processed_sequence`.

Approaches can be combined. The L2 `sequence` number (see [L2-session-lifecycle.md](./L2-session-lifecycle.md)) provides a definitive ordering that survives redelivery and deduplication.

### Prefetch Tuning

The `prefetch_count` (`basic.qos`) controls the trade-off between throughput and recovery granularity:

| Prefetch | Throughput | Recovery cost | Use case |
|----------|-----------|---------------|----------|
| 1 | Lowest | Minimal — at most 1 event reprocessed | Critical tasks (R4–R5), UI-driven consumers |
| 10 | Good | Up to 10 events reprocessed | General-purpose default |
| 50–100 | High | Up to N events reprocessed | High-throughput batch consumers |

Recommendation: Start with `prefetch_count=10`. Increase for batch/background consumers; decrease to `1` for latency-sensitive or safety-critical scenarios.

### Network Partition (Temporary Disconnection)

```
Caller ──── connected ────╳ network loss ╳──── reconnects ────►

Broker perspective:
│ Detects heartbeat timeout (AMQP heartbeat, e.g., 60s)
│ Closes connection
│ Requeues all UNACKED messages for this consumer
│ Queues new events published during partition
│
│ Caller reconnects:
│ Requeued + newly queued events delivered in FIFO order
```

**AMQP heartbeat** enables prompt detection of dead connections. HCP implementations SHOULD configure heartbeats:

| Parameter | Recommended Value | Rationale |
|-----------|------------------|-----------|
| `heartbeat` | 30–60 seconds | Detects dead connections within 2× heartbeat interval |

### Callee Independence

The callee's execution is **completely decoupled** from the caller's connection state:

- The callee publishes events to the `hcp.events` exchange. The broker queues them in `hcp.evt.{caller_id}`.
- Whether the caller is connected or not, the callee's publish succeeds as long as the broker is reachable.
- The callee has no knowledge of whether the caller has consumed, acknowledged, or crashed.
- This decoupling is fundamental: the callee never blocks or pauses because of the caller.

### Multi-Session Stream Interleaving

A single caller event queue (`hcp.evt.{caller_id}`) may carry events from multiple concurrent sessions. The caller demultiplexes by `session_id`:

```
Queue: hcp.evt.alpha
│
├─ event (session=A, seq=10, type=progress)
├─ event (session=B, seq=3, type=tool_start)
├─ event (session=A, seq=11, type=progress)
├─ event (session=B, seq=4, type=tool_end)
├─ event (session=A, seq=12, type=completed)
│  ...

Caller demultiplexes:
  Session A handler: seq=10, 11, 12 → per-session ordered processing
  Session B handler: seq=3, 4       → per-session ordered processing
```

Each session's `sequence` numbers are independent. The caller tracks the last processed sequence **per session** for deduplication.

### Broker Failure

If the AMQP broker itself fails:

- **Durable queues and persistent messages survive broker restart.** On recovery, all READY and UNACKED-requeued messages are available.
- Harnesses SHOULD implement connection retry with **exponential backoff** (e.g., 1s, 2s, 4s, 8s... capped at 60s).
- For high availability, the broker SHOULD be deployed with **quorum queues** (RabbitMQ 3.8+) which replicate queue state across multiple nodes and tolerate minority node failures.

### Summary: Why No Custom Replay Protocol

Traditional event streaming systems often require custom replay mechanisms (e.g., consumer offset tracking, `Last-Event-ID`, cursor-based pagination). HCP avoids all of this by leveraging AMQP's built-in message lifecycle:

| Concern | HCP Solution | AMQP Mechanism |
|---------|-------------|----------------|
| Event persistence | Messages survive disconnection | `delivery_mode: 2` (persistent) + durable queue |
| Resume from crash | Unprocessed events automatically redelivered | Manual ACK + requeue on disconnect |
| Duplicate detection | Skip already-processed events | `redelivered` flag + L2 `sequence` number |
| Flow control | Limit in-flight messages | `basic.qos` (prefetch_count) |
| Dead connection detection | Prompt cleanup of consumer state | AMQP heartbeat |
| Ordering guarantee | Events arrive in emission order | Per-queue FIFO |

This design ensures that from the caller's perspective, the event stream is a **continuous, lossless, ordered sequence** — regardless of crashes, network issues, or restarts.

## Encoding

- All message bodies MUST be encoded as **UTF-8 JSON**.
- The AMQP `content_type` property MUST be set to `"application/json"`.
- The AMQP `content_encoding` property MUST be set to `"utf-8"`.
- Binary data (files, images, large datasets) MUST be referenced by URI, not embedded inline.
- Timestamps MUST use ISO 8601 format in UTC (e.g., `2025-01-15T08:30:00.000Z`).
- Durations MUST use ISO 8601 duration format (e.g., `PT72H`, `PT2H15M`).

## Queue Management

### TTL and Cleanup

| Queue | Recommended TTL | Rationale |
|-------|----------------|-----------|
| `hcp.cmd.{callee_id}` | No TTL | Commands should be consumed as long as the callee exists |
| `hcp.evt.{caller_id}` | 24 hours (message TTL) | Events not consumed within 24h are likely stale |

- Callee command queues SHOULD persist as long as the callee harness is registered.
- Caller event queues MAY use per-message TTL (`x-message-ttl`) to discard stale events.
- Session-specific event queues (if used) SHOULD be auto-deleted when the session reaches a terminal state.

### Queue Size Limits

Implementations SHOULD configure `x-max-length` or `x-max-length-bytes` on event queues to prevent unbounded growth. When limits are reached, the oldest messages SHOULD be discarded (`overflow: drop-head`).

## Connection and Authentication

### Virtual Host

All HCP exchanges and queues SHOULD be created within a dedicated AMQP virtual host (e.g., `/hcp`) to isolate HCP traffic from other applications sharing the same broker.

### Authentication

- Harnesses authenticate to the AMQP broker using standard AMQP SASL mechanisms.
- Each harness SHOULD have a unique set of credentials.
- Access control (which harness can publish/consume which queues) SHOULD be configured at the broker level via AMQP permissions.

HCP does not define its own authentication layer — broker-level authentication and authorization are sufficient for transport security. Application-level identity (caller_id) is validated by L3.

### TLS

All AMQP connections SHOULD use TLS (`amqps://`). Unencrypted connections (`amqp://`) SHOULD only be used in trusted network environments (e.g., localhost development).

## Topology Initialization

When a harness starts:

1. Connect to the AMQP broker.
2. Declare the `hcp.commands` and `hcp.events` exchanges (idempotent — `passive: false` with matching parameters).
3. **If callee**: Declare and bind `hcp.cmd.{callee_id}` queue. Start consuming.
4. **If caller**: Declare and bind `hcp.evt.{caller_id}` queue. Start consuming.

Exchange and queue declarations are **idempotent** — multiple harnesses declaring the same exchange with the same parameters is safe.
