---
name: onping-line-graph-export
description: Export an OnPing line-graph widget to a Dhall file via GET /content/widgets/line-graph/export/{id}. Read-only. Backs up a full widget (title, yAxes, eventParameters, all display config) for restore or cloning with onping-line-graph-import.
allowed-tools: Bash(uv run *)
---

# OnPing Line Graph Widget — Export

Back up a full line-graph widget to a Dhall file — the recommended backup step
before editing or overwriting a widget. Mirrors the OnPing frontend's
line-graph export: a single `GET /content/widgets/line-graph/export/{id}`
returns the complete `ExportedLineGraphWidget` (title, timePeriod, timeUnit,
updateInterval, yAxes, eventParameters, maxStep, normalizeValue,
latestValueLine, legendWithCurrentValue) as Dhall
(`Content-Type: text/x-dhall`, `Content-Disposition: attachment`).

> **Read-only** — no `--yes` gate (unlike `onping-line-graph-import`).

> **Full widget, not just data.** This exports the entire widget including
> layout, colors, line widths, and display name config. For only the OnPing-pid
> data bindings, use `onping-line-graph-export-data`.

> **Not interchangeable with `-export-data`.** This produces a Dhall RECORD
> keyed `{title, timePeriod, …}`. `-export-data` produces a Dhall LIST of
> `[Field]` pid mappings. Feeding a record to `/import-data-only` (or a list to
> `/import`) yields HTTP 400 with `{"error": "Invalid Dhall.Decoder … ↳ <type>"}`.
> See the schema-gotcha note in [_line_graph_routes/SKILL.md](../_line_graph_routes/SKILL.md).

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-line-graph-get** — JSON variant of the same widget (no Dhall round-trip)
- **onping-line-graph-import** — Import/restore the Dhall this emits (the round-trip)
- **onping-line-graph-export-data** — Export only the pid bindings, not the full widget

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Print the Dhall to stdout
uv run ~/.claude/skills/onping-line-graph-export/scripts/export_line_graph.py "$ACCESS_TOKEN" <widget-id>
# Save to a file (also printed to stdout; status line to stderr)
uv run ~/.claude/skills/onping-line-graph-export/scripts/export_line_graph.py "$ACCESS_TOKEN" <widget-id> --output chart.dhall
```

## Flags

- `--output PATH` — write the Dhall to this file (also printed to stdout; status line to stderr). Written only after a confirmed 200 non-HTML Dhall body, so a failure never clobbers an existing backup.

## Output

A Dhall `ExportedLineGraphWidget` record. With `--output`, written verbatim to the path.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/content/widgets/line-graph/export/{id}` | GET | Dhall `ExportedLineGraphWidget`; `Content-Type: text/x-dhall;charset=utf-8`; `Content-Disposition: attachment` |

Handler: `onping/Handler/Highcharts/LineGraphWidget.hs`.

## Authentication

Accepts **Bearer token auth** from `onping-login` (verified live 2026-07-13).

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no file is written.
- **Unknown widget id** — a 404 (Dhall `DhallError "Not found"` body) is surfaced verbatim; no file is written.
- **Non-Dhall body** — defensive check that the body starts with `{`; a non-Dhall response (HTML, error page) fails fast without writing.
