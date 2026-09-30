---
name: onping-hmi-export
description: Export a full OnPing HMI dashboard to a Dhall file via GET /hmi/export/{uuid}. Read-only. Backs up an HMI (layout, components, settings, alerts) for restore or cloning with onping-hmi-import.
allowed-tools: Bash(uv run *)
---

# OnPing HMI Export

Export/back up a full HMI dashboard to a Dhall file — the recommended backup
step before editing, deleting, or cloning an HMI. Mirrors the OnPing web UI's HMI
export: a single `GET /hmi/export/{uuid}` returning the complete `HmiDashboard`
(id, name, all components, settings, alert config) as Dhall
(`Content-Type: text/x-dhall`, `filename="hmi.dhall"`).

> **Read-only** — no `--yes` gate (unlike `onping-hmi-import`). Requires **Write**
> permission on the HMI UUID (the export handler gates on Write, matching the UI).

> **Full dashboard, not just data.** This exports the entire HMI including layout
> and components. For only the OnPing-parameter data bindings, use
> `onping-hmi-export-data`.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-hmi-list** — Discover HMI UUIDs to export
- **onping-hmi-import** — Import/restore/clone the Dhall this emits (the round-trip)
- **onping-hmi-export-data** — Export only the data-binding mappings, not the full dashboard

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Print the Dhall to stdout
uv run ~/.claude/skills/onping-hmi-export/scripts/export_hmi.py "$ACCESS_TOKEN" <uuid>
# Save to a file (also printed to stdout; status line to stderr)
uv run ~/.claude/skills/onping-hmi-export/scripts/export_hmi.py "$ACCESS_TOKEN" <uuid> --output hmi.dhall
```

Discover a UUID first with `onping-hmi-list`, then export:

```bash
uv run ~/.claude/skills/onping-hmi-list/scripts/list_hmis.py "$ACCESS_TOKEN" --uuids-only
```

## Flags

- `--output PATH` — write the Dhall to this file (also printed to stdout; status line to stderr). The file is written only after a confirmed 200, so a failure never clobbers an existing backup.

## Output

A Dhall `HmiDashboard` document. With `--output`, written verbatim to the path (clean file even if stdout is also captured) and a status line goes to stderr.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/hmi/export/{uuid}` | GET | Dhall `HmiDashboard`; `Content-Type: text/x-dhall;charset=utf-8`; `Content-Disposition: attachment; filename="hmi.dhall"` |

The Dhall record uses `_dashId`, `_dashName`, `_dashComponents`, `_dashSettings`, `_dashAlertConfig`, `_dashLastUpdate`, `_dashDeleted`. (The JSON form used by import/upsert drops the underscore — `onping-hmi-import` handles that conversion via `/hmi/parse`.)

## Authentication

`/hmi/export/{uuid}` accepts **Bearer token auth** from `onping-login` (verified) and requires **Write** permission on the HMI UUID.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no file is written.
- **No Write permission / not found** — a non-200 (403/404) is surfaced verbatim; no file is written.
