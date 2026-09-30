---
name: onping-mqtt-integrator-rules-export
description: Download one Lumberjack's mqtt-json-integrator generation rules as XLSX via GET /mqtt/json/integrator/{serial}/rules/export/{filename}, or as JSON via GET .../generation/rules. Read-only. The XLSX is the round-trip format for onping-mqtt-integrator-rules-import, which REPLACES ALL RULES — so exporting first is mandatory, not optional. Only the JSON carries the rule identifiers; the sheet omits them. --summary shows how the import will group rows into location blocks, and warns when a location's rows are non-contiguous.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator rules-export

Downloads the generation rules for one Lumberjack's integrator. Two formats, two
different purposes.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver** — it generates locations and PIDs from MQTT pattern rules. Integrator
routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## Safety

**Read-only on the server.** Both routes are GETs and neither mutates state. The
skill writes a local file; nothing else changes.

## Which format to use

| | XLSX (default) | JSON (`--json`) |
|---|---|---|
| Route | `GET .../rules/export/{filename}` | `GET .../generation/rules` |
| Round-trippable | **yes** — feeds `-rules-import` | no import route accepts JSON |
| Rule identifiers | **omitted entirely** | `unLocationRuleIdentifier`, `unPidRuleIdentifier` |
| Use for | bulk edit and re-import | targeting one rule for an incremental update |

The spreadsheet cannot express rule ids at all. If you want to change a single
rule without rewriting the set, read the ids from `--json` and use the
incremental `POST .../generation/rules` path instead of a full sheet import.

## Why exporting first is mandatory

`onping-mqtt-integrator-rules-import` **replaces the entire rule set**, and
`reconstructGenerationRules` re-derives every rule identifier from row order. So:

- any rule missing from your sheet is **deleted**
- every surviving rule gets a **new id**, even if its content is unchanged

The only safe workflow is **export → edit → re-import with everything you intend
to keep**. This skill is step one.

## Row grouping — the non-obvious import rule

The import does not treat each row as an independent rule. It groups
**consecutive** rows whose columns 1-3 (Location Selector Name, Location Name,
Location Match) are identical into one location rule with N PID rules. Two
non-adjacent blocks repeating the same location produce **two separate location
rules**.

`--summary` prints the blocks exactly as the import will see them, and warns when
a location appears in more than one non-contiguous block — which is almost always
an editing accident. Sort the sheet so each location's rows sit together.

A row whose PID columns (4-12) are all empty is a **location-only** rule. Filling
*some* of them is an error: the server rejects the sheet with `Row <n> has
incomplete PID data`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-rules-export/scripts/export_rules.py

# Download the round-trip spreadsheet:
uv run "$SKILL" "$ACCESS_TOKEN" 1001
# -> integrator-rules-1001.xlsx

# Download and inspect how the import will group it:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --summary

# Download and check every row against the schema:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --validate

# Get the rule IDs (not in the sheet):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --json --stdout

# Custom output path:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --out /tmp/before-edit.xlsx
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `--out PATH` — local destination (default `integrator-rules-<serial>.xlsx`,
  or `.json` with `--json`)
- `--json` — fetch the JSON rule list instead of the spreadsheet
- `--stdout` — with `--json`, print instead of writing a file
- `--summary` — per-block breakdown plus the non-contiguity warning
- `--validate` — check every row against the expected schema; exits 1 on problems
- `--filename` — the `{filename}` path segment, **ignored by the server**
  (default `rules.xlsx`); use `--out` to control the local name

### Exit codes

- `0` — downloaded (and validated, if asked)
- `1` — transport/auth error, a non-XLSX body, or `--validate` found problems

## The 12 columns

| # | Header | Notes |
|---|---|---|
| 1 | Location Selector Name | internal label, free text, need not be unique |
| 2 | Location Name | the location's display name; need not be unique |
| 3 | Location Match | **the uniqueness key** — a location is identified by this rule's output |
| 4 | PID Selector Name | internal label |
| 5 | PID Topic | **the PID uniqueness key** |
| 6 | PID Time | JQ selector for the timestamp |
| 7 | PID Time Format | `ISO`, `LumberjackTime`, or `Format: <fmt>` |
| 8 | PID Description | non-unique description |
| 9 | PID Value | JQ selector for the value |
| 10 | PID Type | `Bool`, `Double`, `Utf8Text24`, `Utf8Text40`, `Utf8Text184` |
| 11 | PID Read Only | **BOOLEAN** in this sheet (the artifacts sheet uses `ReadOnly`/`Writeable`) |
| 12 | PID Local Only | `LocalOnly` or `PushToRTUClient` |

Column 11 differing between the two sheet flavors is the easiest mistake to make
when hand-editing; `--validate` catches it. The schema lives in
`_mqtt_integrator_routes/rules_sheet.py`.

Columns 2 and 3 are worth re-reading: the header says "Name" and "Match", but the
backing fields are `locationRuleName` and `locationRuleLocationId` — the latter
holds the match expression despite its name. Column 3 is the key.

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` (XLSX), `:132` (JSON)
- Sheet: `onping/Handler/MqttJsonIntegrator/Rules/ImportExport.hs`
- Route table: `_mqtt_integrator_routes/routes.py` (`export_rules`, `get_rules`)

## Related skills

- `onping-mqtt-integrator-rules-import` — the write counterpart (destructive)
- `onping-mqtt-integrator-rule-parse` — validate edited expressions before importing
- `onping-mqtt-integrator-reports` — whether the rules actually matched anything
- `onping-mqtt-integrator-unprocessed` — the data the rules run against
