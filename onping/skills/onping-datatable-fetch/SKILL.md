---
name: onping-datatable-fetch
description: Read an OnPing Lumberjack data table's rows with both the rendered value and the stored PID/VPID pointer of every cell; print one row as a unit (--row), or find every cell pointing at a PID or VPID (--pid / --vpid). Read-only. Use to see which PIDs a data-table row names before building or checking a log table.
allowed-tools: Bash(uv run *)
---

# OnPing Data Table — Fetch

Read a data table's rows. Every cell has two faces: the **pointer** stored in
the table (`"1234"` = PID 1234, `"1234 VPID"` = VPID 1234, or literal text in a
Text column) and the **value** the server renders through the column's
selector. This skill shows both.

> **Read-only** — no `--yes` gate. The query route is a POST, but it only reads.

> **Ignores the stored view.** The script clears the table's stored filters and
> order, so a saved filter never hides a row. `--row` and `--pid`/`--vpid` read
> every row in one request and check it against the server's count.

## Related Skills

- **onping-datatable-get** — the columns
- **onping-datatable-cell-set** — change a cell's PID
- **onping-logtable-list --references-pid** — which log tables record a PID

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-datatable-fetch/scripts/fetch_datatable.py "$ACCESS_TOKEN" <LJ> <table-uuid> --limit 5
uv run ~/.claude/skills/onping-datatable-fetch/scripts/fetch_datatable.py "$ACCESS_TOKEN" <LJ> <table-uuid> --row 12
uv run ~/.claude/skills/onping-datatable-fetch/scripts/fetch_datatable.py "$ACCESS_TOKEN" <LJ> <table-uuid> --pid 500001
```

## Flags

- `--row ID` — print one row (`tableRowId`) cell by cell: position, column, selector, pointer, value.
- `--pid N` / `--vpid N` — list every cell pointing at it.
- `--limit N` (default 20), `--offset N` — which rows the default view prints.
- `--json` — JSON (`rowId`, `values`, `pointers`, and per-cell detail).

## Output

The total row count, then rows. A row's cells are joined on `tableRowId`
between the content and pointer lists — the server returns the pointer list in
no fixed order.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/datatable/<LJ>/source/list` | GET | `[TableSource]` |
| `/datatable/<LJ>/source/content/query/v3` | POST (read-only) | `{queryResponseContent, queryResponsePointers, queryResponseCount}` |

Handler: `onping/Handler/OnpingDataTable/Service.hs (postDataTableSourceContentQueryAndCountAndPointersR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned-or-member groups.

## Error Handling

- **Row count disagrees with `queryResponseCount`** (`--row`, `--pid`, `--vpid`) — exit 1 rather than answer from a partial table.
- **`--row` not found** — exit 1.
- **LJ has no routing / token expired** — exit 1 with a hint.
