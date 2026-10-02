---
name: onping-event-table-list
description: List OnPing event tables from dashboard JSON — dashboard, panel, widget title, and UUID — and find every table that binds a given PID (--references-pid). Read-only. Use to get from a widget title to an event-table UUID, or to audit which tables read a deleted PID.
allowed-tools: Bash(uv run *)
---

# OnPing Event Table — List

Find event tables by walking dashboard JSON. No OnPing route lists event tables,
and a table's display title lives only in its dashboard, so this is the way from
"Recent Events on that panel" to a UUID that `onping-event-table-get`,
`-export`, and `-fetch` accept.

`--references-pid N` adds the reverse lookup that no route provides: it reads
each listed table's configuration and keeps the tables that bind PID N.

> **Read-only** — no `--yes` gate.

> **The dashboard key comes from the browser URL.** In
> `/v3/dashboards/o6a20…`, the `o…` part is the key.

> **A wrong key does not fail on its own.** `GET /data/dashboard` silently
> returns your DEFAULT dashboard when it cannot parse the key. The script first
> checks the key against `GET /data/dashboard/values`, and refuses a key that is
> not there.

> **Sub-panels are walked.** OnPing's search (`onping-search`, query
> `is:event-table`) misses event tables in sub-panels, because its indexers scan
> only top-level panels. This skill walks the whole panel tree.

## Related Skills

- **onping-login** — get an access token
- **onping-event-table-get** — read one table's bindings; `--pid` for one known UUID
- **onping-event-table-fetch** — check whether a table still renders
- **onping-pid-locate** — confirm whether a PID still exists
- **onping-search** — a quick title search, with the sub-panel caveat above

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SCRIPT=~/.claude/skills/onping-event-table-list/scripts/list_event_tables.py

# Every event table on one dashboard
uv run $SCRIPT "$ACCESS_TOKEN" --dashboard <o-key>

# Two widgets by title
uv run $SCRIPT "$ACCESS_TOKEN" --dashboard <o-key> --title "Recent Events" --title "Status Log"

# Which tables on this dashboard read PID 500001, and in which column?
uv run $SCRIPT "$ACCESS_TOKEN" --dashboard <o-key> --references-pid 500001

# Across every dashboard you can see (large: reads them all)
uv run $SCRIPT "$ACCESS_TOKEN" --all --title "Recent Events" --json
```

## Flags

- `--dashboard KEY` (repeatable) — read these dashboards. Mutually exclusive with `--all`.
- `--all` — read every dashboard in your owned and member groups (`GET /data/dashboard/list`, unpaginated). A title like "Recent Events" can appear on hundreds of dashboards, so filter.
- `--title TEXT` (repeatable) — keep tables whose title equals `TEXT`, ignoring case.
- `--references-pid N` — read each listed table's config and keep the ones that bind PID N, in a column or in a `DynamicMaxEvents` row count. Each kept table names the column. A VPID with the same number is noted, never matched.
- `--json` — emit the records as JSON.

## Output

One record per table: title, UUID, dashboard key and name, and panel name. With `--references-pid`, a headline gives the count, and each table is marked `REFERENCED` with its binding, or `UNCHECKED` with the error.

## Exit codes

- `0` — the listing finished. With `--references-pid`, every table was checked, whether or not any matched.
- `1` — a dashboard read failed, or at least one table is `UNCHECKED`. **An unchecked table is never reported as a non-match.**

## API Reference

| Endpoint | Method | Use |
|----------|--------|-----|
| `/data/dashboard/values` | GET | validate a `--dashboard` key |
| `/data/dashboard?dashId=<o-key>` | GET | one dashboard |
| `/data/dashboard/list` | GET | `--all` |
| `/event/table/config` | POST | `--references-pid`, once per table |

Handlers: `onping/Handler/JSON/Dashboard.hs` and `onping/Handler/EventTable/Service.hs (postQueryEventTableConfigR)`. Routes and notes: `_event_table_routes/routes.py`.

## Permissions

The dashboard reads cover your owned and member groups. The config read is open to any authenticated user, with no per-table check.
