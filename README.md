# Harness Communication Protocol (HCP)

An open message-queue-based protocol that enables secure communication between
AI agents and executable capabilities, providing a standardized way to validate
execution safety and environments before invocation, and to exchange tasks,
events, and results across tools, systems, and real-world resources.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)

---

## Overview

HCP defines:

- A typed, versioned **message envelope** for all protocol traffic
- A **pre-invocation safety validation** flow so capabilities can accept or
  reject requests before any code runs
- A clear **handshake** flow for capability discovery and version negotiation
- Asynchronous **event streaming** from capabilities back to agents
- Optional **HMAC-SHA256 message signing** for integrity and authentication
- A **pluggable transport layer** (in-process queue by default; plug in Redis,
  RabbitMQ, Kafka, etc.)

See [`SPEC.md`](SPEC.md) for the full protocol specification.

---

## Installation

```bash
pip install hcp
```

For development (includes pytest):

```bash
pip install -e ".[dev]"
```

---

## Quick Start

### 1. Define a Capability

```python
from hcp import Capability, CapabilityManifest

class Calculator(Capability):
    async def execute(self, task_name: str, args: dict) -> object:
        if task_name == "add":
            return args["a"] + args["b"]
        raise NotImplementedError(task_name)
```

### 2. Run Agent + Capability

```python
import asyncio
from hcp import Agent, HCPQueue, CapabilityManifest
from myapp import Calculator

async def main():
    # Shared in-process queue
    queue = HCPQueue()
    await queue.start()

    # Register capability
    manifest = CapabilityManifest(
        name="calculator",
        allowed_permissions=["math"],
    )
    cap = Calculator(capability_id="calculator", queue=queue, manifest=manifest)
    await cap.register()

    # Create and connect agent
    agent = Agent(agent_id="agent-1", queue=queue)
    await agent.connect()

    # Handshake (optional capability discovery)
    hs = await agent.handshake("calculator")
    print("Capabilities:", hs.capabilities)

    # Safety check before invocation
    await agent.safety_check(
        capability_id="calculator",
        task_name="add",
        required_permissions=["math"],
    )

    # Invoke a task
    result = await agent.invoke("calculator", "add", args={"a": 1, "b": 2})
    print("Result:", result.output)   # 3

    await agent.disconnect()
    await queue.stop()

asyncio.run(main())
```

### 3. Receive Events

```python
agent.on_event(lambda event: print(f"Event: {event.event_type}", event.data))
```

### 4. Sign Messages (optional)

```python
from hcp import Agent, Capability, CapabilityManifest, HCPQueue

SECRET = b"shared-secret-key"

agent = Agent(agent_id="agent-1", queue=queue, secret=SECRET)
cap   = Calculator(capability_id="calc", queue=queue, manifest=manifest, secret=SECRET)
```

All outbound messages are automatically signed; all inbound messages are
automatically verified.

---

## Message Flow

```
Agent                                   Capability
  |                                          |
  |-------- HANDSHAKE ---------------------->|
  |<------- HANDSHAKE (ack) -----------------|
  |                                          |
  |-------- SAFETY_CHECK ------------------->|
  |<------- SAFETY_RESPONSE (approved) ------|
  |                                          |
  |-------- TASK --------------------------->|
  |<------- EVENT (progress, optional) ------|
  |<------- RESULT (SUCCESS) ---------------|
```

---

## Architecture

```
hcp/
├── __init__.py        # Public API
├── messages.py        # Message envelope and all payload types
├── queue.py           # Async message queue + QueueAdapter interface
├── security.py        # HMAC signing, manifest, safety validator
├── agent.py           # AI Agent base class
├── capability.py      # Capability (Harness) base class
└── exceptions.py      # Protocol-specific exceptions
```

---

## Running Tests

```bash
pytest
```

---

## Protocol Specification

Full details on message types, security model, safety validation, and
extension points are in [`SPEC.md`](SPEC.md).

---

## License

Apache 2.0 – see [`LICENSE`](LICENSE).
