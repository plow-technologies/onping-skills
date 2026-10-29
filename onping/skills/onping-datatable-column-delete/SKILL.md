---
name: onping-datatable-column-delete
description: Delete a column from an OnPing Lumberjack data table (DROP COLUMN — its cells are destroyed) through POST /datatable/<LJ>/source/metadata/update. MUTATING — previews the data loss by default, posts only with --yes, backs up the TableSource AND every row's pointers first, and verifies the read-back.
allowed-tools: Bash(uv run *)
---

# OnPing Data Table — Column Delete

> **⚠️ WARNING: this skill destroys data and cannot be undone by the server.**
> The server drops the column and every row's cell in it. The preview counts
> the filled cells that will be lost. It changes nothing until you pass
> `--yes`; `--dry-run` also previews and wins over `--yes`. With `--yes` it
> first writes a backup holding the TableSource and every row's pointer cells,
> so the column can be re-added (`onping-datatable-column-add`) and refilled
> (`onping-datatable-cell-set`) by hand.

## Related Skills

- **onping-datatable-get** — find the column
- **onping-datatable-fetch** — see what the column holds
- **onping-datatable-column-add** — the reverse

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-datatable-column-delete/scripts/delete_datatable_column.py \
  "$ACCESS_TOKEN" <LJ> <table-uuid> --column "Old Pressure"          # preview
uv run ~/.claude/skills/onping-datatable-column-delete/scripts/delete_datatable_column.py \
  "$ACCESS_TOKEN" <LJ> <table-uuid> --column "Old Pressure" --yes    # apply
```

## Flags

- `--column REF` (required) — position, column UUID, or name (exact, then case-insensitive).
- `--drop-filters` — a stored filter rule on the column blocks the delete; this removes those rules (and any filter group left empty) too.
- `--yes`, `--dry-run`, `--backup PATH` — default backup: `./datatable-<LJ>-<uuid>-<UTC>.backup.json`, shaped `{"tableSource": …, "rows": [{"tableRowId", "pointers"}]}`.

## Output

BEFORE/AFTER grids, `DATA LOSS: N of M row(s) have a cell in this column`, and
on `--yes` the backup path, the POST result, and the read-back check.

## How it works

The column is removed from the TableSource everywhere it is named: columns,
positions (re-packed from the lowest position), order, hidden columns, custom
widths, and the frozen column. A stored column absent from the posted body is
what the server turns into `DROP COLUMN`.

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/datatable/<LJ>/source/list` | GET | — | `[TableSource]` |
| `/datatable/<LJ>/source/content/query/v3` | POST (read-only) | TableSource, no pagination | every row (for the backup and the loss count) |
| `/datatable/<LJ>/source/metadata/update` | POST | the TableSource without the column | `[]` |

Handler: `onping/Handler/OnpingDataTable/Service.hs (postDataTableSourceMetadataUpdateR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned groups for the write; `Permission Denied` comes back as HTTP 500.

## Error Handling

- **Column referenced by a stored filter** — refused without `--drop-filters`; exit 1.
- **Ambiguous or unknown column** — exit 1; use the position or UUID.
- **Read-back mismatch** — exit 1 listing differences; the backup is on disk.
- **Permission Denied / token expired** — exit 1 with a hint.
