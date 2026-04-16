---
layout: default
title: Home
nav_order: 1
description: "HCP: An open protocol for secure communication between AI agent harnesses"
---

# HCP: Harness Communication Protocol

An open protocol for secure communication between AI agent harnesses — enabling standardized task delegation, safety validation, session lifecycle management, and event-driven result exchange across autonomous agent systems.
{: .fs-6 .fw-300 }

一个开放的 AI 智能体 Harness 间安全通信协议 —— 提供标准化的任务委派、安全验证、会话生命周期管理，以及跨自主智能体系统的事件驱动结果交换。
{: .fs-5 .fw-300 }

[English Specification](spec/){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 }
[中文文档](spec/zh/){: .btn .fs-5 .mb-4 .mb-md-0 }

---

## What is HCP? / 什么是 HCP？

HCP defines how one AI agent harness delegates work to another. Unlike tool-invocation protocols (e.g., MCP) that call passive functions, HCP communicates with **autonomous agents** — the callee harness receives an intent, independently decides how to execute it, and streams progress and results back to the caller.

HCP 定义了一个 AI 智能体 harness 如何将工作委派给另一个 harness。与调用被动函数的工具调用协议（如 MCP）不同，HCP 与**自主智能体**通信——被调用方 harness 接收一个意图，独立决定如何执行，并将进度和结果以流的方式返回给调用方。

## Protocol Stack / 协议栈

| Layer | Name | Responsibility |
|-------|------|----------------|
| **L4** | Task Layer / 任务层 | Intent description, constraints, result exchange |
| **L3** | Safety & Contract / 安全契约层 | Risk assessment, permission audit, session token issuance |
| **L2** | Session & Lifecycle / 会话与生命周期层 | Session state machine, event streaming, checkpoint/recovery |
| **L1** | Transport & Encoding / 传输与编码层 | Message envelope, AMQP topology, channel specification |

---

## English

| Document | Description |
|----------|-------------|
| [Overview](spec/overview) | Protocol overview and design principles |
| [Architecture](spec/architecture) | Layered architecture and interaction model |
| [L1: Transport & Encoding](spec/L1-transport-encoding) | AMQP topology, message envelope, stream continuity |
| [L2: Session & Lifecycle](spec/L2-session-lifecycle) | Session state machine, event stream, checkpoint |
| [L3: Safety & Contract](spec/L3-safety-contract) | Risk assessment, capability declaration, session token |
| [L4: Task](spec/L4-task) | Task submission, results, error handling |

---

## 中文

| 文档 | 说明 |
|------|------|
| [协议总览](spec/zh/overview) | 协议概述与设计原则 |
| [协议架构](spec/zh/architecture) | 分层架构与交互模型 |
| [L1: 传输与编码层](spec/zh/L1-transport-encoding) | AMQP 拓扑、消息信封、流式续流 |
| [L2: 会话与生命周期层](spec/zh/L2-session-lifecycle) | 会话状态机、事件流、检查点 |
| [L3: 安全契约层](spec/zh/L3-safety-contract) | 风险评估、能力声明、Session Token |
| [L4: 任务层](spec/zh/L4-task) | 任务提交、结果返回、错误处理 |

---

## Key Design Principles / 核心设计原则

- **Unidirectional / 单向调用**: Strict Caller → Callee model
- **Safety as Core / 安全为核心**: Mandatory L3 safety gate for every task
- **Harness Autonomy / Harness 自治**: Caller describes *what*; callee decides *how*
- **Standardized Transport / 标准化传输**: AMQP 0-9-1 as the single transport protocol
- **Protocol Simplicity / 协议简洁**: Core spec covers common patterns; advanced features via extensions

---

## HCP vs MCP

| | MCP | HCP |
|---|---|---|
| Callee / 被调方 | Passive tool | Autonomous agent |
| Interaction / 交互 | Call function → get result | Submit intent → agent iterates → stream results |
| Lifecycle / 生命周期 | Stateless | Stateful sessions with events |
| Safety / 安全性 | None | Mandatory pre-execution risk assessment (R1–R5) |
| Transport / 传输 | Stdio / HTTP+SSE | AMQP 0-9-1 with durable delivery |
| Scope / 适用范围 | Inside a harness | Between harnesses |

MCP and HCP are **complementary**. A harness uses MCP internally to invoke tools, and HCP externally to delegate work to other harnesses.

MCP 和 HCP **互为补充**。Harness 内部使用 MCP 调用工具，对外使用 HCP 委派工作给其他 harness。

---

## License

[Apache License 2.0](https://github.com/vian-ai/Harness-Communication-Protocol/blob/main/LICENSE)
