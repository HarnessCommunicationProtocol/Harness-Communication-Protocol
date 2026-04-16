---
layout: default
title: "L4: Task"
parent: English
nav_order: 6
---

[English](L4-task) | [中文](zh/L4-task)
{: .text-right }

# L4: Task Layer

## Purpose

L4 defines how the caller describes what it wants done and how the callee communicates results. This is the application-facing layer — it carries intent, inputs, constraints, and outcomes. L4 keeps the task description focused on *what*, leaving *how* to the callee harness's autonomous agent loop.

## Task Submission

The caller submits a task via a `task_submit` message. This message is the entry point for the entire HCP interaction.

### TaskSubmit Schema

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

### TaskSubmit Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `capability` | string | Yes | Name of the capability to invoke (matches callee's Capability Declaration) |
| `capability_version` | string | No | Semver range for acceptable capability versions (e.g., `"1.x"`, `">=2.0.0"`) |
| `caller_id` | string | Yes | Identifier of the calling harness |
| `intent` | string | Yes | Natural language description of what the caller wants to achieve. This is read by the callee's LLM to understand the goal |
| `inputs` | object | Yes | Structured inputs conforming to the capability's `input_schema` |
| `constraints` | object | No | Execution constraints (see below) |
| `expected_output` | object | No | Description of desired output format (see below) |
| `context` | object | No | Additional context to help the callee understand the task |

### Constraints

| Field | Type | Description |
|-------|------|-------------|
| `max_duration` | string (ISO 8601 duration) | Maximum allowed execution time |
| `confidence_threshold` | number (0–1) | Minimum acceptable confidence for results |
| `data_classification` | enum (T1–T4) | Sensitivity level of the data involved |
| `priority` | enum (low/normal/high/urgent) | Relative priority hint |

### Expected Output

| Field | Type | Description |
|-------|------|-------------|
| `format` | string | Named format identifier |
| `required_fields` | string[] | Fields that MUST be present in the result |
| `schema` | JSON Schema | Full schema for the expected output structure |

### Context

The `context` field provides supplementary information that may help the callee's LLM produce better results. It is not validated against any schema.

| Field | Type | Description |
|-------|------|-------------|
| `purpose` | string | Why this task is being requested |
| `references` | string[] | DOIs, URLs, or identifiers for reference materials |
| `notes` | string | Free-form notes for the callee's LLM |

## Task Completion

When the callee finishes the task successfully, it sends a `task_completed` message.

### TaskCompleted Schema

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

### TaskCompleted Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `outputs` | object | Yes | Structured result data, conforming to `expected_output.schema` if specified |
| `artifacts` | array | No | List of generated artifacts (files, datasets, etc.) |
| `execution_summary` | object | No | Summary of execution metrics and notable events |

### Artifacts

Artifacts are referenced by URI, not embedded. The URI scheme depends on the implementation:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable artifact name |
| `type` | string (MIME) | Content type |
| `uri` | string | URI for retrieving the artifact |
| `size_bytes` | integer | Artifact size |
| `checksum` | string | Optional integrity hash (e.g., `"sha256:abc..."`) |

Artifact retrieval is outside the scope of HCP core protocol. The URI scheme and access mechanism are implementation-specific.

## Task Failure

When a task fails due to an unrecoverable error, the callee sends a `task_failed` message.

### TaskFailed Schema

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

### Standard Error Codes

| Code | Description |
|------|-------------|
| `execution_error` | Error during task execution |
| `timeout` | Task exceeded `max_duration` |
| `safety_violation` | Execution would violate safety envelope |
| `resource_unavailable` | Required resource is not available |
| `internal_error` | Callee harness internal failure |
| `input_error` | Input data is malformed or insufficient (discovered during execution) |

### Partial Results

When a task fails after producing some results, the callee SHOULD include:
- `partial_outputs`: Whatever structured results were produced before failure
- `artifacts`: Any artifacts generated before failure
- `error_details.last_checkpoint`: The last checkpoint ID, enabling the caller to potentially resubmit with recovery context

## Simple Task Example

Not all tasks involve physical instruments or complex safety requirements. Here is a minimal text analysis task:

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

This example demonstrates that HCP works for lightweight, low-risk tasks as well as complex, long-running operations. The same protocol structure scales from R1 document analysis to R5 hazardous material handling.
