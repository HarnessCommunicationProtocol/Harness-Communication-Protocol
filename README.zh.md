[English](README.md) | **中文**

# HCP(Harness Communication Protocol)：Harness 通信协议

一个开放的 AI 智能体 Harness 间安全通信协议 —— 提供标准化的任务委派、安全验证、会话生命周期管理，以及跨自主智能体系统的事件驱动结果交换。

## 什么是 HCP？

HCP 定义了一个 AI 智能体 harness 如何将工作委派给另一个 harness。与调用被动函数的工具调用协议（如 MCP）不同，HCP 与**自主智能体**通信——被调用方 harness 接收一个意图，独立决定如何执行，并将进度和结果以流的方式返回给调用方。

Harness 是包裹 LLM、工具、执行环境和 Agent Loop 的运行时。当作为远程服务暴露时，harness 以 **skill** 的形态呈现——一个具备自主推理能力的自包含能力单元。

## 协议栈

| 层 | 名称 | 职责 |
|----|------|------|
| **L4** | [任务层](spec/zh/L4-task.md) | 意图描述、约束声明、结果交换 |
| **L3** | [安全契约层](spec/zh/L3-safety-contract.md) | 风险评估、权限审计、Session Token 签发 |
| **L2** | [会话与生命周期层](spec/zh/L2-session-lifecycle.md) | 会话状态机、事件流、检查点/恢复 |
| **L1** | [传输与编码层](spec/zh/L1-transport-encoding.md) | 消息信封、AMQP 拓扑、通道规范 |

## 核心设计原则

- **单向调用**：严格的 Caller → Callee 模型，不支持回调，无双向复杂性
- **安全为核心**：每个任务都必须通过强制的安全门控层（L3）
- **Harness 自治**：调用方描述*做什么*；被调用方决定*怎么做*
- **标准化传输**：AMQP 0-9-1 作为唯一传输协议，一次实现，全局互通
- **协议简洁**：核心规范覆盖常见场景，高级功能通过扩展实现

## 仓库结构

```
├── spec/                          # 协议规范（英文）
│   ├── overview.md                # 协议总览与设计原则
│   ├── architecture.md            # 分层架构与交互模型
│   ├── L1-transport-encoding.md   # L1: 传输与编码层
│   ├── L2-session-lifecycle.md    # L2: 会话与生命周期层
│   ├── L3-safety-contract.md      # L3: 安全契约层
│   ├── L4-task.md                 # L4: 任务层
│   └── zh/                        # 协议规范（中文）
│       ├── overview.md
│       ├── architecture.md
│       ├── L1-transport-encoding.md
│       ├── L2-session-lifecycle.md
│       ├── L3-safety-contract.md
│       └── L4-task.md
├── discuss/                       # 讨论记录与待定决策
│   ├── discussion-log.md          # 英文
│   └── zh/
│       └── discussion-log.md      # 中文
├── examples/                      # 示例场景（计划中）
├── extensions/                    # 协议扩展（计划中）
└── core-concepts-reference/       # 背景研究与参考资料
```

## HCP 与 MCP 的对比

| | MCP | HCP |
|---|---|---|
| 被调方 | 被动工具 | 自主智能体 |
| 交互模式 | 调用函数 → 获取结果 | 提交意图 → 智能体迭代 → 流式返回结果 |
| 执行步骤 | 单步 | 多步，不可预知 |
| 生命周期 | 无状态 | 有状态会话，支持事件流 |
| 安全性 | 无 | 强制的执行前风险评估（R1–R5），安全包络校验 |
| 契约 | 隐式工具 schema | 显式能力声明，含风险上限、危害类别、约束条件 |
| 数据治理 | 无 | 数据分级（T1–T4），按敏感度分级处理 |
| 授权 | 无 | Session Token 约束整个执行会话 |
| 恢复机制 | 无 | 检查点与恢复，支持长时任务 |
| 传输 | Stdio / HTTP+SSE | AMQP 0-9-1，持久化投递 |
| 适用范围 | harness *内部*使用 | harness *之间*使用 |

MCP 和 HCP **互为补充**。Harness 内部使用 MCP 调用工具，对外使用 HCP 委派工作给其他 harness。

## 状态

本协议处于**早期定义阶段**。欢迎参与贡献和讨论。

## 许可证

[Apache License 2.0](LICENSE)
