---
name: onping-add-elynx
description: Print the JSON request/response schema for the OnPing elynx driver `/elynx/integration/location/add` POST endpoint. Read-only — does NOT call OnPing.
allowed-tools: Bash(uv run *)
---

# OnPing add-elynx schema

Prints the curated JSON request and response shape for the `POST /elynx/integration/location/add` endpoint. The data lives in `_driver_add_schemas/schemas.py`; this skill is a thin reader.

This skill is **read-only**. It makes no network call. Hitting `POST /elynx/integration/location/add` for real (which would create a record on OnPing) is intentionally out of scope.

## Source of truth

- Handler: `onping/Handler/ElynxIntegration/Service.hs` (in the OnPing repo)
- Request type: `NewElynxLocation`

If the Haskell types drift, re-verify against the recorded handler location and update `_driver_add_schemas/schemas.py`.

## Usage

```bash
uv run ~/.claude/skills/onping-add-elynx/scripts/show_add_schema.py
```

## Output

A JSON object with keys: `driver`, `endpoint`, `handler`, `request_type`, `request_schema`, `response_type`, `response_schema`.
