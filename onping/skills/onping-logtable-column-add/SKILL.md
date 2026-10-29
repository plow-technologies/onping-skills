---
name: onping-logtable-column-add
description: Add a column recording a PID or VPID (with a selector, default Result, and optional position) to an OnPing log table, as a new schema version through POST /logtable/<LJ>/source/schema/upgrade. MUTATING — previews by default, posts only with --yes, backs up the LogTableSource, verifies the read-back. The new version starts with no rows.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — Column Add

> **⚠️ WARNING: this skill changes live data.** It changes what a live log
> table records. It previews BEFORE/AFTER by default and changes nothing until
> you pass `--yes`; `--dry-run` also previews and wins over `--yes`. With
> `--yes` it first writes a JSON backup of the whole LogTableSource.

> **⚠️ Every column edit creates a new, EMPTY schema version.** A log-table
> edit is `schema/upgrade` to version v+1, and the server starts a new table
> for it. Rows recorded under earlier versions are not migrated; read them with
> `onping-logtable-fetch --version N`. Column UUIDs are kept across versions.
> Each run adds one version, so plan a set of edits before applying them.

## Related Skills

- **onping-logtable-get** — current columns and positions
- **onping-logtable-column-delete** / **-column-set** — the other column edits
- **onping-datatable-fetch --row** — the PIDs a data-table row names

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-logtable-column-add/scripts/add_logtable_column.py
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --pid 500002 --name casingPressure            # preview
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --vpid 70 --name flowRate --at 1 --yes      # apply
```

## Flags

- `--pid N` / `--vpid N` (one required) — what the column records.
- `--name NAME` (required) — must not match an existing column.
- `--selector S` — `Result` (default), `Unit`, `Description`, `LastUpdateDateTime`, … `Text` and `Invalid` are not allowed in a log table.
- `--at POS` — insert at position POS (0 is the far left); default last. Positions are re-packed 0..n-1.
- `--yes`, `--dry-run`, `--backup PATH` — default backup: `./logtable-<LJ>-<uuid>-<UTC>.backup.json`.

## Output

BEFORE (version v) and AFTER (version v+1) grids with `<-- new` on the
column, the empty-version warning, and on `--yes` the backup path,
`POST schema/upgrade: OK`, and the read-back result.

## How it works

The script copies the current schema, adds the column with a fresh UUID,
re-packs positions, sets version v+1, and checks the result the way the server
does (`isValidSchema`: a column keyed by the event PID with
`LastUpdateDateTime`) plus position consistency. The posted body is the
stored source at version v+1 with the new schema listed first, so name, group,
and flags are unchanged. The read-back compares version, event source, every
column, and the version list.

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/logtable/<LJ>/source/list` | GET | — | `[LogTableSource]` |
| `/logtable/<LJ>/source/schema/upgrade` | POST | the source at version v+1, new schema first | the stored source |

Handler: `onping/Handler/OnpingLogTable/Service.hs (postLogTableSourceSchemaUpgradeR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned groups; `Permission Denied` comes back as HTTP 500.

## Error Handling

- **Duplicate name, duplicate PID+selector, bad selector, bad `--at`** — refused before any request is posted; exit 1.
- **Version conflict** (someone else upgraded first) — the server rejects a version other than stored+1; re-run to rebuild from the new version.
- **Read-back mismatch** — exit 1 listing differences; the backup is on disk.
- **Permission Denied / token expired** — exit 1 with a hint.
