---
name: onping-hmi-delete
description: Delete an OnPing HMI dashboard by UUID via DELETE /hmi/delete/{uuid}. MUTATING, requires --yes. Soft delete (sets dashDeleted=true). Back up first with onping-hmi-export.
allowed-tools: Bash(uv run *)
---

# OnPing HMI Delete

> **⚠️ WARNING: this skill changes live data.**
> It deletes an HMI dashboard (a soft delete: OnPing flags it `dashDeleted=true`). There is no undelete command; export the HMI first with `onping-hmi-export` so you can restore it with `onping-hmi-import`. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Delete an HMI dashboard by UUID. `DELETE /hmi/delete/{uuid}` removes an HMI.

> **Soft delete.** OnPing sets `dashDeleted = true` on the dashboard rather than
> hard-removing it; `GET /hmi/{uuid}` still returns the (flagged) record
> afterward. Requires **Delete** permission on the HMI UUID.

> **Delete is a MUTATION.** Nothing is deleted unless you pass `--yes`. The
> default and `--dry-run` probe the HMI via `GET /hmi/{uuid}` to show what would
> be deleted, but do not delete. **Back up first** with `onping-hmi-export`.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-hmi-list** — Find the HMI UUID to delete
- **onping-hmi-export** — Back up the HMI before deleting (recommended)
- **onping-hmi-import** — Restore a deleted HMI from a backup, or clean up a `--new` copy

## Usage

**Preview (default — probes the HMI, does not delete):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-hmi-delete/scripts/delete_hmi.py "$ACCESS_TOKEN" <uuid>
```

**Apply (actually deletes):**

```bash
uv run ~/.claude/skills/onping-hmi-delete/scripts/delete_hmi.py "$ACCESS_TOKEN" <uuid> --yes
```

**Recommended — back up first:**

```bash
uv run ~/.claude/skills/onping-hmi-export/scripts/export_hmi.py "$ACCESS_TOKEN" <uuid> --output backup.dhall
uv run ~/.claude/skills/onping-hmi-delete/scripts/delete_hmi.py "$ACCESS_TOKEN" <uuid> --yes
```

## Flags

- `--yes` — perform the deletion. **Required** for the DELETE call.
- `--dry-run` — explicit preview; probes the HMI, makes no delete. Wins over `--yes`.
- `--json` — emit JSON instead of text.

## Output

- **Preview:** the UUID and current name (from a read-only `GET /hmi/{uuid}` probe), a note if it is already flagged deleted; no delete; exit 0.
- **Apply:** confirmation of the soft delete; exit 0 on success, non-zero on failure.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/hmi/delete/{uuid}` | DELETE | JSON `[]` (HTTP 200) on success; soft delete (`dashDeleted=true`) |
| `/hmi/{uuid}` | GET | JSON `HmiDashboard` — used by `--dry-run` to preview the target |

## Authentication

`/hmi/delete/{uuid}` accepts **Bearer token auth** from `onping-login` (verified) and requires **Delete** permission on the HMI UUID.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); nothing is deleted.
- **No Delete permission / not found** — a non-200 is surfaced verbatim, exit non-zero.
