---
layout: default
title: Architecture
parent: English
nav_order: 2
---

[English](architecture) | [中文](zh/architecture)
{: .text-right }

# HCP Protocol Architecture

## Layered Architecture

```
┌─────────────────────────────────────────────────────┐
│  L4: Task Layer                                     │
│  Task submission, intent, constraints, results      │
├─────────────────────────────────────────────────────┤
│  L3: Safety & Contract Layer                        │
│  Capability declaration, risk assessment,           │
│  permission audit, session token issuance           │
├─────────────────────────────────────────────────────┤
│  L2: Session & Lifecycle Layer                      │
│  Session state machine, event stream,               │
│  checkpoint, interruption/recovery                  │
├─────────────────────────────────────────────────────┤
│  L1: Transport & Encoding Layer                     │
│  Message envelope, AMQP topology, channel spec      │
└─────────────────────────────────────────────────────┘
```

## Layer Responsibilities

### L1: Transport & Encoding Layer

The foundation layer. Defines:

- **Message Envelope**: Standard wrapper for all HCP messages (version, message ID, timestamp, session ID, message type, payload)
- **Channel Specification**: Two logical channels — a **command channel** (caller → callee) and an **event channel** (callee → caller), mapped to AMQP exchanges and queues
- **AMQP Topology**: Standard exchange/queue/routing-key conventions that all implementations follow

L1 is concerned with *how messages are encoded and delivered*, not with their semantic meaning. HCP standardizes on AMQP 0-9-1 as its transport protocol.

See [L1-transport-encoding.md](./L1-transport-encoding.md)

### L2: Session & Lifecycle Layer

The state management layer. Defines:

- **Session State Machine**: The lifecycle states of a task session (PENDING → RUNNING → COMPLETED/FAILED/ABORTED) and valid transitions
- **Event Stream Protocol**: Standard event types for progress reporting, intermediate results, warnings, checkpoints, and errors
- **Checkpoint & Recovery**: How sessions can be paused, checkpointed, and resumed after interruption
- **Session Timeout & Cleanup**: Idle detection and resource reclamation

L2 is concerned with *session lifecycle and execution visibility*, not with what the task is or whether it's safe to execute.

See [L2-session-lifecycle.md](./L2-session-lifecycle.md)

### L3: Safety & Contract Layer

The security gate layer. Defines:

- **Capability Declaration**: How a callee harness describes its capabilities, input/output contracts, and safety characteristics
- **Risk Assessment**: Risk level classification (R1–R5) based on task inputs and capability characteristics
- **Permission Audit**: Verifying the caller's authorization to invoke the requested capability
- **Data Classification**: Sensitivity tagging (T1–T4) for data involved in the task
- **Safety Envelope**: Physical and logical boundary constraints that execution must not exceed
- **Session Token**: Cryptographic token issued upon approval, carried through L2 and L1, constraining execution scope

L3 is the **mandatory gate** between task submission and execution. No task proceeds without L3 approval.

See [L3-safety-contract.md](./L3-safety-contract.md)

### L4: Task Layer

The application layer. Defines:

- **Task Submission**: How the caller describes intent, provides inputs, declares constraints, and specifies expected output format
- **Task Result**: How the callee returns final results, artifacts, and execution summaries
- **Task Rejection**: How the callee communicates why a task cannot be accepted
- **Error Reporting**: How execution failures are communicated with actionable detail

L4 is concerned with *what to do and what happened*, not with how it's delivered or whether it's safe.

See [L4-task.md](./L4-task.md)

## End-to-End Flow

A complete HCP interaction follows this sequence:

```
Caller Harness                                         Callee Harness
     │                                                       │
     │  ① TaskSubmit                                         │
     │  L4: intent + inputs + constraints                    │
     │  ─────────── L4 → L1 encoding ─────────────────────► │
     │                                                       │
     │                                 ② L3: Safety Check    │
     │                                 - Permission audit    │
     │                                 - Risk assessment     │
     │                                 - Safety envelope     │
     │                                 - Data classification │
     │                                                       │
     │  ③ TaskAccepted (with SessionToken + risk level)      │
     │     or TaskRejected (with reason)                     │
     │  ◄─────────────────────────────────────────────────── │
     │                                                       │
     │                                 ④ L2: Session created │
     │                                    State → RUNNING    │
     │                                                       │
     │  ⑤ Event Stream                                       │
     │  progress / intermediate_result / checkpoint / ...    │
     │  ◄─────────────────────────────────────────────────── │
     │  ◄─────────────────────────────────────────────────── │
     │  ◄─────────────────────────────────────────────────── │
     │                                                       │
     │  ⑥ Caller may send Abort (optional)                   │
     │  ─────────────────────────────────────────────────►   │
     │                                                       │
     │  ⑦ TaskCompleted / TaskFailed                         │
     │  final result + artifacts + execution summary         │
     │  ◄─────────────────────────────────────────────────── │
     │                                                       │
     │                                 ⑧ Session closed      │
     │                                    State → terminal   │
```

## Layer Interaction Rules

1. **Downward encapsulation**: Each layer encapsulates the layer above when sending. L4 task data is wrapped by L3 safety metadata, managed by L2 session context, and encoded by L1 transport framing.

2. **Upward delivery**: Each layer strips its own concerns when receiving. L1 decodes the transport frame, L2 routes to the correct session, L3 validates the session token, and L4 processes the task content.

3. **L3 is a gate, not a pipe**: Unlike L1 and L2 which always pass data through, L3 can **reject** a task entirely. Data only flows to L2 and L1 for execution if L3 approves.

4. **Event bypass**: During execution, events from L2 flow directly through L1 back to the caller without L3 re-validation. The SessionToken issued at submission time authorizes the entire session scope. L3 constraints are enforced locally by the callee during execution.

## Multiple Callee Harnesses

A caller harness may interact with multiple callee harnesses simultaneously, each through independent HCP sessions:

```
                         ┌─── HCP Session A ───► Callee Harness A
                         │                       (Data Analysis)
Caller Harness ──────────┤
                         │
                         └─── HCP Session B ───► Callee Harness B
                                                 (Lab Instrument Control)
```

Each session is independent. The caller harness is responsible for coordinating results across sessions — this coordination logic is internal to the caller and outside the scope of HCP.
