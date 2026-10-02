---
name: onping-event-table-get
description: Read an OnPing event table's configuration as JSON via POST /event/table/config. Read-only. Shows which PID or VPID each column reads (--bindings) and answers whether a given PID is bound (--pid).
allowed-tools: Bash(uv run *)
---

# OnPing Event Table — Get

Read one event table's `EventTableConfiguration` as JSON, by its UUID. Use
`--bindings` to see every key the table reads, and `--pid N` to ask whether a
PID is bound and where. For a Dhall copy, use `onping-event-table-export`.

> **Read-only** — no `--yes` gate.

> **The UUID is not in the browser URL.** A dashboard holds only a pointer to
> the table, and the widget title lives in the dashboard. Find the UUID with
> `onping-event-table-list --dashboard <key> --title "<widget title>"`.

> **The trigger column is found by index, not position.** The trigger is the
> column whose `eventColumnIndex` equals `eventTableEventColumn`. Production
> tables put it at index 0, with columns 0 and 1 reading the same PID: column 0
> shows the event's date and time, and column 1 shows its value.

> **A deleted PID still shows here.** The config read never validates keys. To
> find out whether a bound PID still exists, run `onping-pid-locate` on it, or
> run `onping-event-table-fetch`, which fails when any bound key is dead.

## Related Skills

- **onping-login** — get an access token
- **onping-event-table-list** — find a table's UUID from its dashboard and title, or find every table that binds a PID
- **onping-event-table-fetch** — render the table's rows, which fails and names the key when a bound PID is dead
- **onping-event-table-export** — the same table as Dhall
- **onping-pid-locate** — confirm whether a bound PID still exists

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SCRIPT=~/.claude/skills/onping-event-table-get/scripts/get_event_table.py
uv run $SCRIPT "$ACCESS_TOKEN" <uuid>                  # raw JSON
uv run $SCRIPT "$ACCESS_TOKEN" <uuid> --bindings       # one row per bound key
uv run $SCRIPT "$ACCESS_TOKEN" <uuid> --pid 500001     # is PID 500001 bound?
uv run $SCRIPT "$ACCESS_TOKEN" <uuid> --output table.json --pretty
```

## Flags

- `--bindings` — print the trigger index, the max-events setting, and one row per column: index, key type, key value, trigger flag, and name. A `DynamicMaxEvents` row count reads a key too, and it gets its own row.
- `--pid N` — print `REFERENCED: PID N` with each column (or the max-events setting) that reads it, or `NOT REFERENCED: PID N`. **Both answers exit 0.** A VPID with the same number is a different parameter, so it is reported as a note, never as a match.
- `--output PATH` — write the JSON to this file. Written only after a successful response.
- `--pretty` — indented, sorted-key JSON.

## Output

Raw JSON by default. With `--bindings` or `--pid`, the answer replaces the JSON on stdout. A soft-deleted table prints a note to stderr; OnPing returns deleted tables like live ones, with `eventTableDeleted: true`.

Key encoding in the JSON: a bare integer is a PID (`500001`), and an object carries its own type (`{"keyType": "VPID", "keyValue": 100001}`).

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/event/table/config` | POST | `{"unEventTableUUID": "<uuid>"}` | JSON `EventTableConfiguration` |

Handler: `onping/Handler/EventTable/Service.hs (postQueryEventTableConfigR)`. Routes and notes: `_event_table_routes/routes.py`.

## Permissions

Any authenticated OnPing user can read any event table by UUID. No handler checks access to the table, its dashboard, or its PIDs. This skill adds no exposure beyond the OnPing UI.

## Error Handling

- **Unknown UUID** — HTTP 404 `Failed to lookup EventTableConfiguration by UUID`; exit 1, no file written.
- **Token expired** — a `303 → /auth/login` redirect or an HTML body; exit 1, naming the token as the likely cause.
- A non-zero exit means only that the question went unanswered. It never means "not referenced".
