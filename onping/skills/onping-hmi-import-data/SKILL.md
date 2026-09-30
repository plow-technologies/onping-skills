---
name: onping-hmi-import-data
description: Import data-binding mappings into an existing OnPing HMI from a Dhall file via POST /hmi/import-data/{uuid}. MUTATING, requires --yes. Re-points which OnPing parameters an HMI reads ([DataImport]) without changing layout.
allowed-tools: Bash(uv run *)
---

# OnPing HMI Data Import

Import **data-binding mappings** into an existing HMI — the write-back inverse of
`onping-hmi-export-data`. `POST /hmi/import-data/{uuid}` takes a Dhall
`[DataImport]` body and applies those bindings to the HMI identified by `{uuid}`,
re-pointing which OnPing parameters it reads **without changing its layout**.

> **Data bindings only.** This does not change the dashboard's components or
> design — only which OnPing parameters they read. For the FULL dashboard, use
> `onping-hmi-import`.

> **Import is a MUTATION.** Nothing is written unless you pass `--yes`. The
> default and `--dry-run` preview the target UUID and input; no network call is
> made in preview mode. Requires **Write** permission on the target HMI.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-hmi-export-data** — Export the data bindings this imports (the round-trip)
- **onping-hmi-import** — Import the full dashboard (layout + everything), not just bindings
- **onping-hmi-list** — Find the target HMI UUID

## Usage

Requires a valid access token, a target HMI UUID, and a Dhall `[DataImport]` file
(from `onping-hmi-export-data`).

**Preview (default — makes no network call):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-hmi-import-data/scripts/import_hmi_data.py "$ACCESS_TOKEN" <uuid> --input hmi-data.dhall
```

**Apply (actually imports — replaces the HMI's data bindings):**

```bash
uv run ~/.claude/skills/onping-hmi-import-data/scripts/import_hmi_data.py "$ACCESS_TOKEN" <uuid> --input hmi-data.dhall --yes
```

**From stdin:**

```bash
cat hmi-data.dhall | uv run ~/.claude/skills/onping-hmi-import-data/scripts/import_hmi_data.py "$ACCESS_TOKEN" <uuid> --yes
```

## Flags

- `--input PATH` — Dhall `[DataImport]` file to import (default: read from stdin).
- `--yes` — perform the import. **Required** for any network call.
- `--dry-run` — explicit preview; makes no request. Wins over `--yes`.
- `--json` — emit JSON instead of text.

## Output

- **Preview:** the target UUID and an approximate binding count; no request; exit 0.
- **Apply:** the updated `HmiDashboard` JSON from OnPing; exit 0 on success, non-zero on failure.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|--------------|------|----------|
| `/hmi/import-data/{uuid}` | POST | `text/plain;charset=UTF-8` | Dhall `[DataImport]` — `{from: {onpingKey, description}, to: Maybe onpingKey}` | JSON `HmiDashboard` (bindings applied) |

## Authentication

`/hmi/import-data/{uuid}` accepts **Bearer token auth** from `onping-login` (verified) and requires **Write** permission on the target HMI UUID.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); nothing is imported.
- **Malformed Dhall / no Write permission** — a non-200 (or `{"error": ...}`) is surfaced verbatim, exit non-zero, nothing imported.
