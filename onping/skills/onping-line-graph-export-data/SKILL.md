---
name: onping-line-graph-export-data
description: Export an OnPing line-graph widget's pid bindings as a Dhall [Field] list via GET /content/widgets/line-graph/export-data-only/{id}. Read-only. Distinct shape from onping-line-graph-export — a bare list of from→to pid mappings; edit and re-import via onping-line-graph-import-data to remap pids.
allowed-tools: Bash(uv run *)
---

# OnPing Line Graph Widget — Export Data-Only

Export only the pid bindings of a line-graph widget — a compact Dhall `[Field]`
list that's easy to hand-edit for pid-remap operations. Mirrors the OnPing
frontend's data-only export: a single
`GET /content/widgets/line-graph/export-data-only/{id}` returns the list of
`{from: {onpingKey, description}, to: Optional {type, value}}` records, one per
y-axis parameter and event parameter that has a set pid.

> **Read-only** — no `--yes` gate.

> **Bare Dhall list, no wrapper.** This does NOT emit the full
> `ExportedLineGraphWidget` record — no title, no y-axes, no colors, no
> display config. Just the pid bindings, in the exact shape
> `onping-line-graph-import-data` consumes.

> **Not interchangeable with `-export`.** This produces a Dhall LIST. `-export`
> produces a Dhall RECORD. Feeding a list to `/import` (or a record to
> `/import-data-only`) yields HTTP 400 with
> `{"error": "Invalid Dhall.Decoder … ↳ <type>"}`. See
> [_line_graph_routes/SKILL.md](../_line_graph_routes/SKILL.md) for the schema
> gotcha.

> **Empty-widget case.** A freshly-created widget (via
> `onping-line-graph-create`) has no bound pids; this route emits an empty
> Dhall list. That's a normal response, not an error.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-line-graph-export** — Full-widget Dhall variant (different shape)
- **onping-line-graph-import-data** — Import the edited list back (remap pids)
- **onping-line-graph-get** — Widget JSON if you want the layout too

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Print the Dhall list to stdout
uv run ~/.claude/skills/onping-line-graph-export-data/scripts/export_line_graph_data.py "$ACCESS_TOKEN" <widget-id>
# Save to a file
uv run ~/.claude/skills/onping-line-graph-export-data/scripts/export_line_graph_data.py "$ACCESS_TOKEN" <widget-id> --output chart-data.dhall
```

Round-trip pid remap:

```bash
# 1. Export current bindings
uv run …/export_line_graph_data.py "$ACCESS_TOKEN" <widget-id> --output data.dhall
# 2. Hand-edit `to = Some { type = "PID", value = +<new-pid> }` lines
$EDITOR data.dhall
# 3. Preview + apply the remap
uv run …/onping-line-graph-import-data/scripts/import_line_graph_data.py "$ACCESS_TOKEN" --id <widget-id> --input data.dhall
uv run …/onping-line-graph-import-data/scripts/import_line_graph_data.py "$ACCESS_TOKEN" --id <widget-id> --input data.dhall --yes
```

## Flags

- `--output PATH` — write the Dhall to this file (also printed to stdout; status line to stderr). Written only after a confirmed 200 non-HTML Dhall body.

## Output

A Dhall `[Field]` list. With `--output`, written verbatim to the path.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/content/widgets/line-graph/export-data-only/{id}` | GET | Dhall `[Field]`; `Content-Type: application/vnd.plow.haskell-type+dhall` |

Handler: `onping/Handler/Highcharts/ImportExport.hs`.

## Authentication

Accepts **Bearer token auth** from `onping-login` (verified live 2026-07-13).

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no file is written.
- **Unknown widget id** — 404 with body `Unable to find the requested LineGraphWidget` is surfaced verbatim.
- **Non-Dhall body** — defensive check that the body starts with `[`; a non-Dhall response fails fast without writing.
