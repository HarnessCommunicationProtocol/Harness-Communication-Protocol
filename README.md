**English** | [中文](README.zh.md)

# HCP: Harness Communication Protocol

An open protocol for secure communication between AI agent harnesses — enabling standardized task delegation, safety validation, session lifecycle management, and event-driven result exchange across autonomous agent systems.

## What is HCP?

HCP defines how one AI agent harness delegates work to another. Unlike tool-invocation protocols (e.g., MCP) that call passive functions, HCP communicates with **autonomous agents** — the callee harness receives an intent, independently decides how to execute it, and streams progress and results back to the caller.

A harness is the runtime that wraps an LLM with tools, execution environments, and an agent loop. When exposed as a remote service, a harness appears as a **skill** — a self-contained capability with autonomous reasoning ability.

## Protocol Stack

| Layer | Name | Responsibility |
|-------|------|----------------|
| **L4** | [Task Layer](spec/L4-task.md) | Intent description, constraints, result exchange |
| **L3** | [Safety & Contract Layer](spec/L3-safety-contract.md) | Risk assessment, permission audit, session token issuance |
| **L2** | [Session & Lifecycle Layer](spec/L2-session-lifecycle.md) | Session state machine, event streaming, checkpoint/recovery |
| **L1** | [Transport & Encoding Layer](spec/L1-transport-encoding.md) | Message envelope, AMQP topology, channel specification |

## Key Design Principles

- **Unidirectional**: Strict Caller → Callee model. No callbacks, no bidirectional complexity.
- **Safety as Core**: Every task passes through a mandatory safety gate (L3) before execution.
- **Harness Autonomy**: The caller describes *what* to achieve; the callee decides *how*.
- **Standardized Transport**: AMQP 0-9-1 as the single transport protocol. One implementation, universal interoperability.
- **Protocol Simplicity**: Core spec covers common patterns. Advanced features via extensions.

## Repository Structure

```
├── spec/                          # Protocol specification (English)
│   ├── overview.md
│   ├── architecture.md
│   ├── L1-transport-encoding.md
│   ├── L2-session-lifecycle.md
│   ├── L3-safety-contract.md
│   ├── L4-task.md
│   └── zh/                        # Protocol specification (中文)
│       ├── overview.md
│       ├── architecture.md
│       ├── L1-transport-encoding.md
│       ├── L2-session-lifecycle.md
│       ├── L3-safety-contract.md
│       └── L4-task.md
├── discuss/                       # Discussion logs and pending decisions
│   ├── discussion-log.md
│   └── zh/
│       └── discussion-log.md
├── examples/                      # Example scenarios (planned)
├── extensions/                    # Protocol extensions (planned)
└── core-concepts-reference/       # Background research and references
```

## HCP vs MCP

| | MCP | HCP |
|---|---|---|
| Callee | Passive tool | Autonomous agent |
| Interaction | Call function → get result | Submit intent → agent iterates → stream results |
| Steps | Single | Multi-step, unpredictable |
| Lifecycle | Stateless | Stateful sessions with events |
| Safety | None | Mandatory pre-execution risk assessment (R1–R5), safety envelope enforcement |
| Contract | Implicit tool schema | Explicit Capability Declaration with risk ceiling, hazard categories, constraints |
| Data governance | None | Data classification (T1–T4) with sensitivity-aware handling |
| Authorization | None | Session Token scoping entire execution session |
| Recovery | N/A | Checkpoint & resume for long-running tasks |
| Transport | Stdio / HTTP+SSE | AMQP 0-9-1 with durable delivery |
| Scope | Used *inside* a harness | Used *between* harnesses |

MCP and HCP are **complementary**. A harness uses MCP internally to invoke tools, and HCP externally to delegate work to other harnesses.

## Status

This protocol is in **early definition phase**. Contributions and discussions are welcome.

## License

[Apache License 2.0](LICENSE)
