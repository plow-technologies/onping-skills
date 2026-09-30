---
name: onping-hmi-list
description: List the OnPing HMIs available to the user via GET /hmi/list. Read-only. Returns each HMI's name, UUID, dashboard, and panel — the discovery entry point for finding UUIDs to export, back up, or delete.
allowed-tools: Bash(uv run *)
---

# OnPing HMI List

List the HMIs available to the authenticated user — the discovery entry point for
the HMI skills. `GET /hmi/list` returns a JSON array of `HmiInfo` records, one per
HMI placed on a dashboard panel the user can see:

`{ hmiInfoName, hmiInfoUuid, hmiInfoDashboardName, hmiInfoPanelName }`

The `hmiInfoUuid` values feed `onping-hmi-export`, `onping-hmi-export-data`, and
`onping-hmi-delete`.

> **Scoped to dashboard panels.** The list only includes HMIs embedded on
> dashboard panels. A freshly upserted HMI (e.g. an `onping-hmi-import --new`
> copy) that is not placed on a panel will **not** appear here — retrieve it
> directly by its UUID instead. Read-only.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-hmi-export** / **onping-hmi-export-data** — Export an HMI by the UUID this lists
- **onping-hmi-delete** — Delete an HMI by UUID

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Table (uuid, name, panel, dashboard)
uv run ~/.claude/skills/onping-hmi-list/scripts/list_hmis.py "$ACCESS_TOKEN"
# Just UUIDs, space-separated
uv run ~/.claude/skills/onping-hmi-list/scripts/list_hmis.py "$ACCESS_TOKEN" --uuids-only
# Raw JSON
uv run ~/.claude/skills/onping-hmi-list/scripts/list_hmis.py "$ACCESS_TOKEN" --json
```

## Flags

- `--json` — emit the raw JSON array from `/hmi/list`.
- `--uuids-only` — print just the HMI UUIDs, space-separated (pipe into export/delete).
- `--panel-only` — only rows with a non-empty panel name.

## Output

- **Default:** a table of `UUID | NAME | PANEL | DASHBOARD` with a count on stderr; an empty list exits 0 cleanly.
- **`--uuids-only` / `--json`:** the UUIDs or raw array on stdout; count on stderr.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/hmi/list` | GET | JSON `[HmiInfo]` — `{hmiInfoName, hmiInfoUuid, hmiInfoDashboardName (nullable), hmiInfoPanelName}` |

## Authentication

`/hmi/list` accepts **Bearer token auth** from `onping-login` (verified).

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit).
- **Unexpected shape** — a non-array response fails with a diagnostic.
