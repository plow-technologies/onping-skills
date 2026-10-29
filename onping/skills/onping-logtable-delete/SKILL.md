---
name: onping-logtable-delete
description: Delete an OnPing log table (soft delete — it stops recording and leaves the list; no undelete route) through POST /logtable/<LJ>/source/delete. MUTATING — previews the table and its row count by default, posts only with --yes, backs up the full LogTableSource first, and verifies it is gone from the list.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — Delete

> **⚠️ WARNING: this skill changes live data, and there is no undo route.**
> The table stops recording and disappears from every list. The server marks
> it deleted rather than erasing it, but no route brings it back. It previews
> by default and changes nothing until you pass `--yes`; `--dry-run` also
> previews and wins over `--yes`. With `--yes` it first writes the whole
> LogTableSource (every schema version) to a backup, enough to rebuild the
> definition with `onping-logtable-create` and the column skills. Recorded
> rows are not in the backup.

## Related Skills

- **onping-logtable-list** — find the table
- **onping-logtable-fetch** — check its rows before deleting
- **onping-logtable-create** — also names orphaned version-0 tables to delete

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-logtable-delete/scripts/delete_logtable.py "$ACCESS_TOKEN" <LJ> <table-uuid>
uv run ~/.claude/skills/onping-logtable-delete/scripts/delete_logtable.py "$ACCESS_TOKEN" <LJ> <table-uuid> --yes
```

## Flags

- `--yes`, `--dry-run`, `--backup PATH` — default backup: `./logtable-<LJ>-<uuid>-<UTC>.backup.json`.

## Output

The table's name, versions, current-version row count, and columns; on `--yes`
the backup path, `POST source/delete: OK`, and `Verified: the table no longer
appears in source/list.`

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/logtable/<LJ>/source/list` | GET | — | `[LogTableSource]` |
| `/logtable/<LJ>/source/content/query/v2` | POST (read-only) | one-row query | the row count for the preview |
| `/logtable/<LJ>/source/delete` | POST | `"<uuid>"` (a JSON string) | `[]` |

Handler: `onping/Handler/OnpingLogTable/Service.hs (postLogTableSourceDeleteR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned groups; `Permission Denied` comes back as HTTP 500.

## Error Handling

- **UUID not on that LJ** — exit 1; nothing posted.
- **Still listed after the delete** — exit 1; the backup is on disk.
- **Permission Denied / token expired** — exit 1 with a hint.
