---
name: onping-mqtt-integrator-artifacts-export
description: Download one Lumberjack's mqtt-json-integrator created-object record as XLSX via GET /mqtt/json/integrator/{serial}/artifacts/export/{filename}, or losslessly as JSON via GET .../artifacts. Read-only. This is the integrator's record of what it BELIEVES it created — one-way data flow, never verified against OnPing, values frozen at rule-execution time. The XLSX round-trip is LOSSY (PID timestamps dropped, unknown values collapse to 0.0), so use --json to back up. Its live function is create-suppression, not just audit.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator artifacts-export

Downloads the integrator's record of the locations and PIDs it created for one
Lumberjack.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## Safety

**Read-only on the server.** Both routes are GETs. The skill writes a local file
and changes nothing else.

## What "artifacts" actually are — and are not

Artifacts are the integrator's **own record** of what it created in OnPing and
pushed to the mqtt-json driver. Three properties of that record matter:

- **The data flow is one-way.** The integrator cannot query OnPing or the driver
  to confirm any of these objects still exist. Someone deleting a location in
  OnPing leaves this record untouched and now wrong.
- **Values are frozen.** Each `storedPidValue` is whatever the rules saw at
  execution time. The integrator does not trend PID values; this is not live data.
- **The record is load-bearing, not just documentation.** The create pipeline
  skips anything already recorded as created. That is why importing an artifacts
  sheet creates nothing yet still changes what a subsequent create does.

To verify an object genuinely exists, resolve its PID with `onping-pid-locate` or
list the driver location's parameters with `onping-export-mqtt-json`.

## XLSX is lossy — JSON is not

`Artifacts/ImportExport.hs` flattens `LocalParameterValue` on the way out:

- `localParameterTime` is **dropped entirely**; a re-import sets it to `null`
- a value matching no known constructor falls back to `Double 0.0` / the string
  `"0.0"`

So export → import is **not** identity. Use `--json` for a faithful backup; use
the spreadsheet only when you intend to edit and re-import, accepting that loss.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-artifacts-export/scripts/export_artifacts.py

# Faithful backup (do this before any artifacts-import):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --json

# The editable spreadsheet:
uv run "$SKILL" "$ACCESS_TOKEN" 1001

# What is recorded, per location:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --json --summary

# Schema-check the sheet:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --validate

# Print JSON without writing a file:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --json --stdout
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `--out PATH` — local destination (default `integrator-artifacts-<serial>.xlsx`,
  or `.json` with `--json`)
- `--json` — fetch the lossless JSON record
- `--stdout` — with `--json`, print instead of writing
- `--summary` — per-location breakdown; on the JSON path also flags PIDs whose
  location key is missing from `storedLocations`
- `--validate` — check every sheet row against the expected schema; exits 1 on problems
- `--filename` — the `{filename}` path segment, **ignored by the server**

### Exit codes

- `0` — downloaded (and validated, if asked)
- `1` — transport/auth error, a non-XLSX body, or `--validate` found problems

## The 12 columns

| # | Header | Notes |
|---|---|---|
| 1 | Location Unique Identifier | the location key (output of the Location Match rule) |
| 2 | Location Name | display name |
| 3 | Location ID Ref | **integer** — OnPing's real location refId; trusted verbatim on import |
| 4 | PID Description | |
| 5 | PID Topic | a resolved MQTT topic, not a rule expression |
| 6 | PID Value Selector | plain JQ |
| 7 | PID Time Selector | plain JQ |
| 8 | PID Time Format | `ISO`, `LumberjackTime`, or `Format: <fmt>` |
| 9 | PID Value Type | `Bool`, `Double`, `Utf8Text24`, `Utf8Text40`, `Utf8Text184` |
| 10 | PID Value | the captured value, as text |
| 11 | PID Read Only | **`ReadOnly` / `Writeable`** — the rules sheet uses a BOOLEAN here |
| 12 | PID Local Only | `LocalOnly` or `PushToRTUClient` |

**This is not the rules sheet.** Both are 12 columns with location data in 1-3
and PID data in 4-12, but the meanings differ (column 5 here is a resolved topic;
in the rules sheet it is a match expression) and column 11 uses strings where the
rules sheet uses a boolean. `--validate` catches the confusion. Schema lives in
`_mqtt_integrator_routes/rules_sheet.py`.

A row with columns 4-12 all empty is a location with no PIDs. Filling only some
of them is rejected.

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` (XLSX), `:155` (JSON)
- Sheet: `onping/Handler/MqttJsonIntegrator/Artifacts/ImportExport.hs`
- Lifecycle: `mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md`, "Created Objects"
- Route table: `_mqtt_integrator_routes/routes.py` (`export_artifacts`, `get_artifacts`)

## Related skills

- `onping-mqtt-integrator-artifacts-import` — the write counterpart (record-only, creates nothing)
- `onping-mqtt-integrator-create` — the route that actually creates objects
- `onping-mqtt-integrator-delete --target stored` — forget records (leaves real objects orphaned)
- `onping-pid-locate`, `onping-export-mqtt-json` — verify an object really exists
