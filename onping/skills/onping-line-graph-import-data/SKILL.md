---
name: onping-line-graph-import-data
description: Remap pid bindings on an OnPing line-graph widget via POST /content/widgets/line-graph/import-data-only/{id}. Consumes a Dhall [Field] list of from→to OnpingKey mappings. MUTATING, requires --yes. Rewrites pids only — leaves title / colors / axis descriptions / event icons untouched. Distinct shape from onping-line-graph-import.
allowed-tools: Bash(uv run *)
---

# OnPing Line Graph Widget — Import Data-Only

Remap the pid bindings on a line-graph widget without touching layout. Wraps
`POST /content/widgets/line-graph/import-data-only/{id}` with a Dhall `[Field]`
body — a list of `{from : {onpingKey, description}, to : Optional {type, value}}`
records. The handler (`onping/Handler/Highcharts/ImportExport.hs`)
rewrites `yParam_pid` and `eventParam_pid` where `from` matches; every other
field is untouched.

> **MUTATING — requires `--yes`.** By default the skill validates the input
> locally, prints the from→to mapping table, and does NOT POST.

> **⚠️ Schema gotcha — different shape from `-import`.** This endpoint consumes
> a Dhall LIST of `[Field]` records. `-import` consumes a Dhall RECORD
> (`ExportedLineGraphWidget`). Feeding an export to this endpoint (or an
> export-data list to `-import`) yields HTTP 400 with
> `{"error": "Invalid Dhall.Decoder … ↳ List …"}`. The local shape check
> refuses to POST if the input starts with `{` (a record).

> **Only pids are remapped.** Every non-pid field on the target widget is
> preserved by the handler. Unreachable `from` keys — pids not present on the
> target — are a no-op server-side, not an error.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-line-graph-export-data** — Export the current pid bindings (the input for this skill)
- **onping-line-graph-import** — Full-widget import (overwrites layout too)
- **onping-line-graph-get** — Read the widget to confirm the remap took effect

## Usage

Requires an access token and a Dhall `[Field]` file (typically from `-export-data`).

**Preview (default — parses input, prints from→to table, no network):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-line-graph-import-data/scripts/import_line_graph_data.py \
  "$ACCESS_TOKEN" --id <widget-id> --input data.dhall
```

**Apply — rewrite pids on the target widget:**

```bash
uv run …/import_line_graph_data.py "$ACCESS_TOKEN" --id <widget-id> --input data.dhall --yes
```

**Round-trip pid remap:**

```bash
# 1. Export current bindings
uv run …/onping-line-graph-export-data/scripts/export_line_graph_data.py "$ACCESS_TOKEN" <widget-id> --output data.dhall
# 2. Hand-edit the `to = Some { type = "PID", value = +<new-pid> }` lines
$EDITOR data.dhall
# 3. Preview + apply the remap
uv run …/import_line_graph_data.py "$ACCESS_TOKEN" --id <widget-id> --input data.dhall           # preview
uv run …/import_line_graph_data.py "$ACCESS_TOKEN" --id <widget-id> --input data.dhall --yes     # apply
```

## Flags

- `--id <widget-id>` — the LineGraphWidgetId to remap. Required.
- `--input PATH` — Dhall `[Field]` file to apply (default: read from stdin).
- `--yes` — perform the remap. **Required** for any write.
- `--dry-run` — explicit preview; validates locally, prints the from→to mapping, no POST. Wins over `--yes`.
- `--json` — after a successful apply, emit the resulting widget JSON to stdout.

## Output

- **Preview:** shape-check result, target widget id, from→to mapping table. Exit 0 on shape OK, 2 on shape errors.
- **Apply:** `Remapped pids on widget <id>` to stderr; exit 0 on 200. With `--json`, the updated widget JSON on stdout.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|---|---|---|---|---|
| `/content/widgets/line-graph/import-data-only/{id}` | POST | `text/plain;charset=UTF-8` | Dhall `[Field]` | Raw JSON widget on 200; `{"error": "..."}` on 400 |

Handler: `onping/Handler/Highcharts/ImportExport.hs`.

## Authentication

Accepts **Bearer token auth** from `onping-login`. Unknown widget id → 404 `"Unable to find the requested LineGraphWidget"`.

## Error Handling

- **Local shape refuses** — the input is a Dhall RECORD (looks like an `-export` output), or isn't a list; the skill exits 2 (or refuses to POST on `--yes`) with a clear message.
- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no remap.
- **Malformed Dhall** — server type-check fails, 400 with `{"error": "Invalid Dhall.Decoder …"}`; surfaced verbatim; widget not modified.
- **Unknown target widget id** — 404 `"Unable to find the requested LineGraphWidget"`; surfaced verbatim.
