---
name: onping-datatable-cell-set
description: Adjust the PIDs in an OnPing Lumberjack data table — set one cell (--row + --column to --pid/--vpid/--text/--clear) or rewrite every cell pointing at a PID or VPID (--replace-pid OLD NEW) — through POST /datatable/<LJ>/source/content/update. MUTATING — previews by default, posts only with --yes, backs up the edited rows, and verifies the read-back.
allowed-tools: Bash(uv run *)
---

# OnPing Data Table — Cell Set

> **⚠️ WARNING: this skill changes live data.** It rewrites cells in a live
> data table. It previews every changed cell (old → new) by default and
> changes nothing until you pass `--yes`; `--dry-run` also previews and wins
> over `--yes`. With `--yes` it first writes a backup of the edited rows'
> pre-edit values, in the same shape the update route takes, so a restore is
> one more update.

A data-table cell stores a pointer as text: `"1234"` is PID 1234, `"1234 VPID"`
is VPID 1234. A Text column stores literal text and never resolves a PID.

## Related Skills

- **onping-datatable-fetch** — find rows and the cells pointing at a PID
- **onping-datatable-column-add** — make a column to fill
- **onping-logtable-column-set** — the log-table equivalent of repointing

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-datatable-cell-set/scripts/set_datatable_cells.py

uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --row 12 --column "Casing Pressure" --pid 500002
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --row 12 --column "Lease" --text "North 4"
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --replace-pid 500001 500002            # every column
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --replace-vpid 70 71 --column 3      # one column
# add --yes to apply
```

## Flags

- `--row ID --column REF` with one of `--pid N`, `--vpid N`, `--text T`, `--clear` — set one cell.
- `--replace-pid OLD NEW` / `--replace-vpid OLD NEW` — rewrite every cell pointing at OLD; `--column REF` limits it to one column.
- `--yes`, `--dry-run`, `--backup PATH` — default backup: `./datatable-cells-<LJ>-<uuid>-<UTC>.backup.json`.

## Output

One line per changed cell (`row, position, column: old -> new`), the number of
rows to be sent, and on `--yes` the backup path, the POST result, and the
read-back check over every row.

## How it works

The update route needs each changed row's **full** value list in position
order, so the script reads every row (stored pointers, not rendered values),
edits only the requested cells, and sends just the changed rows, sorted by
`tableRowId` (the server pairs the rows it reads back with the rows sent).
The table regenerates after each write.

## Refusals

- A PID/VPID into a Text column, or `--text` into a pointer column.
- A table with an `Invalid`-selector column: the update route counts that column in its positions but the query omits it, so a row cannot be rebuilt safely.
- `--replace-*` that matches no cell.

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/datatable/<LJ>/source/content/query/v3` | POST (read-only) | TableSource, no pagination | rows + pointers |
| `/datatable/<LJ>/source/content/update` | POST | `["<uuid>", [{"tableRowId": n, "tableRowValues": [...]}]]` | `[]` |

Handler: `onping/Handler/OnpingDataTable/Service.hs (postDataTableSourceContentUpdateR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned groups for the write; `Permission Denied` comes back as HTTP 500.

## Error Handling

- **HTTP 503** — a regeneration holds the table lock; wait and re-run.
- **Read-back mismatch** — exit 1 listing differences; the backup is on disk.
- **Permission Denied / token expired** — exit 1 with a hint.
