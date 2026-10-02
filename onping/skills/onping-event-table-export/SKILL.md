---
name: onping-event-table-export
description: Export an OnPing event table as Dhall via GET /event/table/export/<file>?eventTableUUID=<uuid>. Read-only. Backs up a table, or gives a starting point for the event-table-import template.
allowed-tools: Bash(uv run *)
---

# OnPing Event Table — Export

Download one event table's `EventTableConfiguration` as Dhall, by its UUID. The
output is the shape that `POST /event/table/import` and the `event-table-import`
template use. For JSON and a bindings view, use `onping-event-table-get`.

> **Read-only** — no `--yes` gate.

> **The UUID goes in the query parameter.** The route's path segment only names
> the downloaded file, and the server ignores it. The script handles this.

> **The export carries no title.** A table's display title lives in its
> dashboard, so find the UUID with `onping-event-table-list`.

## Related Skills

- **onping-login** — get an access token
- **onping-event-table-list** — find a table's UUID from its dashboard and title
- **onping-event-table-get** — the same table as JSON, with `--bindings` and `--pid`
- **event-table-import** — the Dhall template for building a new table

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-event-table-export/scripts/export_event_table.py \
  "$ACCESS_TOKEN" <uuid> --output table.dhall
```

## Flags

- `--output PATH` (required) — the Dhall file to write. The script writes through a temporary file and replaces `PATH` only after a successful, non-HTML response, so a failed export never replaces an existing file.

## Output

A Dhall `EventTableConfiguration`. Keys are records: `eventColumnKey = { type = "PID", value = +500001 }`.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/event/table/export/<file>.dhall?eventTableUUID=<uuid>` | GET | Dhall; `Content-Type: application/vnd.plow.event-table+dhall` |

Handler: `onping/Handler/EventTable/Service.hs (getEventTableExportR)`. Routes and notes: `_event_table_routes/routes.py`.

## Permissions

Any authenticated OnPing user can export any event table by UUID. No handler checks access to the table, its dashboard, or its PIDs.

## Error Handling

- **Unknown UUID or missing parameter** — HTTP 500 with a bare JSON string (`Failed to lookup EventTableConfiguration by UUID`); exit 1, file untouched.
- **Token expired** — a `303 → /auth/login` redirect or an HTML body; exit 1, file untouched.
