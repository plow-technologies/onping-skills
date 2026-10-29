---
name: onping-datatable-list
description: List OnPing Lumberjack data tables (the /datatable sources) on one LJ or every LJ — LJ, UUID, column count, group, name — and find every table with a cell pointing at a PID or VPID (--references-pid / --references-vpid). Read-only. Start here to get a data table's UUID; not the ctable widget.
allowed-tools: Bash(uv run *)
---

# OnPing Data Table — List

List the Lumberjack data tables you can see. A data table is a grid whose
columns each hold a *selector* (Result, Unit, Text, …) and whose cells each
hold a PID or VPID pointer — so one row usually describes one asset, and often
one log table's worth of PIDs. This is the Lumberjack `/datatable` source, not
the dashboard ctable widget.

> **Read-only** — no `--yes` gate.

## Related Skills

- **onping-login** — get an access token
- **onping-datatable-get** — one table's columns and settings
- **onping-datatable-fetch** — one table's rows and the PID in every cell
- **onping-logtable-list** — the log-table equivalent

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

uv run ~/.claude/skills/onping-datatable-list/scripts/list_datatables.py "$ACCESS_TOKEN" <LJ>
uv run ~/.claude/skills/onping-datatable-list/scripts/list_datatables.py "$ACCESS_TOKEN" --all --name pump
uv run ~/.claude/skills/onping-datatable-list/scripts/list_datatables.py "$ACCESS_TOKEN" --all --references-pid 500001
```

## Flags

- `<LJ>` or `--all` — one Lumberjack serial, or every routed LJ (`/datatable/router/source/all`; slow).
- `--name TEXT` — keep tables whose name contains TEXT, case-insensitive. Repeatable (any match).
- `--references-pid N` / `--references-vpid N` — keep tables with at least one cell pointing at it, and list those cells. This reads every row of every listed table, so narrow with `<LJ>` or `--name` first.
- `--json` — JSON records instead of the table.

## Output

One line per table: LJ, UUID, column count, group, name. With `--references-*`,
each match is `REFERENCED` with its row, column, and position. A table whose
rows could not be read is reported `UNCHECKED` and the script exits 1, so "no
match" is never silently confused with "could not look".

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/datatable/<LJ>/source/list` | GET | `[TableSource]` |
| `/datatable/router/source/all` | GET | `[TableSource]` across every routed LJ |
| `/datatable/<LJ>/source/content/query/v3` | POST (read-only) | rows, pointers, count (only with `--references-*`) |

Handlers: `onping/Handler/OnpingDataTable/Service.hs (getDataTableSourceListR, getAllDataTableSourcesR, postDataTableSourceContentQueryAndCountAndPointersR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

The server returns only tables whose group is one of your owned-or-member
groups. A table you cannot see is simply absent.

## Error Handling

- **LJ has no routing** — HTTP 404 `Routing index could not be found.`; exit 1.
- **Token expired** — 401, a redirect to `/auth/login`, or an HTML page; exit 1 with a re-login hint.
- **A table's rows cannot be read** (`--references-*`) — reported `UNCHECKED`; exit 1 after the list.
