---
name: onping-add-micrologix
description: Print the JSON request/response schema for the OnPing micrologix driver `/micrologix/location/add` POST endpoint. Read-only — does NOT call OnPing.
allowed-tools: Bash(uv run *)
---

# OnPing add-micrologix schema

Prints the curated JSON request and response shape for the `POST /micrologix/location/add` endpoint. The data lives in `_driver_add_schemas/schemas.py`; this skill is a thin reader.

This skill is **read-only**. It makes no network call. Hitting `POST /micrologix/location/add` for real (which would create a record on OnPing) is intentionally out of scope.

## Source of truth

- Handler: `onping/Handler/Micrologix/Service.hs` (in the OnPing repo)
- Request type: `MicrologixLocationConfig`

If the Haskell types drift, re-verify against the recorded handler location and update `_driver_add_schemas/schemas.py`.

## Usage

```bash
uv run ~/.claude/skills/onping-add-micrologix/scripts/show_add_schema.py
```

## Output

A JSON object with keys: `driver`, `endpoint`, `handler`, `request_type`, `request_schema`, `response_type`, `response_schema`.
