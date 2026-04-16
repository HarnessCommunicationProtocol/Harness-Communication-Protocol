---
layout: default
title: Overview
parent: English
nav_order: 1
---

[English](overview) | [中文](zh/overview)
{: .text-right }

# HCP: Harness Communication Protocol

## Overview

HCP (Harness Communication Protocol) is an open, message-queue-based protocol that defines how AI agent harnesses communicate with each other. It provides a standardized way to submit tasks, validate execution safety, manage session lifecycles, and exchange events and results between harnesses.

## What is a Harness?

A harness is the runtime environment that wraps an AI model (LLM) and orchestrates its interaction with tools, resources, and execution environments. A harness includes:

- An **agent loop** — the core reasoning cycle that calls the LLM and routes its decisions
- **Tools and capabilities** — MCP servers, local tools, sandboxes, domain-specific instruments
- **Context management** — session history, memory, context engineering
- **Autonomous iteration** — the ability to decide execution strategy and iterate until a task is complete

A harness is a **superset of capability**. Unlike a passive tool that receives parameters and returns results, a harness has autonomous reasoning ability — it determines *how* to accomplish a task, not just *what* to execute.

## Core Concept: Harness as Skill

When a harness exposes itself as a remote service, it appears to the calling harness as a **skill** — a unit of capability with a name, description, and input/output contract. The key difference from a traditional tool or MCP server is that the callee harness:

1. Receives an **intent** (what to achieve), not a **command** (what to execute)
2. **Autonomously decides** the execution plan through its own agent loop
3. **Iterates independently**, potentially making many LLM calls and tool invocations
4. **Streams progress** back to the caller via an event protocol
5. **Returns a result** when the task is complete, failed, or aborted

```
┌─────────────────────────┐                        ┌─────────────────────────┐
│   Caller Harness        │         HCP            │   Callee Harness        │
│                         │                        │                         │
│   LLM + Agent Loop      │  Task / Events / Result│   LLM + Agent Loop      │
│   Local Tools (MCP)     │◄──────────────────────►│   Specialized Tools     │
│   Skills (incl. remote) │                        │   Domain Knowledge      │
│                         │                        │   Physical Instruments  │
└─────────────────────────┘                        └─────────────────────────┘
```

## How HCP Differs from MCP

| Dimension | MCP (Model Context Protocol) | HCP (Harness Communication Protocol) |
|-----------|------------------------------|--------------------------------------|
| Call model | Deterministic: call tool with parameters → get result | Autonomous: submit task with intent → harness iterates |
| Steps | Single-step | Multi-step, unpredictable count |
| Callee | Passive tool | Agent with reasoning capability |
| Discovery | `list_tools` / `list_resources` | Not needed; callee is a known capability set |
| Visibility | Synchronous return, no intermediate state | Event stream with progress, warnings, intermediate results |
| Lifecycle | Stateless, call-and-return | Stateful session, may last hours or days |
| Safety | None — caller is responsible for safe invocation | Mandatory L3 safety gate: risk assessment (R1–R5), permission audit, safety envelope enforcement before any execution begins |
| Contract | Implicit — tool schema defines parameters | Explicit — Capability Declaration with input/output schema, risk ceiling, hazard categories, and operational constraints |
| Data governance | None | Data classification (T1–T4) with sensitivity-aware handling requirements |
| Authorization | None at protocol level | Session Token issued by L3, scoping and constraining the entire execution session |
| Checkpoint & recovery | N/A (single-step, no state) | Checkpoint mechanism for long-running tasks; session can survive callee failure and resume from last checkpoint |
| Abort | N/A | Caller can abort a running session; callee performs graceful cleanup |
| Transport | Stdio / HTTP+SSE | AMQP 0-9-1 with durable delivery, message persistence, and built-in reconnection |
| Scope | Used *inside* a harness to invoke tools | Used *between* harnesses to delegate autonomous work |

MCP and HCP are **complementary**, not competing. MCP operates *within* a harness as the tool invocation protocol. HCP operates *between* harnesses as the task delegation protocol.

## Design Principles

### 1. Unidirectional Call Model
Communication follows a strict Caller → Callee direction. The callee does not call back into the caller during task execution. This keeps the protocol simple and avoids complex bidirectional state management. Simplicity enables ecosystem adoption.

### 2. Safety as a Core Layer
Safety validation is not optional. Every task submission passes through a safety contract layer before execution begins. This layer evaluates risks, validates permissions, enforces safety envelopes, and issues session tokens that constrain execution scope. This is critical for scenarios involving physical devices, hazardous materials, or sensitive data.

### 3. Protocol Simplicity
The core protocol covers the most common interaction patterns. Advanced features such as task granularity levels, sub-task decomposition, and multi-party coordination are addressed through extensions, not the core spec. A simple core protocol encourages implementation and adoption.

### 4. Standardized Transport
HCP standardizes on **AMQP 0-9-1** as its transport protocol. By fixing the transport layer, every HCP-compliant harness speaks the same wire protocol — callee harnesses need only one implementation, and any caller can communicate with any callee through a shared AMQP broker. This avoids ecosystem fragmentation where different callees require different transport adapters.

### 5. Harness Autonomy
The protocol respects the autonomy of the callee harness. The caller describes *what* should be achieved (intent, constraints, expected output) but does not prescribe *how*. The callee's internal execution — which LLM it uses, which tools it calls, how many iterations it performs — is opaque to the protocol.

## Protocol Stack

HCP is organized as a four-layer protocol stack:

| Layer | Name | Responsibility |
|-------|------|----------------|
| **L4** | Task Layer | Task submission, intent description, constraints, result exchange |
| **L3** | Safety & Contract Layer | Capability declaration, risk assessment, permission audit, session token issuance |
| **L2** | Session & Lifecycle Layer | Session state machine, event stream protocol, checkpoint, interruption/recovery |
| **L1** | Transport & Encoding Layer | Message envelope format, AMQP topology, channel specification |

Data flows **downward** through the stack on task submission (L4 → L3 → L2 → L1) and events flow **upward** on execution (L1 → L2 → L4).

See [architecture.md](./architecture.md) for the detailed layer architecture and interaction model.
