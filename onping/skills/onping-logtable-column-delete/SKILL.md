---
name: onping-logtable-column-delete
description: Remove a column (by position, UUID, name, or the PID/VPID it records) from an OnPing log table, as a new schema version through POST /logtable/<LJ>/source/schema/upgrade. Refuses the event column. MUTATING — previews by default, posts only with --yes, backs up the LogTableSource, verifies the read-back.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — Column Delete

> **⚠️ WARNING: this skill changes live data.** The table stops recording the
> column. It previews BEFORE/AFTER by default and changes nothing until you
> pass `--yes`; `--dry-run` also previews and wins over `--yes`. With `--yes`
> it first writes a JSON backup of the whole LogTableSource. The column's past
> values are not destroyed: they stay in the older versions' rows.

> **⚠️ Every column edit creates a new, EMPTY schema version.** A log-table
> edit is `schema/upgrade` to version v+1, and the server starts a new table
> for it. Rows recorded under earlier versions are not migrated; read them with
> `onping-logtable-fetch --version N`. Column UUIDs are kept across versions.
> Each run adds one version, so plan a set of edits before applying them.

## Related Skills

- **onping-logtable-get** — find the column
- **onping-logtable-column-set** — move the trigger before removing an event column
- **onping-logtable-column-add** — the reverse

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-logtable-column-delete/scripts/delete_logtable_column.py
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --column flowRate          # preview
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --pid 500002 --yes         # apply
```

## Flags

- One of `--column REF` (position, UUID, or name), `--pid N`, `--vpid N`. A PID recorded by two columns is ambiguous; use `--column`.
- `--drop-filters` — a stored filter rule on the column blocks the delete; this removes those rules too.
- `--yes`, `--dry-run`, `--backup PATH` — default backup: `./logtable-<LJ>-<uuid>-<UTC>.backup.json`.

## Output

BEFORE/AFTER grids, the empty-version warning, and on `--yes` the backup
path, the POST result, and the read-back check.

## How it works

The column is removed everywhere the schema names it — columns, positions
(re-packed 0..n-1), order, hidden columns, custom widths, frozen column — and
the result is posted as version v+1, as in `onping-logtable-column-add`.

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/logtable/<LJ>/source/list` | GET | — | `[LogTableSource]` |
| `/logtable/<LJ>/source/schema/upgrade` | POST | the source at version v+1, new schema first | the stored source |

Handler: `onping/Handler/OnpingLogTable/Service.hs (postLogTableSourceSchemaUpgradeR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned groups; `Permission Denied` comes back as HTTP 500.

## Error Handling

- **Event column** — refused: a log table must keep its trigger. Repoint it with `onping-logtable-column-set` or add another event column first.
- **Column referenced by a stored filter** — refused without `--drop-filters`.
- **Read-back mismatch** — exit 1 listing differences; the backup is on disk.
- **Permission Denied / token expired** — exit 1 with a hint.
