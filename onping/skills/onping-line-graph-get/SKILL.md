---
name: onping-line-graph-get
description: Read an OnPing line-graph widget as JSON via GET /content/widgets/line-graph/widget/{id}. Read-only. Inspects a widget's title, timePeriod, yAxes, eventParameters, and pids without a Dhall round-trip.
allowed-tools: Bash(uv run *)
---

# OnPing Line Graph Widget — Get

Read a line-graph widget's raw JSON. This is the fast inspection path — a single
`GET /content/widgets/line-graph/widget/{id}` returns the whole widget as
`application/json`. For a Dhall backup (usable as `onping-line-graph-import`
input), use `onping-line-graph-export`.

> **Read-only** — no `--yes` gate.

> **Widget id is a Mongo-style `o…` id** (e.g. `o00000000000000000000002d`),
> assigned server-side by `POST /content/widgets/line-graph/config`. Discover
> one via the containing dashboard (`/v3/dashboards/{id}` URL bar) or the HMI
> panel config that references it.

> **Wire-level `pid` is a bare integer.** The Dhall exported schema uses
> `pid = Some { type = "PID", value = +12345 }`; the JSON returned here uses
> `"pid": 12345`. OnPing flattens the `{type, value}` record on JSON
> serialization. `type` (PID vs VPID) is lost in JSON — use `-export` if you
> need the full type-tagged form.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-line-graph-export** — Dhall variant of the same widget (round-trip with `-import`)
- **onping-line-graph-import-data** — Remap pids on this widget after inspecting them
- **onping-line-graph-create** — Mint a fresh widget id

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Compact JSON to stdout
uv run ~/.claude/skills/onping-line-graph-get/scripts/get_line_graph.py "$ACCESS_TOKEN" <widget-id>
# Pretty-print (2-space indent, sorted keys)
uv run ~/.claude/skills/onping-line-graph-get/scripts/get_line_graph.py "$ACCESS_TOKEN" <widget-id> --pretty
# Save to file (also printed to stdout; status line to stderr)
uv run ~/.claude/skills/onping-line-graph-get/scripts/get_line_graph.py "$ACCESS_TOKEN" <widget-id> --output widget.json
```

## Flags

- `--output PATH` — write the JSON to this file (also printed to stdout; status line to stderr). Written only after a confirmed 200, so a failure never clobbers an existing file.
- `--pretty` — 2-space-indent + sorted-key JSON. Otherwise a compact single-line body.

## Output

The raw `LineGraphWidget` JSON on stdout. With `--output`, the same body is written to the path plus a status line to stderr.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/content/widgets/line-graph/widget/{id}` | GET | JSON `LineGraphWidget`; `Content-Type: application/json; charset=utf-8` |

Handler: `onping/Handler/Highcharts/LineGraphWidget.hs`.

## Authentication

`/content/widgets/line-graph/widget/{id}` accepts **Bearer token auth** from `onping-login` (verified live 2026-07-13). The handler runs the read under the caller's Haxl identity — the caller sees the widget the same way the OnPing UI does.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no file is written.
- **Unknown widget id** — a non-2xx (usually 404 with an empty body) is surfaced verbatim; no file is written.
