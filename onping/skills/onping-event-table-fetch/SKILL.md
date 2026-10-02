---
name: onping-event-table-fetch
description: Fetch the rows an OnPing event table renders at a given time via POST /event/table/fetch. Read-only. Confirms whether a table renders, and names the dead PID when one stops it.
allowed-tools: Bash(uv run *)
---

# OnPing Event Table — Fetch

Render an event table's rows at a given time, the way the dashboard does. Use it
to confirm whether a table works. When a table shows nothing on its dashboard,
this is the fastest way to find out why.

> **Read-only** — no `--yes` gate.

> **One dead key breaks the whole table.** If any column reads a PID or VPID
> that OnPing cannot look up — a deleted PID, for example — the fetch fails with
> HTTP 500 `failed to lookup TagInfo for key: KeyPID N`. The table does not show
> stale or zero values. It renders nothing. The script prints the key as the
> likely cause.

> **OnPing names only the first dead key.** A table can bind more than one.
> After a failure, list every bound key with `onping-event-table-get --bindings`
> and check them all with `onping-pid-locate`.

## Related Skills

- **onping-login** — get an access token
- **onping-event-table-list** — find a table's UUID
- **onping-event-table-get** — list every key the table reads
- **onping-pid-locate** — confirm whether a PID still exists. It cannot tell a deleted PID from one you cannot see, so compare it with a neighbouring PID on the same location.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SCRIPT=~/.claude/skills/onping-event-table-fetch/scripts/fetch_event_table.py
uv run $SCRIPT "$ACCESS_TOKEN" <uuid>                          # rows as of now
uv run $SCRIPT "$ACCESS_TOKEN" <uuid> --at 2026-10-01T12:00:00Z --pretty
```

## Flags

- `--at TIME` — the fetch time, ISO-8601 with a zone. The default is now, in UTC.
- `--pretty` — indented JSON.

## Output

The rendered rows as JSON on stdout: each row's `eventTableRowIndex` and its `eventTableRowCells`. A row count goes to stderr. Rows are the last `maxEvents` history points of the trigger PID before the fetch time.

## API Reference

| Endpoint | Method | Body |
|----------|--------|------|
| `/event/table/fetch` | POST | `{"fetchEventTableUUID": {"unEventTableUUID": "<uuid>"}, "fetchTime": "<ISO-8601 UTC>"}` |

Handler: `onping/Handler/EventTable/Service.hs (postFetchEventTableR)`. The dead-key failure comes from `makeCell` in the onping-core event-table data source. Routes and notes: `_event_table_routes/routes.py`.

## Permissions

Any authenticated OnPing user can fetch any event table by UUID.

## Error Handling

- **Dead key** — HTTP 500 naming the key; the script prints `TABLE DOES NOT RENDER`, the key, and the next steps, then exits 1.
- **Unknown UUID or other failure** — the status and body; exit 1.
- **Token expired** — a `303 → /auth/login` redirect or an HTML body; exit 1.
