---
layout: default
title: "L3: Safety & Contract"
parent: English
nav_order: 4
---

[English](L3-safety-contract) | [中文](zh/L3-safety-contract)
{: .text-right }

# L3: Safety & Contract Layer

## Purpose

L3 is the mandatory security gate of HCP. Every task submission MUST pass through L3 before execution begins. This layer validates permissions, assesses risk, enforces safety boundaries, and issues session tokens that constrain the scope of execution. No task bypasses L3.

This layer is critical for scenarios involving:
- Physical devices and laboratory instruments
- Hazardous materials, high-temperature/high-pressure processes
- Sensitive or classified data
- Long-running operations in production environments
- Container and sandbox execution security

## Capability Declaration

A callee harness publishes a **Capability Declaration** that describes what it can do, what it requires, and what risks it may involve. This declaration serves as the "skill definition" that a caller harness uses to understand and invoke the callee.

### Capability Declaration Schema

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

### Capability Declaration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for this capability |
| `version` | string (semver) | Yes | Capability version |
| `description` | string | Yes | Human and LLM readable description of what this capability does |
| `input_schema` | JSON Schema | Yes | Schema for valid task inputs |
| `output_schema` | JSON Schema | Yes | Schema for expected task outputs |
| `safety` | object | Yes | Safety characteristics (see below) |
| `constraints` | object | No | Operational constraints |

### Safety Declaration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `risk_ceiling` | enum (R1–R5) | Yes | Maximum risk level this capability may involve |
| `requires_human_approval` | boolean | Yes | Whether tasks require human sign-off before execution |
| `involves_physical_resources` | boolean | Yes | Whether the capability controls physical devices |
| `resource_types` | string[] | No | Types of physical or virtual resources involved |
| `hazard_categories` | string[] | No | Categories of potential hazards |

## Risk Classification

HCP defines five risk levels. Risk assessment is performed by the callee's L3 layer based on the task inputs and capability characteristics.

| Level | Name | Description | Examples |
|-------|------|-------------|----------|
| **R1** | Minimal | Read-only operations, no side effects | Data analysis, report generation |
| **R2** | Low | Reversible side effects in sandboxed environment | File creation in sandbox, code generation |
| **R3** | Moderate | Irreversible side effects in controlled environment | Database writes, deployment to staging |
| **R4** | High | Operations involving physical resources or sensitive systems | Lab instrument control, production deployment |
| **R5** | Critical | Operations with safety-of-life implications or hazardous materials | High-pressure reactions, toxic material handling |

### Risk Assessment Process

When a `task_submit` is received, L3 evaluates:

1. **Static risk floor**: The capability's declared `risk_ceiling` sets the minimum possible risk.
2. **Input-driven escalation**: Specific input parameters may elevate the risk level. For example, a CVD process at 500°C may be R3, but at 1200°C it escalates to R4.
3. **Contextual factors**: Time of day (unattended operation), concurrent tasks on shared equipment, or resource availability may further affect risk assessment.

The assessed risk level is included in the `task_accepted` response and carried in the session token.

## Data Classification

Data involved in a task is tagged with sensitivity levels:

| Level | Name | Description | Handling Requirements |
|-------|------|-------------|----------------------|
| **T1** | Public | Non-sensitive data | No restrictions |
| **T2** | Internal | Internal data, not for public release | Access logging |
| **T3** | Confidential | Sensitive data with restricted access | Encryption in transit and at rest |
| **T4** | Restricted | Highly sensitive, regulatory implications | Encryption, audit trail, access approval |

Data classification is declared by the caller in the task submission and validated by the callee's L3 layer.

## Safety Envelope

For capabilities involving physical resources (R4, R5), L3 defines a **safety envelope** — hard boundaries that execution must never exceed.

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

The safety envelope is:
- Defined by the callee based on equipment specifications and safety policies
- Enforced **locally** by the callee during L1 tool execution (the callee's internal tools check against the envelope before executing physical commands)
- **Not modifiable** by the caller — the caller cannot relax safety limits

## Permission Audit

Before approving a task, L3 verifies:

1. **Caller identity**: The caller harness is authenticated via AMQP broker-level credentials (SASL).
2. **Capability access**: The caller has permission to invoke the requested capability.
3. **Input validation**: The task inputs conform to the capability's `input_schema`.
4. **Safety compliance**: The task parameters fall within acceptable risk thresholds for the caller's permission level.

Callers with lower permission levels may be restricted to lower risk levels. For example, an automated pipeline may only invoke R1–R2 capabilities, while a human-supervised session may access R4.

## Session Token

Upon approving a task, L3 issues a **Session Token** that:

1. Authorizes the execution session
2. Encodes the approved risk level and constraints
3. Is carried in all subsequent messages for the session (via `session_token` in L2 session metadata)
4. Is validated by the callee's L1/L2 layers on each operation to ensure execution stays within approved scope

### Session Token Properties

| Property | Description |
|----------|-------------|
| `token` | Opaque string, implementation-specific (e.g., JWT, signed hash) |
| `issued_at` | When the token was issued |
| `expires_at` | When the token expires (MUST be ≤ task max_duration) |
| `approved_risk_level` | The risk level approved for this session |
| `approved_data_classification` | Maximum data sensitivity level for this session |
| `constraints` | Approved safety envelope and operational constraints |

### Token Format

The internal format of the session token is implementation-specific. The protocol requires only that:
- It is an opaque string from the caller's perspective
- It is included in the `task_accepted` response
- It is verifiable by the callee's L2 and L1 layers

## Approval Flow

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

## TaskAccepted Response

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

## TaskRejected Response

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

The `suggestion` field is optional but encouraged — it helps the caller (or the caller's LLM) understand how to adjust the task to make it acceptable.
