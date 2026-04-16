---
layout: default
title: 协议架构
parent: 中文
nav_order: 2
---

[English](../architecture) | **中文**
{: .text-right }

# HCP 协议架构

## 分层架构

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

## 各层职责

### L4: 任务层 (Task Layer)

应用层。定义：

- **任务提交 (Task Submission)**：调用方如何描述意图、提供输入、声明约束以及指定预期输出格式
- **任务结果 (Task Result)**：被调用方如何返回最终结果、产物和执行摘要
- **任务拒绝 (Task Rejection)**：被调用方如何告知任务无法被接受的原因
- **错误报告 (Error Reporting)**：执行失败如何以可操作的详细信息进行通报

L4 关注的是*要做什么以及发生了什么*，而非如何投递或是否安全。

详见 [L4-task.md](./L4-task.md)

### L3: 安全与契约层 (Safety & Contract Layer)

安全门控层。定义：

- **能力声明 (Capability Declaration)**：被调用方 harness 如何描述其能力、输入/输出契约和安全特性
- **风险评估 (Risk Assessment)**：基于任务输入和能力特性的风险等级分类 (R1–R5)
- **权限审计 (Permission Audit)**：验证调用方是否有权调用所请求的能力
- **数据分级 (Data Classification)**：任务涉及数据的敏感度标记 (T1–T4)
- **安全包络 (Safety Envelope)**：执行不得超越的物理和逻辑边界约束
- **Session Token**：审批通过后签发的加密令牌，贯穿 L2 和 L1，约束执行范围

L3 是任务提交和执行之间的**强制门控**。没有 L3 的批准，任何任务都不会执行。

详见 [L3-safety-contract.md](./L3-safety-contract.md)

### L2: 会话与生命周期层 (Session & Lifecycle Layer)

状态管理层。定义：

- **会话状态机 (Session State Machine)**：任务会话的生命周期状态 (PENDING → RUNNING → COMPLETED/FAILED/ABORTED) 及有效转换
- **事件流协议 (Event Stream Protocol)**：用于进度报告、中间结果、警告、检查点和错误的标准事件类型
- **检查点与恢复 (Checkpoint & Recovery)**：会话如何暂停、建立检查点以及在中断后恢复
- **会话超时与清理 (Session Timeout & Cleanup)**：空闲检测和资源回收

L2 关注的是*会话生命周期和执行可见性*，而非任务内容或执行是否安全。

详见 [L2-session-lifecycle.md](./L2-session-lifecycle.md)

### L1: 传输与编码层 (Transport & Encoding Layer)

基础层。定义：

- **消息信封 (Message Envelope)**：所有 HCP 消息的标准包装器（版本、消息 ID、时间戳、会话 ID、消息类型、载荷）
- **通道规范 (Channel Specification)**：两个逻辑通道 — **命令通道** (调用方 → 被调用方) 和 **事件通道** (被调用方 → 调用方)，映射到 AMQP exchange 和 queue
- **AMQP 拓扑 (AMQP Topology)**：所有实现遵循的标准 exchange/queue/routing-key 约定

L1 关注的是*消息如何编码和投递*，而非其语义含义。HCP 将 AMQP 0-9-1 标准化为其传输协议。

详见 [L1-transport-encoding.md](./L1-transport-encoding.md)

## 端到端流程

一个完整的 HCP 交互遵循以下序列：

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

## 层间交互规则

1. **向下封装**：发送时每一层封装其上层。L4 任务数据被 L3 安全元数据包裹，由 L2 会话上下文管理，并由 L1 传输帧编码。

2. **向上传递**：接收时每一层剥离自身关注点。L1 解码传输帧，L2 路由到正确的会话，L3 验证 session token，L4 处理任务内容。

3. **L3 是门控而非管道**：与 L1 和 L2 始终传递数据不同，L3 可以**拒绝**整个任务。只有在 L3 批准后，数据才会流向 L2 和 L1 进行执行。

4. **事件旁路**：在执行期间，来自 L2 的事件直接通过 L1 返回给调用方，无需 L3 重新验证。任务提交时签发的 SessionToken 授权了整个会话范围。L3 的约束在执行期间由被调用方在本地强制执行。

## 多被调用方 Harness

一个调用方 harness 可以同时与多个被调用方 harness 交互，每个交互通过独立的 HCP 会话进行：

```
                         ┌─── HCP Session A ───► Callee Harness A
                         │                       (Data Analysis)
Caller Harness ──────────┤
                         │
                         └─── HCP Session B ───► Callee Harness B
                                                 (Lab Instrument Control)
```

每个会话是独立的。调用方 harness 负责跨会话协调结果 — 这种协调逻辑属于调用方内部事务，不在 HCP 的范围之内。
