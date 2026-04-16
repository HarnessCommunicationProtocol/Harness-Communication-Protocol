---
layout: default
title: "L2: 会话与生命周期"
parent: 中文
nav_order: 4
---

[English](../L2-session-lifecycle) | **中文**
{: .text-right }

# L2：会话与生命周期层

## 目的

L2 管理任务会话的生命周期——从创建、执行到终止。它定义了会话状态机、用于执行可见性的标准事件类型，以及检查点与恢复机制。

## 会话

**会话（session）** 代表单个任务执行的生命周期。当任务通过 L3 安全验证后创建，当任务到达终止状态时销毁。

### 会话属性

| 属性 | 类型 | 描述 |
|------|------|------|
| `session_id` | string (UUID v4) | 唯一会话标识符，由被调用方生成 |
| `state` | enum | 当前生命周期状态 |
| `created_at` | timestamp | 会话创建时间 |
| `updated_at` | timestamp | 上次状态转换时间 |
| `session_token` | string | L3 签发的会话授权令牌 |
| `risk_level` | enum (R1–R5) | L3 评估的风险等级 |
| `metadata` | object | 调用方提供和被调用方分配的元数据 |

## 会话状态机

```
                     TaskSubmit received
                           │
                           ▼
                       PENDING
                       │     │
               L3 Approve   L3 Reject
                       │     │
                       ▼     ▼
                   RUNNING  REJECTED ─── (terminal)
                   │  │  │
          ┌────────┘  │  └────────┐
          ▼           │           ▼
       PAUSED     RUNNING     ABORTING
          │                       │
          └───► RUNNING           ▼
                              ABORTED ──── (terminal)

               RUNNING
               │     │
               ▼     ▼
         COMPLETED  FAILED ──── (terminal)
         (terminal)
```

### 状态定义

| 状态 | 描述 | 触发条件 |
|------|------|----------|
| **PENDING** | 任务已接收，等待 L3 安全检查 | 收到 `task_submit` |
| **REJECTED** | 任务未通过 L3 安全检查（终止态） | L3 拒绝任务 |
| **RUNNING** | 任务正由被调用方 harness 主动执行 | L3 批准任务 |
| **PAUSED** | 执行暂时挂起，会话保留 | 被调用方决策或检查点 |
| **ABORTING** | 已请求中止，被调用方正在清理 | 调用方发送 `abort` |
| **ABORTED** | 执行已中止，清理完成（终止态） | 被调用方完成中止清理 |
| **COMPLETED** | 任务成功完成（终止态） | 被调用方报告成功 |
| **FAILED** | 任务因不可恢复的错误而终止（终止态） | 被调用方报告失败 |

### 有效状态转换

| 源状态 | 目标状态 | 触发条件 |
|--------|----------|----------|
| PENDING | RUNNING | L3 安全检查通过 |
| PENDING | REJECTED | L3 安全检查未通过 |
| RUNNING | PAUSED | 被调用方暂停执行 |
| RUNNING | ABORTING | 调用方发送 `abort` |
| RUNNING | COMPLETED | 任务成功完成 |
| RUNNING | FAILED | 不可恢复的错误 |
| PAUSED | RUNNING | 被调用方恢复执行 |
| PAUSED | ABORTING | 暂停期间调用方发送 `abort` |
| ABORTING | ABORTED | 被调用方完成清理 |

## 事件流

在执行过程中，被调用方发出事件流以提供执行进度的可见性。所有事件均通过 L1 事件通道传递。

### 事件信封

事件承载于 `type: "event"` 的 L1 消息的 `payload` 中：

```json
{
  "hcp_version": "1.0",
  "message_id": "...",
  "timestamp": "...",
  "session_id": "...",
  "type": "event",
  "payload": {
    "event_type": "progress",
    "sequence": 42,
    "data": { }
  }
}
```

| 字段 | 类型 | 描述 |
|------|------|------|
| `event_type` | string (enum) | 事件类型 |
| `sequence` | integer | 会话内单调递增的序列号 |
| `data` | object | 特定于事件类型的内容 |

### 标准事件类型

| 事件类型 | 描述 | 数据字段 |
|----------|------|----------|
| `session_created` | 会话已创建，执行即将开始 | `state`, `risk_level`, `session_token` |
| `state_changed` | 会话状态已转换 | `from_state`, `to_state`, `reason` |
| `progress` | 执行进度更新 | `stage` (string), `percent` (number, 可选), `message` (string) |
| `intermediate_result` | 部分或中间结果可用 | `result_type`, `data`, `is_partial` |
| `log` | 执行日志条目 | `level` (info/warn/error), `message`, `details` |
| `warning` | 非致命警告 | `code`, `message`, `details` |
| `error` | 发生错误但执行继续 | `code`, `message`, `recoverable` |
| `checkpoint_created` | 检查点已保存 | `checkpoint_id`, `description`, `resumable` |
| `session_closed` | 会话已到达终止状态 | `final_state`, `reason` |

### 事件排序

- 事件必须（MUST）在会话内以严格递增的 `sequence` 编号发出。
- 消费者必须（MUST）按 `sequence` 顺序处理事件。
- 如果事件由于传输特性导致乱序到达，消费者应当（SHOULD）进行缓冲并重新排序。

### 与 L1 流连续性的集成

`sequence` 编号是 L2 的机制，与 L1 基于 AMQP ACK 的流连续性（参见 [L1-transport-encoding.md — 流连续性](./L1-transport-encoding.md#stream-continuity)）配合使用，以提供**无丢失、去重、有序的事件投递**。

**调用方的逐会话跟踪**：

调用方必须（MUST）为每个活跃会话维护一个 `last_processed_sequence` 值。该值用于：

1. **重新投递时的去重**：当 L1 在调用方崩溃后重新投递消息（AMQP requeue）时，调用方检查 `event.sequence <= last_processed_sequence`——如果为真，则该事件已被处理，跳过（但仍然 ACK 以推进队列）。

2. **间隙检测**：如果调用方收到 `sequence = N+2` 而未处理过 `N+1`，则检测到间隙。在正常 AMQP 投递下这不应发生，但可作为安全检查。检测到间隙时，调用方应当（SHOULD）记录警告并继续处理（缺失的事件可能通过重新投递到达）。

3. **重启后恢复**：重启时，调用方从持久化存储加载 `last_processed_sequence`（如果可用）以恢复去重能力。如果未持久化，幂等的事件处理（如 L1 所建议的）将处理重新投递。

**交互模型**：

```
L1 (AMQP)                    L2 (Session)                  Caller Application
    │                              │                              │
    │  deliver event               │                              │
    │  (delivery_tag=7)            │                              │
    │─────────────────────────────►│                              │
    │                              │  parse session_id, sequence  │
    │                              │  check: seq > last_processed?│
    │                              │                              │
    │                              │  ├─ Yes: forward to app ────►│ process event
    │                              │  │  update last_processed    │
    │                              │  │                           │
    │  basic.ack(delivery_tag=7) ◄─┤  │  signal ACK to L1        │
    │                              │  │                           │
    │                              │  └─ No (duplicate): skip     │
    │  basic.ack(delivery_tag=7) ◄─┤     ACK without processing  │
    │                              │                              │
```

**核心原则**：L1 确保消息**永不丢失**（AMQP 持久化投递 + 手动 ACK + 重新入队）。L2 确保事件**永不重复处理**（基于 sequence 的去重）且**始终有序**（基于 sequence 的排序）。两者结合，在应用层提供恰好一次（exactly-once）语义。

## 检查点与恢复

对于长时间运行的任务，检查点允许在中断后恢复执行。

### 检查点

检查点是被调用方在给定时间点的执行状态快照。创建检查点时，被调用方发出 `checkpoint_created` 事件。

```json
{
  "event_type": "checkpoint_created",
  "sequence": 100,
  "data": {
    "checkpoint_id": "ckpt-001",
    "description": "Completed phase 1: material preparation",
    "resumable": true,
    "created_at": "2025-01-15T10:00:00.000Z"
  }
}
```

### 恢复

如果被调用方 harness 故障并重启，它可以（MAY）从最近的检查点恢复。恢复是被调用方的内部事务——协议不定义检查点如何存储或状态如何重建。从调用方的角度来看：

1. 事件流可能存在间隙（故障与恢复之间的事件会丢失）。
2. 被调用方应当（SHOULD）在恢复后发出 `state_changed` 事件，并将 `reason` 设为 `"recovered_from_checkpoint"`。
3. 执行从检查点继续，新事件追加到同一会话中。

## 会话超时

- 被调用方应当（SHOULD）强制执行最大会话持续时间，该时间来源于任务的 `max_duration` 约束（L4）或系统默认值。
- 如果执行超过超时时间，被调用方转换至 FAILED 状态，原因为 `"timeout"`。
- 空闲会话（在可配置的时间段内未发出事件）可以（MAY）由被调用方进行清理。

## 中止协议

当调用方发送 `abort` 消息时：

1. 会话转换至 **ABORTING** 状态。
2. 被调用方开始清理：停止 LLM 调用、终止正在运行的工具、释放资源。
3. 清理应当（SHOULD）受限于被调用方定义的中止超时时间。
4. 清理完成后，会话转换至 **ABORTED** 状态。
5. 被调用方发出 `session_closed` 事件，`final_state: "ABORTED"`。

被调用方必须（MUST）尽最大努力进行清理，但不要求保证在任何特定时间范围内释放资源。调用方应当（SHOULD）将 ABORTING 视为将最终解析为 ABORTED 的瞬态状态。
