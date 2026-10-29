---
name: onping-datatable-get
description: Read one OnPing Lumberjack data table's TableSource — every column's position, UUID, selector, hidden flag, and name, plus pagination, order, and stored filters — or the raw JSON (--json / --output, also the backup format). Read-only.
allowed-tools: Bash(uv run *)
---

# OnPing Data Table — Get

Show one data table's definition: its columns in position order and its stored
view settings. Use it before any column edit to see positions and UUIDs, and
`--output` to keep a JSON copy.

> **Read-only** — no `--yes` gate.

> **There is no get-one route.** The script filters `GET /datatable/<LJ>/source/list` by UUID.

## Related Skills

- **onping-datatable-list** — find the table's LJ and UUID
- **onping-datatable-fetch** — the rows and the PID in each cell
- **onping-datatable-column-add** / **-column-delete** / **-cell-set** — edits

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-datatable-get/scripts/get_datatable.py "$ACCESS_TOKEN" <LJ> <table-uuid>
uv run ~/.claude/skills/onping-datatable-get/scripts/get_datatable.py "$ACCESS_TOKEN" <LJ> <table-uuid> --output table.json
```

## Flags

- `--json` — print the raw `TableSource`.
- `--output PATH` — write the raw `TableSource` to PATH and print the path.

## Output

A header (name, UUID, LJ, group, pagination, order, filter count) and a grid:
`pos  uuid  selector  hidden  name`. A column with selector `Invalid` is shown
but holds no data; such a table cannot be edited with `onping-datatable-cell-set`.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/datatable/<LJ>/source/list` | GET | `[TableSource]`; the script keeps the one matching the UUID |

Handler: `onping/Handler/OnpingDataTable/Service.hs (getDataTableSourceListR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned-or-member groups. A table outside your groups reads as "not found".

## Error Handling

- **UUID not on that LJ** — exit 1 naming the LJ and UUID.
- **LJ has no routing** — HTTP 404 `Routing index could not be found.`; exit 1.
- **Token expired** — 401, a redirect to `/auth/login`, or an HTML page; exit 1.
