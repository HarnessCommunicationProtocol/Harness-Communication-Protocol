---
layout: default
title: "L4: 任务层"
parent: 中文
nav_order: 6
---

[English](../L4-task) | **中文**
{: .text-right }

# L4：任务层

## 目的

L4 定义了调用方如何描述其期望执行的任务，以及被调用方如何传达执行结果。这是面向应用的层——它承载意图、输入、约束条件和结果。L4 将任务描述聚焦于*做什么*，而将*怎么做*留给被调用方 harness 的自主代理循环。

## 任务提交

调用方通过 `task_submit` 消息提交任务。该消息是整个 HCP 交互的入口。

### TaskSubmit 模式

```json
{
  "hcp_version": "1.0",
  "message_id": "...",
  "timestamp": "...",
  "session_id": null,
  "type": "task_submit",
  "payload": {
    "capability": "cvd-material-synthesis",
    "capability_version": "1.x",
    "caller_id": "harness-alpha-001",
    "intent": "Synthesize monolayer MoS2 on SiO2/Si substrate and perform Raman spectroscopy characterization",
    "inputs": {
      "target_material": "MoS2",
      "substrate": "SiO2/Si",
      "temperature_range": {
        "min": 700,
        "max": 750,
        "unit": "celsius"
      }
    },
    "constraints": {
      "max_duration": "PT72H",
      "confidence_threshold": 0.95,
      "data_classification": "T2"
    },
    "expected_output": {
      "format": "raman_spectrum_analysis",
      "required_fields": ["peak_distance", "layer_count", "confidence"],
      "schema": {
        "type": "object",
        "required": ["peak_distance", "layer_count"],
        "properties": {
          "peak_distance": { "type": "number", "description": "A1g-E2g peak distance in cm^-1" },
          "layer_count": { "type": "integer", "description": "Estimated layer count" },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
        }
      }
    },
    "context": {
      "purpose": "Verify growth parameters for single-layer MoS2 synthesis optimization",
      "references": ["doi:10.1021/nl903868w"]
    }
  }
}
```

### TaskSubmit 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `capability` | string | 是 | 要调用的能力名称（与被调用方的 Capability Declaration 匹配） |
| `capability_version` | string | 否 | 可接受的能力版本 semver 范围（例如 `"1.x"`、`">=2.0.0"`） |
| `caller_id` | string | 是 | 调用方 harness 的标识符 |
| `intent` | string | 是 | 自然语言描述调用方希望实现的目标。此字段由被调用方的 LLM 读取以理解任务目标 |
| `inputs` | object | 是 | 符合该能力 `input_schema` 的结构化输入 |
| `constraints` | object | 否 | 执行约束条件（见下文） |
| `expected_output` | object | 否 | 期望的输出格式描述（见下文） |
| `context` | object | 否 | 帮助被调用方理解任务的附加上下文信息 |

### 约束条件

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_duration` | string（ISO 8601 时长） | 允许的最大执行时间 |
| `confidence_threshold` | number（0–1） | 结果可接受的最低置信度 |
| `data_classification` | enum（T1–T4） | 所涉数据的敏感等级 |
| `priority` | enum（low/normal/high/urgent） | 相对优先级提示 |

### 期望输出

| 字段 | 类型 | 说明 |
|------|------|------|
| `format` | string | 命名的格式标识符 |
| `required_fields` | string[] | 结果中必须包含的字段 |
| `schema` | JSON Schema | 期望输出结构的完整模式 |

### 上下文

`context` 字段提供补充信息，可帮助被调用方的 LLM 产生更好的结果。该字段不针对任何模式进行验证。

| 字段 | 类型 | 说明 |
|------|------|------|
| `purpose` | string | 请求此任务的原因 |
| `references` | string[] | 参考材料的 DOI、URL 或标识符 |
| `notes` | string | 供被调用方 LLM 参考的自由格式备注 |

## 任务完成

当被调用方成功完成任务时，发送 `task_completed` 消息。

### TaskCompleted 模式

```json
{
  "hcp_version": "1.0",
  "message_id": "...",
  "timestamp": "...",
  "session_id": "...",
  "type": "task_completed",
  "payload": {
    "outputs": {
      "peak_distance": 18.47,
      "layer_count": 1,
      "confidence": 0.97,
      "spectrum_data": {
        "raman_shift": [380, 382, 384, 386, 388, 390, 392, 394, 396, 398, 400, 402, 404, 406],
        "intensity": [120, 135, 180, 450, 980, 1200, 950, 400, 200, 150, 160, 300, 750, 400]
      }
    },
    "artifacts": [
      {
        "name": "raw_spectrum",
        "type": "application/json",
        "uri": "hcp://session-abc/artifacts/raman_raw.json",
        "size_bytes": 45200
      },
      {
        "name": "growth_log",
        "type": "text/csv",
        "uri": "hcp://session-abc/artifacts/growth_log.csv",
        "size_bytes": 128000
      }
    ],
    "execution_summary": {
      "duration": "PT2H15M",
      "steps_executed": 42,
      "checkpoints_created": 3,
      "risk_events": [],
      "warnings": ["Chamber pressure fluctuation at T+45min, within tolerance"]
    }
  }
}
```

### TaskCompleted 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `outputs` | object | 是 | 结构化结果数据，若指定了 `expected_output.schema` 则须符合该模式 |
| `artifacts` | array | 否 | 生成的制品列表（文件、数据集等） |
| `execution_summary` | object | 否 | 执行指标和重要事件的摘要 |

### 制品

制品通过 URI 引用，而非内嵌。URI 方案取决于具体实现：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 人类可读的制品名称 |
| `type` | string（MIME） | 内容类型 |
| `uri` | string | 用于检索制品的 URI |
| `size_bytes` | integer | 制品大小 |
| `checksum` | string | 可选的完整性哈希（例如 `"sha256:abc..."`） |

制品检索不在 HCP 核心协议的范围之内。URI 方案和访问机制由具体实现决定。

## 任务失败

当任务因不可恢复的错误而失败时，被调用方发送 `task_failed` 消息。

### TaskFailed 模式

```json
{
  "hcp_version": "1.0",
  "message_id": "...",
  "timestamp": "...",
  "session_id": "...",
  "type": "task_failed",
  "payload": {
    "error_code": "execution_error",
    "error_message": "Furnace temperature controller reported communication timeout after 3 retries",
    "error_details": {
      "phase": "material_growth",
      "step": 15,
      "last_checkpoint": "ckpt-002",
      "recoverable": false
    },
    "partial_outputs": {
      "growth_log": {
        "entries_before_failure": 142
      }
    },
    "artifacts": [
      {
        "name": "partial_growth_log",
        "type": "text/csv",
        "uri": "hcp://session-abc/artifacts/growth_log_partial.csv",
        "size_bytes": 64000
      }
    ],
    "execution_summary": {
      "duration": "PT1H10M",
      "steps_executed": 15,
      "checkpoints_created": 2,
      "risk_events": ["furnace_comm_timeout"]
    }
  }
}
```

### 标准错误码

| 错误码 | 说明 |
|--------|------|
| `execution_error` | 任务执行过程中发生的错误 |
| `timeout` | 任务超过了 `max_duration` 限制 |
| `safety_violation` | 执行将违反安全包络 |
| `resource_unavailable` | 所需资源不可用 |
| `internal_error` | 被调用方 harness 内部故障 |
| `input_error` | 输入数据格式错误或不充分（在执行过程中发现） |

### 部分结果

当任务在产生部分结果后失败时，被调用方应当（SHOULD）包含：
- `partial_outputs`：失败前已产生的结构化结果
- `artifacts`：失败前已生成的制品
- `error_details.last_checkpoint`：最后一个检查点 ID，使调用方能够在恢复上下文中重新提交任务

## 简单任务示例

并非所有任务都涉及物理仪器或复杂的安全要求。以下是一个最小化的文本分析任务：

### TaskSubmit

```json
{
  "hcp_version": "1.0",
  "message_id": "msg-001",
  "timestamp": "2025-01-15T08:30:00.000Z",
  "session_id": null,
  "type": "task_submit",
  "payload": {
    "capability": "document-analysis",
    "caller_id": "harness-local-01",
    "intent": "Analyze the provided research paper and extract key findings with confidence scores",
    "inputs": {
      "document_uri": "https://example.com/papers/paper-123.pdf",
      "analysis_type": "key_findings_extraction"
    },
    "constraints": {
      "max_duration": "PT10M",
      "data_classification": "T1"
    },
    "expected_output": {
      "required_fields": ["findings"],
      "schema": {
        "type": "object",
        "properties": {
          "findings": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "statement": { "type": "string" },
                "confidence": { "type": "number" },
                "source_section": { "type": "string" }
              }
            }
          }
        }
      }
    }
  }
}
```

### TaskCompleted

```json
{
  "hcp_version": "1.0",
  "message_id": "msg-010",
  "timestamp": "2025-01-15T08:32:15.000Z",
  "session_id": "session-xyz",
  "type": "task_completed",
  "payload": {
    "outputs": {
      "findings": [
        {
          "statement": "The proposed catalyst achieves 95% conversion rate under ambient conditions",
          "confidence": 0.92,
          "source_section": "Results, Section 3.2"
        },
        {
          "statement": "Reaction selectivity improves by 23% compared to baseline",
          "confidence": 0.87,
          "source_section": "Results, Section 3.4"
        }
      ]
    },
    "execution_summary": {
      "duration": "PT2M15S",
      "steps_executed": 5
    }
  }
}
```

此示例说明 HCP 既适用于轻量级、低风险的任务，也适用于复杂的长时间运行操作。相同的协议结构可以从 R1 级文档分析扩展到 R5 级危险材料处理。
