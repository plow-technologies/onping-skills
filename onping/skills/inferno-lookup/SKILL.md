---
name: inferno-lookup
description: Look up Inferno language documentation - functions, syntax, and examples. Use when writing or debugging Inferno scripts for OnPing ML, Virtual, or Control parameters.
allowed-tools: Bash(uv run *), Read
---

# Inferno Language Lookup

Look up Inferno scripting language documentation for OnPing.

## Inferno Parameter Types

- **ML Parameters**: Scripts that reference Inferno ML models
- **Virtual Parameters**: Compute on multiple parameters at view/alarm time
- **Control Parameters**: Run scripts on periodic schedules or input-change triggers using Lumberjack edge devices

## Documentation Files

- **Virtual/Control**: `docs/inferno-virtual-control.md` - Functions for Virtual and Control parameters
- **ML**: `docs/inferno-ml.md` - ML-specific extensions including TorchScript model inference, Bedrock LLM prompting (`ML.prompt`, `ML.promptWith`), structured JSON output via schemas (`Schema` and `JSON` modules)
- **Control vs Virtual**: `docs/inferno-control-vs-virtual.md` - Runtime model differences for control vs virtual parameters (triggers, outputs, and execution model)

## Usage

Read the documentation for Virtual/Control parameters:
```bash
cat ~/.claude/skills/inferno-lookup/docs/inferno-virtual-control.md
```

Read the documentation for ML parameters:
```bash
cat ~/.claude/skills/inferno-lookup/docs/inferno-ml.md
```

Read control-vs-virtual behavior notes:
```bash
cat ~/.claude/skills/inferno-lookup/docs/inferno-control-vs-virtual.md
```

## Refresh Documentation

To update the cached documentation:
```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/inferno-lookup/scripts/fetch_docs.py "$ACCESS_TOKEN"
```

## When to Use

- User asks about Inferno syntax or functions
- Writing new Inferno scripts
- Debugging Inferno parameter issues
- Understanding the difference between ML, Virtual, and Control parameters
- Interpreting control parameter trigger/output behavior from `cp-list` payloads (including the output exclusivity constraint: one CP per output parameter)
