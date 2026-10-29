---
name: onping-logtable-list
description: List OnPing log tables on one LJ or every LJ — LJ, UUID, schema version, column count, event (trigger) PID, name — and find every log table with a column recording a PID or VPID (--references-pid / --references-vpid). Read-only. Start here to get a log table's UUID or to check whether a data-table row's PIDs are already logged.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — List

List the Lumberjack log tables you can see. A log table records one row each
time its **event (trigger) PID** updates, snapshotting the value of every
other column's PID at that moment.

> **Read-only** — no `--yes` gate.

> **`--all` hides version-0 tables and is slow.** The all-LJ route returns only
> sources that have a schema (version > 0), so a table just made by
> `source/create` with no version 1 shows only on its LJ's list. On 2026-10-09
> the route took about a minute and returned 30+ MB; the script waits up to 300 s.

## Related Skills

- **onping-login** — get an access token
- **onping-logtable-get** — one table's columns
- **onping-logtable-fetch** — its rows, and whether it is still recording
- **onping-datatable-list** — the data-table equivalent

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-logtable-list/scripts/list_logtables.py "$ACCESS_TOKEN" <LJ>
uv run ~/.claude/skills/onping-logtable-list/scripts/list_logtables.py "$ACCESS_TOKEN" <LJ> --references-pid 500001
uv run ~/.claude/skills/onping-logtable-list/scripts/list_logtables.py "$ACCESS_TOKEN" --all --name "bay"
```

## Flags

- `<LJ>` or `--all` — one Lumberjack serial, or every routed LJ.
- `--name TEXT` — keep names containing TEXT, case-insensitive. Repeatable.
- `--references-pid N` / `--references-vpid N` — keep tables whose **current** schema has a column keyed by it, and name those columns (`(event)` marks the trigger). No extra requests: the list already carries every schema.
- `--json` — JSON records.

## Output

`LJ  uuid  ver  cols  event PID  name`, one line per table, and with
`--references-*` a `REFERENCED` line per table naming the matching columns.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/logtable/<LJ>/source/list` | GET | `[LogTableSource]`, any version, not deleted |
| `/logtable/router/source/all` | GET | `[LogTableSource]`, version > 0, every routed LJ |

Handlers: `onping/Handler/OnpingLogTable/Service.hs (getLogTableSourceListR, getAllLogTableSourcesR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned-or-member groups; other tables are simply absent.

## Error Handling

- **LJ has no routing** — HTTP 404 `Routing index could not be found.`; exit 1.
- **Timeout on `--all`** — exit 1; query the LJs you need one at a time.
- **Token expired** — exit 1 with a re-login hint.
