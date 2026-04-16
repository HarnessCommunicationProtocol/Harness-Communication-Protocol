# HCP Discussion Log

## Session 1: Protocol Foundation

Date: 2025-04-16

### Participants
- Project initiator
- Claude (protocol design collaborator)

---

## Discussion Summary

### 1. Protocol Positioning

**Established**: HCP is a protocol for **Harness-to-Harness communication**. A harness is a superset of capability — it wraps an LLM, tools, and execution environments with autonomous reasoning ability.

**Key insight**: When a harness is exposed as a remote service, it appears to the calling harness as a **skill**. Unlike passive tools, the callee harness receives an intent and autonomously decides the execution strategy.

### 2. Relationship with MCP

**Established**: HCP and MCP are complementary, not competing.

- **MCP** operates *within* a harness — it's the protocol the harness uses internally to invoke tools, access resources, and interact with servers.
- **HCP** operates *between* harnesses — it's the protocol for task delegation, safety validation, and result exchange.
- The callee harness is a known, well-defined capability set. It does not need MCP-style `list_tools` discovery. The caller knows what the callee can do via Capability Declaration.

### 3. Communication Model

**Established**: Strictly **unidirectional** (Caller → Callee).

- Bidirectional communication was explicitly rejected because it would make the protocol too complex.
- Simplicity is prioritized for ecosystem adoption.
- The callee does not call back into the caller during execution.

### 4. Task Granularity

**Established**: The core protocol handles a **single granularity** — submit a task with intent, receive a result.

- Different granularity levels (sub-tasks, step-by-step control, etc.) are deferred to **extensions**.
- The main protocol stays simple.

### 5. Safety as Core Layer

**Established**: The Safety & Contract Layer (L3) is a **mandatory core layer**, not an optional extension.

- Critical for container and sandbox execution security.
- Essential for scientific scenarios involving physical devices and hazardous materials.
- Every task submission must pass through L3 before execution begins.

### 6. Protocol Architecture

**Established**: A four-layer protocol stack.

| Layer | Name | Responsibility |
|-------|------|----------------|
| L4 | Task Layer | Intent, inputs, constraints, results |
| L3 | Safety & Contract Layer | Risk assessment, permission, session token |
| L2 | Session & Lifecycle Layer | State machine, events, checkpoint |
| L1 | Transport & Encoding Layer | Message envelope, AMQP topology, channels |

### 7. Clarification on Meta-Harness Interface (Option C)

**Discussed and excluded**: Anthropic's Managed Agents pattern defines interfaces for the *internal structure* of a harness system (session, brain, sandbox components). HCP deliberately does not prescribe harness internals. Each harness's internal architecture is its own concern.

### 8. Transport Protocol: AMQP

**Established**: L1 standardizes on **AMQP 0-9-1** as the single transport protocol.

- **Rationale**: If transport is left open (Redis, WebSocket, HTTP SSE, AMQP, etc.), every callee harness must implement multiple transport adapters, fragmenting the ecosystem. Fixing the transport layer ensures any caller can communicate with any callee through a shared AMQP broker with a single implementation.
- **Why AMQP**: Mature standard, exchange/queue routing maps naturally to HCP's command + event channels, durable delivery, manual ACK, broad client library support.
- **Topology**: `hcp.commands` (direct exchange) for commands, `hcp.events` (topic exchange) for events. Routing keys encode callee_id, caller_id, session_id, and message type.
- **Previous plan discarded**: The `spec/bindings/` directory for multiple transport binding specs is no longer needed.

### 9. Stream Continuity via AMQP Message States

**Established**: Caller crash/reconnection recovery is handled entirely through standard AMQP message state mechanisms. No custom replay protocol is needed.

- **Core mechanism**: Manual ACK (`basic.ack`) mode. The caller only ACKs an event after fully processing it. If the caller crashes before ACKing, the broker automatically requeues unacknowledged messages (UNACKED → READY). On reconnection, the caller resumes from exactly where it left off.
- **Three AMQP message states leveraged**: READY (in queue) → UNACKED (delivered, awaiting ACK) → CONSUMED (ACKed) or REQUEUED (consumer disconnected).
- **Deduplication**: Handled at L2 via per-session `sequence` numbers. The caller tracks `last_processed_sequence` per session, skipping events with `sequence <= last_processed_sequence` on redelivery.
- **Prefetch tuning**: `basic.qos(prefetch_count)` controls the trade-off between throughput and recovery granularity (fewer prefetch = fewer events to reprocess on crash).
- **Callee independence**: The callee is completely decoupled from the caller's connection state — it publishes events regardless of whether the caller is connected.
- **L1 + L2 collaboration**: L1 ensures messages are never lost (AMQP durable + manual ACK + requeue). L2 ensures events are never processed twice (sequence dedup) and always in order. Together they provide exactly-once semantics at the application level.

---

## Pending Questions

### P1: Risk Classification Details (R1–R5)
The current R1–R5 risk levels are adapted from S-MCP's scientific context. Need to validate whether these five levels are appropriate for general-purpose scenarios, or if the definitions need adjustment.

**Specific questions:**
- Is R5 "safety-of-life implications" too narrow? Should it cover broader critical-infrastructure scenarios?
- Should risk levels be extensible by domain, or fixed in the core spec?

### P2: Data Classification Details (T1–T4)
Same question as P1 — the T1–T4 data classification was designed with scientific data in mind. Need to evaluate fit for general use cases (enterprise data, personal data, etc.).

**Specific questions:**
- How does T1–T4 relate to existing data classification standards (e.g., GDPR categories, SOC 2)?
- Should HCP define its own classification or reference external standards?

### P3: Human Approval Flow
L3 defines `requires_human_approval` as a flag, but the protocol does not yet specify how human approval integrates into the flow.

**Questions:**
- Is human approval async (task enters a queue, approval arrives later)?
- How does the caller know the task is waiting for human approval?
- Should there be a `PENDING_APPROVAL` session state?
- Is the approval mechanism out of scope for HCP (implementation-specific)?

### P4: Capability Discovery
The current design assumes the caller already knows the callee's Capability Declaration. The protocol does not define how capabilities are discovered.

**Questions:**
- Should HCP define a discovery mechanism (registry, broadcast, etc.)?
- Or is discovery explicitly out of scope, left to external systems?
- If out of scope, should the spec recommend a standard format for capability registries?

### P5: Artifact Retrieval
Artifacts in `task_completed` are referenced by URI (`hcp://session-abc/artifacts/...`) but the protocol does not define how these URIs are resolved.

**Questions:**
- Should there be an artifact retrieval sub-protocol?
- Or is artifact access implementation-specific?
- What about large artifacts (GB-scale datasets)?

### P6: Abort vs. Pause Semantics
The current spec has both PAUSED and ABORTING states. Need to clarify the caller's role:

**Questions:**
- Can the caller request a pause, or only the callee can pause?
- Is pause/resume exposed as a protocol command (like abort), or purely an internal callee behavior?
- Should the core spec simplify to only abort, deferring pause to extensions?

### P7: Session Token Format
The spec says session token format is implementation-specific. Need to consider:

**Questions:**
- Should HCP recommend (not require) a specific format like JWT for interoperability?
- What claims should a recommended token format carry?

### P8: Error Recovery and Retry
When a task fails, the caller may want to retry with adjusted parameters or resume from a checkpoint.

**Questions:**
- Should `task_submit` support a `resume_from_checkpoint` field?
- Is retry a new task submission or a protocol-level mechanism?
- How does the callee communicate "this error is retryable"?

### P9: Extension Mechanism
The spec mentions extensions (e.g., task granularity) but doesn't define how extensions work.

**Questions:**
- How are extensions negotiated between caller and callee?
- Are extensions declared in the Capability Declaration?
- What is the extension naming convention and versioning?

---

## Next Steps

1. Review and refine the current spec based on feedback
2. Prioritize pending questions for next discussion session
3. Create example scenarios beyond scientific experiments (e.g., code review, deployment, data pipeline)
4. Consider reference implementation strategy
