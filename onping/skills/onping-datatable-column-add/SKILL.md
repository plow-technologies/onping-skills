---
name: onping-datatable-column-add
description: Add an empty column (name + selector, optional position) to an OnPing Lumberjack data table through POST /datatable/<LJ>/source/metadata/update. MUTATING — previews by default, posts only with --yes, backs up the TableSource first, and verifies the read-back. Fill the new cells with onping-datatable-cell-set.
allowed-tools: Bash(uv run *)
---

# OnPing Data Table — Column Add

> **⚠️ WARNING: this skill changes live data.** It adds a column to a live
> data table. It previews by default and changes nothing until you pass
> `--yes`; `--dry-run` also previews and wins over `--yes`. With `--yes` it
> writes a JSON backup of the TableSource before posting. Removing the column
> again is `onping-datatable-column-delete`.

A data-table column holds only a selector (what each cell shows for its PID:
Result, Unit, Text, …). The new column's cells start empty in every row; set
them with `onping-datatable-cell-set`.

## Related Skills

- **onping-datatable-get** — positions and existing names
- **onping-datatable-cell-set** — fill the new column's cells
- **onping-datatable-column-delete** — the reverse

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# Preview:
uv run ~/.claude/skills/onping-datatable-column-add/scripts/add_datatable_column.py \
  "$ACCESS_TOKEN" <LJ> <table-uuid> --name "Tubing Pressure" --selector Result --at 4
# Apply:
uv run ~/.claude/skills/onping-datatable-column-add/scripts/add_datatable_column.py \
  "$ACCESS_TOKEN" <LJ> <table-uuid> --name "Tubing Pressure" --selector Result --at 4 --yes
```

## Flags

- `--name NAME` (required) — must not match an existing column name.
- `--selector S` — `Result` (default), `Text`, `Unit`, `Description`, `LastUpdateDateTime`, … (short or full `…TagSelector` names). `Invalid` is refused.
- `--at POS` — stored position; columns at POS and later shift up by one. Default: after the last column.
- `--yes`, `--dry-run`, `--backup PATH` — see the warning above. Default backup: `./datatable-<LJ>-<uuid>-<UTC>.backup.json`.

## Output

BEFORE and AFTER grids (`<-- new (empty)` marks the column), then on `--yes`:
the backup path, `POST metadata/update: OK`, and the read-back result.

## How it works

The script sends the stored TableSource with one extra column whose
`columnHeaderNewOrDuplicate` is the nil UUID; the server turns that into
`ALTER TABLE … ADD COLUMN`. It re-reads the table and compares column ids,
names, selectors, order, hidden columns, and filters (the server may clear
`NewOrDuplicate` and renumber positions; those are tolerated).

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/datatable/<LJ>/source/list` | GET | — | `[TableSource]` |
| `/datatable/<LJ>/source/metadata/update` | POST | the full TableSource | `[]` |

Handler: `onping/Handler/OnpingDataTable/Service.hs (postDataTableSourceMetadataUpdateR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Writes need the table's group in your **owned** groups. Otherwise the server
answers `Permission Denied` with HTTP 500.

## Error Handling

- **Duplicate name / bad selector / bad `--at`** — refused before any request is posted; exit 1.
- **Permission Denied (HTTP 500)** — exit 1 with an owned-groups hint.
- **Read-back mismatch** — exit 1 listing each difference; the backup is on disk.
- **Token expired** — exit 1 with a re-login hint.
