---
name: onping-line-graph-import
description: Import a full OnPing line-graph widget from a Dhall / JSON / YAML file via POST /content/widgets/line-graph/import/{id}. MUTATING, requires --yes. Overwrites the target widget in place; `--new` mints a fresh id and imports into it (two-step). --dry-run runs locally (no /parse endpoint) and surfaces the pid list the server will permission-check.
allowed-tools: Bash(uv run *)
---

# OnPing Line Graph Widget — Import

Import a full line-graph widget layout into an existing widget id — the
write-back inverse of `onping-line-graph-export`, and the way to restore, edit,
or clone a chart. Accepts three input formats: `.dhall` (passthrough), `.json`,
or `.yaml` (both friendly formats are compiled to Dhall by expanding the
`DisplayNameConfig` union boilerplate per parameter).

> **Import is a MUTATION.** By default the import **overwrites** the widget in
> place via `repsertLineGraphWidget`. Nothing is written to OnPing unless you
> pass `--yes`. The default and `--dry-run` validate the input locally and
> preview what would be written, but do not POST.

> **`--dry-run` is fully local — no network call** (unlike `onping-hmi-import`,
> which has `/hmi/parse` to validate server-side). Line-graph has no `/parse`
> endpoint, so the shape check is client-side only. It confirms:
> (1) the input is a Dhall record (not a `[Field]` list), (2) all required
> top-level keys are present, (3) the pid list that the server will
> permission-check. The authoritative type-check runs on the actual POST.

> **⚠️ Schema gotcha #1 — full vs data-only.** This skill's input is a Dhall
> `ExportedLineGraphWidget` RECORD keyed
> `{title, timePeriod, timeUnit, updateInterval, yAxes, eventParameters,
> maxStep, normalizeValue, latestValueLine, legendWithCurrentValue}`. It is
> NOT interchangeable with the `[Field]` LIST consumed by
> `onping-line-graph-import-data`. Feeding a `-export-data` output to this
> skill yields a local shape-check refusal (or, if forced through with
> `--yes`, an HTTP 400 with `{"error": "Invalid Dhall.Decoder … ↳ Record …"}`).

> **⚠️ Schema gotcha #2 — server-side pid permission check (fail-open on unknown).**
> The handler (`LineGraphWidget.hs`) collects every pid/vpid across
> `yAxes[].parameters[].pid` and `eventParameters[].pid`, and calls
> `LocationLister.checkOnpingKeysPermission`. If the caller lacks Read on ANY
> pid whose location resolves, the server returns HTTP 400 with
> `{"error": "Permission error for [<keys>]"}` and the widget is NOT modified.
> **Unknown pids (never-existed ids, deleted ids) are silently accepted** —
> they don't map to a location, so they drop out of the check and land on the
> widget as-is (verified 2026-07-14). If you want to validate that a pid is
> real and readable, use `onping-parameters` or `onping-search` before import.
> `--dry-run` prints the exact pid list the server will check.

> **⚠️ `--new` leaves an orphan on failure.** `--new` is a two-step
> (`POST /config` mints, `POST /import` populates). If the first call succeeds
> but the second fails, the minted widget exists but is empty. **There is no
> delete route for line-graph widgets** — cleanup requires deleting the
> parent dashboard. The skill prints the orphaned id on failure so it's not
> silently lost.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-line-graph-export** — Export a widget to Dhall (produces the file this imports — the round-trip)
- **onping-line-graph-create** — Mint a fresh widget id (used internally by `--new`)
- **onping-line-graph-import-data** — Data-only variant (remap pids without touching layout)
- **onping-charts/skills/onping-line-graph** — Reference doc for the Dhall schema, colors, and design patterns

## When to Use

- **Restore** a widget from an `onping-line-graph-export` backup.
- **Edit**: export → hand-edit the Dhall (title, colors, pids, hidden flags) → import back.
- **Clone**: `import --new` mints a fresh id and populates it (source untouched).
- **Author from scratch**: write a compact `.json` / `.yaml` (the friendly format), let this skill compile it to Dhall.

## Usage

Requires a valid access token and an input file (`.dhall`, `.json`, or `.yaml`).

**Preview (default — validates locally, shows the pid list, no network):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-line-graph-import/scripts/import_line_graph.py \
  "$ACCESS_TOKEN" --id <widget-id> --input chart.dhall
```

**Apply — overwrite the target widget:**

```bash
uv run …/import_line_graph.py "$ACCESS_TOKEN" --id <widget-id> --input chart.dhall --yes
```

**Clone — mint a fresh widget and populate it (source untouched):**

```bash
NEW_ID=$(uv run …/import_line_graph.py "$ACCESS_TOKEN" --new --input chart.dhall --yes)
echo "created widget: $NEW_ID"
```

**Friendly JSON input:**

```bash
uv run …/import_line_graph.py "$ACCESS_TOKEN" --id <widget-id> --input chart.json --yes
```

**Friendly YAML input:**

```bash
uv run …/import_line_graph.py "$ACCESS_TOKEN" --id <widget-id> --input chart.yaml --yes
```

**Round-trip:**

```bash
# 1. Back up
uv run …/onping-line-graph-export/scripts/export_line_graph.py "$ACCESS_TOKEN" <widget-id> --output before.dhall
# 2. Edit
$EDITOR before.dhall
# 3. Preview + apply
uv run …/import_line_graph.py "$ACCESS_TOKEN" --id <widget-id> --input before.dhall           # preview
uv run …/import_line_graph.py "$ACCESS_TOKEN" --id <widget-id> --input before.dhall --yes     # apply
```

## Friendly JSON/YAML input format

The compact spec expands into an `ExportedLineGraphWidget` Dhall record. Every
field has a sensible default; the friendly compiler generates the full
`DisplayNameConfig` union boilerplate for you.

**Minimal JSON example** (equivalent to `fixtures/Rewards_export.dhall`'s Reward axis, in compact form):

```json
{
  "title": "Reward Trends (24h)",
  "timePeriod": 1440,
  "timeUnit": "minute",
  "updateInterval": 60,
  "maxStep": 1,
  "latestValueLine": false,
  "legendWithCurrentValue": false,
  "yAxes": [
    {
      "description": "Reward",
      "parameters": [
        {"pid": {"type": "PID", "value": 500022}, "name": "Total Reward",
         "color": "rgba(0, 200, 0, 1)", "line_width": 2.0, "hidden": true},
        {"pid": {"type": "PID", "value": 500023}, "name": "Arrival Reward",
         "color": "rgba(255, 140, 0, 1)", "line_width": 2.0}
      ]
    }
  ],
  "eventParameters": [
    {"pid": {"type": "PID", "value": 500024}, "name": "Valve Status",
     "icon": "dot-circle-o", "color": "#0758bb", "hidden": true}
  ]
}
```

**Field defaults** — anything you don't set gets these:

| Field | Default |
|---|---|
| `title` | `"New Chart"` |
| `timePeriod` | `1` |
| `timeUnit` | `"hour"` |
| `updateInterval` | `60` |
| `maxStep` | `1` |
| `normalizeValue` | `false` |
| `latestValueLine` | `None Bool` (omitted from JSON) |
| `legendWithCurrentValue` | `true` |
| `yAxes[i].opposite` | `false` |
| `yAxes[i].scale` | `"linear"` |
| `yAxes[i].rangeMin` / `rangeMax` | `None Integer` (omit from JSON for auto) |
| `parameters[i].graph_type` | `"line"` |
| `parameters[i].line_width` | `1.0` |
| `parameters[i].hidden` | `false` |
| `parameters[i].color` | `"#0758bb"` |
| `parameters[i].display_name_config` | `DisplayByText <name>` |
| `eventParameters[i].icon` | `"dot-circle-o"` |

**DisplayNameConfig variants:**

```json
"display_name_config": "Static text"
"display_name_config": {"text": "Static text"}
"display_name_config": {"parameter": {"pid": 500025, "metadata": ["parameterName"]}}
"display_name_config": {"parameter": {"vpid": 12345, "name": true}}
"display_name_config": {"parameter": {"vpid": 12345, "metadata": ["fieldA", "fieldB"]}}
"display_name_config": {"other_parameter": {"pid": 500025, "metadata": ["parameterName"]}}
```

> **Best-effort format.** The friendly compiler produces a valid
> `ExportedLineGraphWidget` for the current schema. If OnPing adds a new
> top-level field, the compiler silently defaults it. `.dhall` passthrough is
> the authoritative round-trip.

## Flags

- `--id <widget-id>` — the LineGraphWidgetId to overwrite. Required unless `--new`.
- `--new` — mint a fresh widget id via `POST /config`, then import into it. Prints the new id on success. Mutually exclusive with `--id`.
- `--input PATH` — exported Dhall/JSON/YAML file to import (default: read from stdin).
- `--input-format {dhall,json,yaml}` — override the input format detection. Required for stdin YAML.
- `--yes` — perform the import. **Required** for any write.
- `--dry-run` — explicit preview; validates locally, prints the pid list, no POST. Wins over `--yes` if both are passed.
- `--json` — after a successful apply, emit the imported widget JSON to stdout.

## Output

- **Preview:** shape-check result (✓/✗ per required key), the target widget id or "would MINT", the full unique pid/vpid list the server will permission-check. Exit 0 on shape OK, 2 on shape errors.
- **Apply (overwrite):** `Imported into widget <id>` to stderr; exit 0 on 200. With `--json`, the imported widget JSON on stdout.
- **Apply (`--new`):** the new widget id on stdout; import status on stderr; exit 0 on 200.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|---|---|---|---|---|
| `/content/widgets/line-graph/config` | POST | (empty) | (none) | JSON-quoted widget id (used only for `--new`) |
| `/content/widgets/line-graph/import/{id}` | POST | `text/plain;charset=UTF-8` | Dhall `ExportedLineGraphWidget` | Raw JSON widget on 200; `{"error": "..."}` on 400 |

Handler: `onping/Handler/Highcharts/LineGraphWidget.hs`. Permission check: `:175-181`.

The response is a **raw** `LineGraphWidget` JSON (no `{status, data, …}` wrapper) — verified live 2026-07-13.

## Authentication

Accepts **Bearer token auth** from `onping-login`. The server also enforces Read on every pid/vpid referenced in the widget (see gotcha #2 above).

## Error Handling

- **Local shape refuses** — the input is a `[Field]` list, or is missing required keys, or isn't a Dhall record; the skill exits 2 (or refuses to POST on `--yes`) with a clear message.
- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no import.
- **Malformed Dhall** — server type-check fails, 400 with `{"error": "Invalid Dhall.Decoder …"}`; surfaced verbatim; widget not modified.
- **Permission denied on a pid** — 400 with `{"error": "Permission error for [<keys>]"}`; surfaced verbatim; widget not modified.
- **`--new` half-success** — `POST /config` succeeded, `POST /import` failed; the fresh id is printed with a clear cleanup note.
- **Unknown target widget id (without `--new`)** — 404 `"LineGraph Not Found"`; surfaced verbatim.
