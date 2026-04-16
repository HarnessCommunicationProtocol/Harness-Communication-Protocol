---
layout: default
title: "L1: 传输与编码"
parent: 中文
nav_order: 6
---

[English](../L1-transport-encoding) | **中文**
{: .text-right }

# L1：传输与编码层

## 目的

L1 定义了 HCP 消息如何在网络上进行编码、封帧和传递。HCP 以 **AMQP 0-9-1** 作为标准传输协议，避免生态系统中的碎片化——每个符合 HCP 规范的 harness 使用相同的有线协议。

## 为什么选择 AMQP

HCP 需要可靠的、异步的、双向的消息传递，并支持持久化投递。AMQP 原生提供了所有这些能力：

- **标准化**：AMQP 0-9-1 是一个成熟的线级协议，拥有广泛的实现支持（RabbitMQ、LavinMQ、Apache Qpid 等）
- **Exchange + Queue 路由**：自然映射到 HCP 的命令和事件通道，无需自定义路由逻辑
- **持久化投递**：消息可以持久化到磁盘，在 broker 重启后仍然存在
- **确认机制**：消费端 ACK 确保至少一次投递
- **广泛支持**：几乎所有语言和平台都有客户端库

通过固定传输层，callee harness 只需实现一种协议，任何 caller 都可以通过共享的 AMQP broker 与任何 callee 通信。

## 消息信封

每条 HCP 消息都包裹在一个标准信封中，作为 AMQP 消息体承载：

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

### 信封字段

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `hcp_version` | string | 是 | 协议版本。格式：`MAJOR.MINOR` |
| `message_id` | string (UUID v4) | 是 | 此消息的唯一标识符 |
| `timestamp` | string (ISO 8601) | 是 | 消息创建时间，UTC |
| `session_id` | string (UUID v4) \| null | 条件必需 | 会话标识符。仅在初始 `task_submit` 消息中为 `null`。所有后续消息必须（MUST）包含有效的会话 ID |
| `type` | string (enum) | 是 | 消息类型。参见[消息类型](#消息类型) |
| `payload` | object | 是 | 层级特定内容。结构取决于 `type` |

### AMQP 消息属性映射

HCP 信封字段映射到 AMQP 消息属性，用于 broker 级别的路由和去重：

| AMQP 属性 | HCP 来源 | 用途 |
|-----------|----------|------|
| `message_id` | `message_id` | Broker 级别去重 |
| `timestamp` | `timestamp` | 消息创建时间 |
| `correlation_id` | `session_id` | 会话关联，用于路由 |
| `content_type` | `"application/json"` | 固定为 JSON |
| `content_encoding` | `"utf-8"` | 固定为 UTF-8 |
| `delivery_mode` | `2`（持久化） | 持久化投递 |
| `type` | `type` | 消息类型，用于消费端过滤 |

### 消息类型

消息按方向分类：

**Caller → Callee（命令通道）**

| 类型 | 说明 | 需要会话 |
|------|------|----------|
| `task_submit` | 提交新任务 | 否（会话由 callee 创建） |
| `abort` | 请求中止任务 | 是 |

**Callee → Caller（事件通道）**

| 类型 | 说明 |
|------|------|
| `task_accepted` | 任务通过安全检查，会话已创建 |
| `task_rejected` | 任务未通过安全检查 |
| `event` | 会话生命周期事件（进度、检查点等） |
| `task_completed` | 任务成功完成 |
| `task_failed` | 任务因错误而终止 |

## AMQP 拓扑

HCP 定义了所有实现必须（MUST）遵循的标准 AMQP 拓扑。

### 概览

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

### Exchange

| Exchange | 类型 | 持久化 | 说明 |
|----------|------|--------|------|
| `hcp.commands` | `direct` | 是 | 承载从 caller 到 callee 的命令消息 |
| `hcp.events` | `topic` | 是 | 承载从 callee 到 caller 的事件消息 |

### 队列

| 队列 | 绑定到 | 路由/绑定键 | 持久化 | 说明 |
|------|--------|------------|--------|------|
| `hcp.cmd.{callee_id}` | `hcp.commands` | `{callee_id}` | 是 | 特定 callee harness 的命令队列 |
| `hcp.evt.{caller_id}` | `hcp.events` | `{caller_id}.#` | 是 | 特定 caller harness 的事件队列 |

### 路由键

**命令通道**（`hcp.commands` exchange，直接路由）：

```
路由键: {callee_id}
```

Caller 向 `hcp.commands` 发布消息，路由键设置为目标 callee 的 ID。Broker 将消息路由到 callee 的命令队列。

**事件通道**（`hcp.events` exchange，主题路由）：

```
路由键: {caller_id}.{session_id}.{message_type}
```

Callee 向 `hcp.events` 发布消息，路由键包含 caller ID、会话 ID 和消息类型。这使得：

- **按 caller 路由**：每个 caller 的队列使用 `{caller_id}.#` 绑定，仅接收自己的事件
- **按会话过滤**：消费者可以选择使用 `{caller_id}.{session_id}.#` 绑定来创建会话专属队列
- **按类型过滤**：消费者可以使用 `{caller_id}.*.task_completed` 绑定来仅接收完成事件

### 拓扑示例

```
Caller "alpha" 向 Callee "lab-cvd" 提交任务：

命令：
  Exchange: hcp.commands
  路由键: lab-cvd
  队列: hcp.cmd.lab-cvd

事件：
  Exchange: hcp.events
  路由键: alpha.session-xyz.event
  队列: hcp.evt.alpha（绑定 "alpha.#"）
```

## 投递保证

### 命令通道

- **投递方式**：至少一次。Caller 必须（MUST）使用 `delivery_mode: 2`（持久化）发布，callee 必须（MUST）使用手动 ACK（`basic.ack`）。
- **顺序性**：AMQP 保证每个队列的 FIFO 顺序。由于发往某个 callee 的所有命令都进入同一个队列，顺序得以保留。
- **重试**：如果 caller 在可配置的超时时间内未收到 `task_accepted` 或 `task_rejected`，应当（SHOULD）使用相同的 `message_id` 重新发布 `task_submit`。Callee 必须（MUST）基于 `message_id` 进行去重。

### 事件通道

- **投递方式**：至少一次，保证顺序。Callee 必须（MUST）使用 `delivery_mode: 2` 发布，caller 必须（MUST）使用手动 ACK。
- **持久性**：事件队列是持久化的。Caller 断开连接期间发布的事件会保留在队列中，直到 caller 重新连接并消费。
- **幂等性**：每个事件都携带唯一的 `message_id`。消费者应当（SHOULD）基于 `message_id` 进行去重。
- **顺序性**：会话内的事件由 callee 按顺序发布。AMQP 的每队列 FIFO 保证它们按顺序到达。

## 流连续性

HCP 的核心要求之一是，callee 与 caller 之间的事件流即使在 caller 崩溃、重启或网络中断时也保持**稳定且无损**。HCP 完全通过标准 AMQP 消息状态机制实现这一点——不需要自定义的重放协议。

### 问题描述

在长时间运行的任务（可能持续数小时甚至数天）中，caller 可能：
1. 在流传输过程中崩溃并重启
2. 临时丢失网络连接
3. 被有意重启（例如部署、扩缩容）

在所有这些情况下，事件流必须从中断处精确恢复——不丢失事件、不产生间隙、不重复处理。

### 机制：基于 AMQP ACK 的流连续性

AMQP 提供三种消息状态，HCP 加以利用：

```
                        ┌──────────────┐
                        │   READY      │  消息在队列中，尚未投递
                        └──────┬───────┘
                               │ broker 投递给消费者
                               ▼
                        ┌──────────────┐
                        │ UNACKED      │  已投递但未确认
                        └──┬───────┬───┘
                           │       │
                  basic.ack│       │ 消费者断开连接
                           │       │ （崩溃 / 网络丢失）
                           ▼       ▼
                   ┌──────────┐  ┌──────────────┐
                   │ CONSUMED │  │ REQUEUED     │  返回 READY 状态，
                   │ （完成） │  │ （→ READY）  │  重新投递给下一个消费者
                   └──────────┘  └──────────────┘
```

**关键保证**：处于 UNACKED 状态的消息**永远不会丢失**。如果消费者在发送 `basic.ack` 之前断开连接，broker 会自动将消息重新入队，使其可被重新投递。

### Caller 消费者配置

Caller 必须（MUST）按如下方式配置其事件通道消费者：

| 参数 | 值 | 理由 |
|------|----|----|
| `no_ack` | `false` | **手动 ACK 模式。**Caller 在处理完每个事件后显式确认。这是流连续性的基础。 |
| `prefetch_count` | 1–100（推荐：10） | 控制 broker 提前投递多少未确认消息。值越高吞吐量越大；值越低崩溃时重新投递的消息越少。 |
| `exclusive` | `false` | 允许消费者在重启后重新连接到同一队列。 |

### ACK 策略

Caller 必须（MUST）遵循以下 ACK 策略：

```
Caller 从 broker 接收事件
       │
       ▼
处理事件
（更新本地状态、渲染到 UI、持久化到存储等）
       │
       ▼
处理是否成功？
├── 是 → basic.ack(delivery_tag)
│         消息从队列中永久移除。
│         Broker 推进投递游标。
│
└── 否（处理错误）→ basic.nack(delivery_tag, requeue=true)
          消息返回 READY 状态。
          Broker 将重新投递。
```

**关键规则**：Caller 在**完全处理**事件（持久化、渲染、转发等）之前，不得（MUST NOT）确认事件。在处理完成前确认可能导致崩溃时数据丢失。

### Caller 崩溃与恢复

```
时间线：

Caller 正常运行
│
│  event seq=1  ──► 处理 ──► basic.ack     ✓ 已消费
│  event seq=2  ──► 处理 ──► basic.ack     ✓ 已消费
│  event seq=3  ──► 处理 ──► basic.ack     ✓ 已消费
│  event seq=4  ──► 已投递（UNACKED）
│  event seq=5  ──► 已投递（UNACKED）        预取窗口
│
│  ╳ CALLER 崩溃
│
│  Broker 检测到 TCP 断开
│  │
│  ├─ event seq=4 ──► UNACKED → REQUEUED → READY
│  └─ event seq=5 ──► UNACKED → REQUEUED → READY
│
│  与此同时，callee 继续执行：
│  event seq=6 ──► 已发布 → READY（排在 seq=4,5 之后）
│  event seq=7 ──► 已发布 → READY
│
│  Caller 重启
│  │
│  ├─ 连接到 broker
│  ├─ 在 hcp.evt.{caller_id} 上声明消费者
│  └─ Broker 从队列头部开始投递：
│
│  event seq=4  ──► 重新投递（redelivered=true）
│  event seq=5  ──► 重新投递（redelivered=true）
│  event seq=6  ──► 首次投递
│  event seq=7  ──► 首次投递
│  ... 流无缝继续
```

Caller 的事件流从中断处精确恢复。没有事件丢失。不需要自定义重放协议。

### 处理重新投递的消息

当消息被重新投递时，AMQP 在投递元数据中将 `redelivered` 标志设置为 `true`。Caller 应当（SHOULD）处理重新投递：

1. **幂等处理**（推荐）：将事件处理设计为幂等的。处理同一事件两次产生相同的结果。这是最简单的方法。

2. **基于 message_id 去重**：维护一个最近处理过的 `message_id` 集合。在重新投递时，检查 `message_id` 是否已被处理，如果是则跳过。

3. **基于 L2 序列号去重**：使用 L2 事件的 `sequence` 编号。按会话跟踪最后处理的序列号。在重新投递时，跳过 `sequence <= last_processed_sequence` 的事件。

这些方法可以组合使用。L2 的 `sequence` 编号（参见 [L2-session-lifecycle.md](./L2-session-lifecycle)）提供了在重新投递和去重后仍然有效的确定性排序。

### 预取调优

`prefetch_count`（`basic.qos`）控制吞吐量与恢复粒度之间的权衡：

| 预取值 | 吞吐量 | 恢复成本 | 使用场景 |
|--------|--------|----------|----------|
| 1 | 最低 | 最小——最多重新处理 1 个事件 | 关键任务（R4–R5），UI 驱动的消费者 |
| 10 | 良好 | 最多重新处理 10 个事件 | 通用默认值 |
| 50–100 | 高 | 最多重新处理 N 个事件 | 高吞吐量批处理消费者 |

建议：从 `prefetch_count=10` 开始。对批处理/后台消费者增大；对延迟敏感或安全关键场景减小到 `1`。

### 网络分区（临时断开）

```
Caller ──── 已连接 ────╳ 网络丢失 ╳──── 重新连接 ────►

Broker 视角：
│ 检测到心跳超时（AMQP 心跳，例如 60 秒）
│ 关闭连接
│ 将此消费者的所有 UNACKED 消息重新入队
│ 将分区期间发布的新事件入队
│
│ Caller 重新连接：
│ 重新入队的 + 新入队的事件按 FIFO 顺序投递
```

**AMQP 心跳**能够及时检测死连接。HCP 实现应当（SHOULD）配置心跳：

| 参数 | 推荐值 | 理由 |
|------|--------|------|
| `heartbeat` | 30–60 秒 | 在 2× 心跳间隔内检测到死连接 |

### Callee 独立性

Callee 的执行与 caller 的连接状态**完全解耦**：

- Callee 向 `hcp.events` exchange 发布事件。Broker 将其放入 `hcp.evt.{caller_id}` 队列。
- 无论 caller 是否连接，只要 broker 可达，callee 的发布就能成功。
- Callee 不知道 caller 是否已消费、确认或崩溃。
- 这种解耦是根本性的：callee 永远不会因为 caller 而阻塞或暂停。

### 多会话流交错

单个 caller 事件队列（`hcp.evt.{caller_id}`）可能承载来自多个并发会话的事件。Caller 通过 `session_id` 进行多路分解：

```
队列: hcp.evt.alpha
│
├─ event (session=A, seq=10, type=progress)
├─ event (session=B, seq=3, type=tool_start)
├─ event (session=A, seq=11, type=progress)
├─ event (session=B, seq=4, type=tool_end)
├─ event (session=A, seq=12, type=completed)
│  ...

Caller 多路分解：
  会话 A 处理器: seq=10, 11, 12 → 按会话有序处理
  会话 B 处理器: seq=3, 4       → 按会话有序处理
```

每个会话的 `sequence` 编号是独立的。Caller **按会话**跟踪最后处理的序列号以进行去重。

### Broker 故障

如果 AMQP broker 本身发生故障：

- **持久化队列和持久化消息在 broker 重启后仍然存在。**恢复后，所有 READY 和 UNACKED 重新入队的消息均可用。
- Harness 应当（SHOULD）实现**指数退避**的连接重试（例如 1 秒、2 秒、4 秒、8 秒……上限 60 秒）。
- 为实现高可用，broker 应当（SHOULD）部署**仲裁队列**（RabbitMQ 3.8+），将队列状态复制到多个节点，可容忍少数节点故障。

### 总结：为什么不需要自定义重放协议

传统的事件流系统通常需要自定义重放机制（例如消费者偏移量跟踪、`Last-Event-ID`、基于游标的分页）。HCP 通过利用 AMQP 内置的消息生命周期避免了所有这些：

| 关注点 | HCP 解决方案 | AMQP 机制 |
|--------|-------------|-----------|
| 事件持久化 | 消息在断开连接后仍然存在 | `delivery_mode: 2`（持久化）+ 持久化队列 |
| 从崩溃中恢复 | 未处理的事件自动重新投递 | 手动 ACK + 断开连接时重新入队 |
| 重复检测 | 跳过已处理的事件 | `redelivered` 标志 + L2 `sequence` 编号 |
| 流量控制 | 限制在途消息数量 | `basic.qos`（prefetch_count） |
| 死连接检测 | 及时清理消费者状态 | AMQP 心跳 |
| 顺序保证 | 事件按发送顺序到达 | 每队列 FIFO |

这种设计确保从 caller 的角度来看，事件流是一个**连续的、无损的、有序的序列**——无论崩溃、网络问题还是重启。

## 编码

- 所有消息体必须（MUST）使用 **UTF-8 JSON** 编码。
- AMQP `content_type` 属性必须（MUST）设置为 `"application/json"`。
- AMQP `content_encoding` 属性必须（MUST）设置为 `"utf-8"`。
- 二进制数据（文件、图片、大型数据集）必须（MUST）通过 URI 引用，不得内联嵌入。
- 时间戳必须（MUST）使用 ISO 8601 格式的 UTC 时间（例如 `2025-01-15T08:30:00.000Z`）。
- 持续时间必须（MUST）使用 ISO 8601 持续时间格式（例如 `PT72H`、`PT2H15M`）。

## 队列管理

### TTL 与清理

| 队列 | 推荐 TTL | 理由 |
|------|----------|------|
| `hcp.cmd.{callee_id}` | 无 TTL | 只要 callee 存在，命令就应被消费 |
| `hcp.evt.{caller_id}` | 24 小时（消息 TTL） | 超过 24 小时未消费的事件可能已过时 |

- Callee 命令队列应当（SHOULD）在 callee harness 注册期间持续存在。
- Caller 事件队列可以（MAY）使用每消息 TTL（`x-message-ttl`）来丢弃过时事件。
- 会话专属事件队列（如使用）应当（SHOULD）在会话达到终态时自动删除。

### 队列大小限制

实现应当（SHOULD）在事件队列上配置 `x-max-length` 或 `x-max-length-bytes` 以防止无限增长。当达到限制时，应当（SHOULD）丢弃最旧的消息（`overflow: drop-head`）。

## 连接与认证

### 虚拟主机

所有 HCP exchange 和队列应当（SHOULD）在专用的 AMQP 虚拟主机（例如 `/hcp`）中创建，以将 HCP 流量与共享同一 broker 的其他应用隔离。

### 认证

- Harness 使用标准 AMQP SASL 机制向 AMQP broker 进行认证。
- 每个 harness 应当（SHOULD）拥有独立的凭据集。
- 访问控制（哪个 harness 可以发布/消费哪些队列）应当（SHOULD）通过 AMQP 权限在 broker 层面配置。

HCP 不定义自己的认证层——broker 级别的认证和授权足以满足传输安全需求。应用级身份（caller_id）由 L3 验证。

### TLS

所有 AMQP 连接应当（SHOULD）使用 TLS（`amqps://`）。未加密连接（`amqp://`）应当（SHOULD）仅在可信网络环境中使用（例如 localhost 开发）。

## 拓扑初始化

当 harness 启动时：

1. 连接到 AMQP broker。
2. 声明 `hcp.commands` 和 `hcp.events` exchange（幂等操作——`passive: false`，参数匹配）。
3. **如果是 callee**：声明并绑定 `hcp.cmd.{callee_id}` 队列。开始消费。
4. **如果是 caller**：声明并绑定 `hcp.evt.{caller_id}` 队列。开始消费。

Exchange 和队列声明是**幂等的**——多个 harness 使用相同参数声明同一 exchange 是安全的。
