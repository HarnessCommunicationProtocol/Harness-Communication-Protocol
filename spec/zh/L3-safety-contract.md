---
layout: default
title: "L3: 安全契约"
parent: 中文
nav_order: 4
---

[English](../L3-safety-contract) | **中文**
{: .text-right }

# L3：安全与契约层

## 目的

L3 是 HCP 的强制安全关卡。每个任务提交在开始执行之前必须通过 L3。该层负责验证权限、评估风险、执行安全边界，并签发限定执行范围的会话令牌。任何任务都不能绕过 L3。

该层对以下场景至关重要：
- 物理设备与实验室仪器
- 危险物质、高温/高压工艺
- 敏感或机密数据
- 生产环境中的长时间运行操作
- 容器与沙箱执行安全

## 能力声明

被调用方 harness 发布一份**能力声明（Capability Declaration）**，描述它能做什么、需要什么以及可能涉及哪些风险。该声明作为"技能定义"，供调用方 harness 理解和调用被调用方。

### 能力声明模式

```json
{
  "capability": {
    "name": "cvd-material-synthesis",
    "version": "1.0.0",
    "description": "Synthesize 2D materials via Chemical Vapor Deposition with parameter control and Raman spectroscopy analysis",

    "input_schema": {
      "type": "object",
      "required": ["target_material", "substrate"],
      "properties": {
        "target_material": { "type": "string", "description": "Target material formula" },
        "substrate": { "type": "string", "description": "Substrate material" },
        "temperature_range": {
          "type": "object",
          "properties": {
            "min": { "type": "number" },
            "max": { "type": "number" },
            "unit": { "type": "string", "enum": ["celsius", "kelvin"] }
          }
        }
      }
    },

    "output_schema": {
      "type": "object",
      "properties": {
        "raman_analysis": { "type": "object" },
        "growth_log": { "type": "array" }
      }
    },

    "safety": {
      "risk_ceiling": "R4",
      "requires_human_approval": true,
      "involves_physical_resources": true,
      "resource_types": ["high_temperature_furnace", "gas_supply", "vacuum_system"],
      "hazard_categories": ["high_temperature", "toxic_gas"]
    },

    "constraints": {
      "max_duration": "PT72H",
      "concurrent_limit": 1
    }
  }
}
```

### 能力声明字段

| 字段 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| `name` | string | 是 | 该能力的唯一标识符 |
| `version` | string (semver) | 是 | 能力版本 |
| `description` | string | 是 | 人类和 LLM 可读的能力功能描述 |
| `input_schema` | JSON Schema | 是 | 有效任务输入的模式 |
| `output_schema` | JSON Schema | 是 | 预期任务输出的模式 |
| `safety` | object | 是 | 安全特性（见下文） |
| `constraints` | object | 否 | 操作约束 |

### 安全声明字段

| 字段 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| `risk_ceiling` | enum (R1–R5) | 是 | 该能力可能涉及的最高风险等级 |
| `requires_human_approval` | boolean | 是 | 任务执行前是否需要人工审批 |
| `involves_physical_resources` | boolean | 是 | 该能力是否控制物理设备 |
| `resource_types` | string[] | 否 | 涉及的物理或虚拟资源类型 |
| `hazard_categories` | string[] | 否 | 潜在危害类别 |

## 风险分级

HCP 定义了五个风险等级。风险评估由被调用方的 L3 层根据任务输入和能力特性执行。

| 等级 | 名称 | 描述 | 示例 |
|------|------|------|------|
| **R1** | 极低 | 只读操作，无副作用 | 数据分析、报告生成 |
| **R2** | 低 | 沙箱环境中的可逆副作用 | 沙箱中创建文件、代码生成 |
| **R3** | 中等 | 受控环境中的不可逆副作用 | 数据库写入、部署至预发布环境 |
| **R4** | 高 | 涉及物理资源或敏感系统的操作 | 实验室仪器控制、生产环境部署 |
| **R5** | 极高 | 涉及生命安全或危险物质的操作 | 高压反应、有毒物质处理 |

### 风险评估流程

当收到 `task_submit` 时，L3 进行以下评估：

1. **静态风险基线**：能力声明中的 `risk_ceiling` 设定了最低可能风险。
2. **输入驱动的风险升级**：特定输入参数可能提升风险等级。例如，500°C 的 CVD 工艺可能为 R3，但 1200°C 时将升级为 R4。
3. **上下文因素**：时间（无人值守操作）、共享设备上的并发任务或资源可用性等因素可能进一步影响风险评估。

评估后的风险等级包含在 `task_accepted` 响应中，并携带在会话令牌内。

## 数据分级

任务涉及的数据标记有敏感度等级：

| 等级 | 名称 | 描述 | 处理要求 |
|------|------|------|----------|
| **T1** | 公开 | 非敏感数据 | 无限制 |
| **T2** | 内部 | 内部数据，不对外公开 | 访问日志记录 |
| **T3** | 机密 | 受限访问的敏感数据 | 传输和存储加密 |
| **T4** | 受限 | 高度敏感，涉及合规要求 | 加密、审计追踪、访问审批 |

数据分级由调用方在任务提交中声明，并由被调用方的 L3 层进行验证。

## 安全包络

对于涉及物理资源的能力（R4、R5），L3 定义了一个**安全包络（Safety Envelope）**——执行过程中绝不能超越的硬性边界。

```json
{
  "safety_envelope": {
    "parameters": {
      "temperature": { "max": 1000, "unit": "celsius", "hard_limit": true },
      "pressure": { "max": 5, "unit": "atm", "hard_limit": true },
      "gas_flow_rate": { "max": 200, "unit": "sccm", "hard_limit": true }
    },
    "prohibited_actions": [
      "simultaneous_gas_mixing_without_purge"
    ],
    "emergency_procedures": {
      "over_temperature": "immediate_shutdown",
      "gas_leak_detected": "close_all_valves_and_alert"
    }
  }
}
```

安全包络具有以下特性：
- 由被调用方根据设备规格和安全策略定义
- 在 L1 工具执行期间由被调用方**在本地**强制执行（被调用方的内部工具在执行物理命令前检查安全包络）
- 调用方**不可修改**——调用方不能放宽安全限制

## 权限审计

在批准任务之前，L3 验证以下内容：

1. **调用方身份**：调用方 harness 通过 AMQP 代理级别的凭证（SASL）进行身份认证。
2. **能力访问权**：调用方有权调用所请求的能力。
3. **输入验证**：任务输入符合能力的 `input_schema`。
4. **安全合规**：任务参数在调用方权限等级允许的风险阈值范围内。

权限等级较低的调用方可能被限制为较低的风险等级。例如，自动化流水线可能只能调用 R1–R2 能力，而有人工监督的会话可以访问 R4。

## 会话令牌

在批准任务后，L3 签发一个**会话令牌（Session Token）**，具有以下功能：

1. 授权执行会话
2. 编码已批准的风险等级和约束条件
3. 在该会话的所有后续消息中携带（通过 L2 会话元数据中的 `session_token`）
4. 被调用方的 L1/L2 层在每次操作时对其进行验证，以确保执行不超出批准的范围

### 会话令牌属性

| 属性 | 描述 |
|------|------|
| `token` | 不透明字符串，具体实现自定（例如 JWT、签名哈希） |
| `issued_at` | 令牌签发时间 |
| `expires_at` | 令牌过期时间（必须 ≤ 任务 max_duration） |
| `approved_risk_level` | 本会话批准的风险等级 |
| `approved_data_classification` | 本会话允许的最高数据敏感度等级 |
| `constraints` | 已批准的安全包络和操作约束 |

### 令牌格式

会话令牌的内部格式由具体实现决定。协议仅要求：
- 从调用方的角度来看它是一个不透明字符串
- 它包含在 `task_accepted` 响应中
- 它可被被调用方的 L2 和 L1 层验证

## 审批流程

```
TaskSubmit received
       │
       ▼
┌─── Permission Audit ───┐
│ Caller authenticated?   │─── No ──► TaskRejected (unauthorized)
│ Capability access OK?   │─── No ──► TaskRejected (forbidden)
│ Input schema valid?     │─── No ──► TaskRejected (invalid_input)
└─────────┬───────────────┘
          │ Yes
          ▼
┌─── Risk Assessment ────┐
│ Evaluate risk level     │
│ Check caller's allowed  │
│ risk threshold          │─── Exceeds ──► TaskRejected (risk_too_high)
└─────────┬───────────────┘
          │ Within limits
          ▼
┌─── Human Approval? ────┐
│ requires_human_approval │─── Yes ──► Queue for human review
│ && risk_level >= R3?    │           (async approval flow)
└─────────┬───────────────┘
          │ No / Approved
          ▼
   Issue SessionToken
   Return TaskAccepted
```

## TaskAccepted 响应

```json
{
  "hcp_version": "1.0",
  "message_id": "...",
  "timestamp": "...",
  "session_id": "new-session-uuid",
  "type": "task_accepted",
  "payload": {
    "session_token": "eyJhbGciOiJIUzI1NiIs...",
    "risk_level": "R3",
    "data_classification": "T2",
    "safety_envelope": { },
    "constraints": {
      "max_duration": "PT4H",
      "abort_timeout": "PT5M"
    }
  }
}
```

## TaskRejected 响应

```json
{
  "hcp_version": "1.0",
  "message_id": "...",
  "timestamp": "...",
  "session_id": null,
  "type": "task_rejected",
  "payload": {
    "reason_code": "risk_too_high",
    "reason_message": "Task parameters indicate R4 risk level, but caller is only authorized for R1-R3",
    "assessed_risk_level": "R4",
    "suggestion": "Reduce temperature_range.max to below 800°C to qualify for R3"
  }
}
```

`suggestion` 字段为可选但建议提供——它帮助调用方（或调用方的 LLM）理解如何调整任务以使其被接受。
