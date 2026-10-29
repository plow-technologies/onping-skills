---
name: onping-logtable-column-set
description: Repoint an OnPing log-table column to another PID or VPID, change its selector, and/or rename it — keeping its UUID — as a new schema version through POST /logtable/<LJ>/source/schema/upgrade. Repointing the event column moves the trigger (PID only). MUTATING — previews by default, posts only with --yes, backs up the LogTableSource, verifies the read-back.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — Column Set

> **⚠️ WARNING: this skill changes live data.** It changes what a live log
> table records. It previews BEFORE/AFTER by default and changes nothing until
> you pass `--yes`; `--dry-run` also previews and wins over `--yes`. With
> `--yes` it first writes a JSON backup of the whole LogTableSource.

> **⚠️ Every column edit creates a new, EMPTY schema version.** A log-table
> edit is `schema/upgrade` to version v+1, and the server starts a new table
> for it. Rows recorded under earlier versions are not migrated; read them with
> `onping-logtable-fetch --version N`. Column UUIDs are kept across versions.
> Each run adds one version, so plan a set of edits before applying them.

> **Renames version too.** The OnPing UI renames a column in place through
> `metadata/update`; this skill sends every column edit through
> `schema/upgrade` so there is one verified write path. A rename therefore
> also starts an empty version.

## Related Skills

- **onping-logtable-get** — find the column and its current key
- **onping-datatable-cell-set** — the data-table equivalent of repointing
- **onping-logtable-column-add** / **-column-delete** — the other column edits

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-logtable-column-set/scripts/set_logtable_column.py
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --column-pid 500001 --pid 500002       # repoint
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --column 3 --selector Unit --name units
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --column 0 --pid 500003 --yes          # move the trigger
```

## Flags

- Which column — one of `--column REF` (position, UUID, or name), `--column-pid N`, `--column-vpid N`.
- What to change — any of `--pid N` / `--vpid N` (the new key), `--selector S`, `--name NAME`.
- `--yes`, `--dry-run`, `--backup PATH` — default backup: `./logtable-<LJ>-<uuid>-<UTC>.backup.json`.

## Output

BEFORE/AFTER grids with `<-- changed` on the column, a `NOTE` when the
trigger moves, the empty-version warning, and on `--yes` the backup path, the
POST result, and the read-back check.

## Rules

- The event column's key must be a PID; changing it also sets `schemaHeaderEventSource`.
- The event column keeps `LastUpdateDateTime`; another selector is refused.
- `Text` and `Invalid` selectors are not allowed in a log table.
- A new name must not match another column.

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/logtable/<LJ>/source/list` | GET | — | `[LogTableSource]` |
| `/logtable/<LJ>/source/schema/upgrade` | POST | the source at version v+1, new schema first | the stored source |

Handler: `onping/Handler/OnpingLogTable/Service.hs (postLogTableSourceSchemaUpgradeR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned groups; `Permission Denied` comes back as HTTP 500.

## Error Handling

- **Rule violations** (above) — refused before any request is posted; exit 1.
- **Read-back mismatch** — exit 1 listing differences; the backup is on disk.
- **Permission Denied / token expired** — exit 1 with a hint.
