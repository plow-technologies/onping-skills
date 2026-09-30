---
name: onping-hmi-export-data
description: Export an OnPing HMI's data-binding mappings to a Dhall file via GET /hmi/export-data/{uuid}. Read-only. Exports only the OnPing-parameter bindings ([DataImport]), not the layout — re-point an HMI's data with onping-hmi-import-data.
allowed-tools: Bash(uv run *)
---

# OnPing HMI Data Export

Export only an HMI's **data-binding mappings** to a Dhall file — the OnPing
parameters the HMI reads, without its visual design. `GET /hmi/export-data/{uuid}`
returns a Dhall `[DataImport]` list, each `{ from: { onpingKey, description }, to:
Maybe onpingKey }` (`Content-Type: text/x-dhall`, `filename="hmi-data.dhall"`).

> **Data bindings only, not the full dashboard.** Use this to transfer or
> re-point which OnPing parameters an HMI reads (e.g. copy a display's bindings to
> another well) without touching layout. For the FULL dashboard, use
> `onping-hmi-export`.

> **Read-only** — no `--yes` gate. Requires **Write** permission on the HMI UUID.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-hmi-list** — Discover HMI UUIDs
- **onping-hmi-import-data** — Import the data bindings this emits into a target HMI (the round-trip)
- **onping-hmi-export** — Export the full dashboard (layout + everything), not just bindings

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-hmi-export-data/scripts/export_hmi_data.py "$ACCESS_TOKEN" <uuid>
uv run ~/.claude/skills/onping-hmi-export-data/scripts/export_hmi_data.py "$ACCESS_TOKEN" <uuid> --output hmi-data.dhall
```

## Flags

- `--output PATH` — write the Dhall to this file (also printed to stdout; status line to stderr). Written only after a confirmed 200.

## Output

A Dhall `[DataImport]` list. With `--output`, written verbatim to the path and a status line goes to stderr.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/hmi/export-data/{uuid}` | GET | Dhall `[DataImport]`; `Content-Type: text/x-dhall;charset=utf-8`; `Content-Disposition: attachment; filename="hmi-data.dhall"` |

## Authentication

`/hmi/export-data/{uuid}` accepts **Bearer token auth** from `onping-login` (verified) and requires **Write** permission on the HMI UUID.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no file is written.
- **No Write permission / not found** — a non-200 is surfaced verbatim; no file is written.
