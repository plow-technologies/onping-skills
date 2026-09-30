---
name: onping-import-mqtt-json
description: Upload an OnPing mqtt-json parameter spreadsheet to POST /mqtt/json/param/import (multipart form; File + Location). MUTATES OnPing with --yes. Bulk UPDATE, not authoring — the sheet must contain every existing PID, so the flow is export → edit → re-import. SKILL.md documents the full parameter/JQ format.
allowed-tools: Bash(uv run *)
---

# OnPing import-mqtt-json

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> It overwrites the settings of every mqtt-json parameter in the sheet (description, topic, selectors, time format, writeability) and creates a parameter for each blank-PID row. Undo an overwrite by re-importing a sheet exported first with `onping-export-mqtt-json`; created parameters cannot be removed with these skills. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Uploads an edited parameter spreadsheet for one mqtt-json location to OnPing via
`POST /mqtt/json/param/import` (a multipart form: `File` = the XLSX, `Location` =
the location refId int). This is the write counterpart to
`onping-export-mqtt-json` (the GET download).

## This is a bulk UPDATE, not an authoring tool

The import handler reconciles the location's **entire** parameter set from the
spreadsheet. Server-side it fetches the current parameters and requires that
**every existing PID appears in the sheet** (`existingPids ⊆ importedPids`); if
any is missing, it rejects the whole import with
`Missing existing PIDs in the spreadsheet: [...]`. So the only safe workflow is:

```
export current  →  edit rows  →  re-import
```

1. `onping-export-mqtt-json "$TOKEN" LOCATION_ID` — download the current sheet.
2. Edit rows in the sheet (change descriptions, selectors, topics, writeability;
   add new rows with a blank PID to create parameters).
3. `onping-import-mqtt-json "$TOKEN" LOCATION_ID sheet.xlsx --yes` — upload.

Within a row:
- **Blank `PID` cell** → creates a new parameter (seeded from the location's
  loc/site/company ids, empty stored value).
- **Populated `PID` cell** → updates that existing parameter, preserving its
  stored value but overwriting description, topic, selectors, time format, and
  writeability.

## Safety

- **Mutating.** A real write happens only with `--yes`. Without `--yes` (and with
  `--dry-run`) the skill validates the file, fetches the live location to check
  PID coverage, prints a preview, and exits without POSTing. `--dry-run` wins if
  both are passed.
- Before a `--yes` upload the skill **reproduces the server's PID-coverage
  check locally** (via the export route) so you see the exact missing-PID list
  *before* a wasted upload. It refuses to POST a sheet that omits existing PIDs
  or that fails format validation.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# Preview (validate + coverage check, no write):
uv run ~/.claude/skills/onping-import-mqtt-json/scripts/import_params.py \
  "$ACCESS_TOKEN" LOCATION_ID sheet.xlsx --dry-run

# Apply:
uv run ~/.claude/skills/onping-import-mqtt-json/scripts/import_params.py \
  "$ACCESS_TOKEN" LOCATION_ID sheet.xlsx --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `location_id` — int (LocationIdRef)
- `spreadsheet` — path to the `.xlsx` to upload
- `--dry-run` / `--yes` — see Safety

---

## Parameter spreadsheet format

The sheet has **8 columns**, header in row 1, data from row 2. Column *order*
is what the parser reads (not styling).

| # | Column | Meaning |
|---|--------|---------|
| 1 | `PID` | OnPing parameter id. **Blank = create**, populated = update that parameter. |
| 2 | `Description` | Human label (e.g. `Tank Temperature`). |
| 3 | `Topic` | MQTT topic to subscribe to (e.g. `sensors/tank1/data`). |
| 4 | `Value Selector` | JQ expression extracting the value from the JSON payload (e.g. `.temperature`). See JQ subset below. |
| 5 | `Type` | Value type — see below. **Parsed but IGNORED on import**: the stored value type of an existing parameter is preserved regardless of what you put here. Kept for humans reading the sheet. |
| 6 | `Time Format` | How to parse the timestamp — `ISO`, `LumberjackTime`, or a custom strftime string. |
| 7 | `Time Selector` | JQ expression extracting the timestamp (e.g. `.timestamp`). |
| 8 | `Writeable` | `TRUE`/`FALSE` (case-insensitive; `1`/`0` also accepted). |

### Value types (column 5)

One of (blank allowed): `Boolean`, `Double`, `Utf8 Text 24`, `Utf8 Text 40`,
`Utf8 Text 184`. The `Utf8 Text N` variants are UTF-8 text capped at N bytes.
Again — this column does not change an existing parameter's stored type on import.

### Time formats (column 6)

- `ISO` — ISO-8601 timestamps (e.g. `2024-01-15T10:30:00Z`).
- `LumberjackTime` — the Lumberjack's own time (use when the payload has no usable timestamp).
- **Custom strftime string** — any other value is treated as a strftime format.
  Example: `%s` parses a Unix epoch seconds field like `1705320600`.

### Writeability (column 8)

`TRUE` = the parameter can be written back out (writeable); `FALSE` = read-only.

---

## JQ selector subset (columns 4 and 7)

Value/time selectors use a **subset of JQ** (implemented by `plow-jq` V2). The
whole expression is applied to the decoded JSON payload; the first result is the
parameter's value/time.

### Field access & structure

```jq
.                       # identity — the whole payload
.temperature            # field
.sensor.reading         # nested (chained) fields
.'sensor-data'          # quoted field: dashes / leading digits / special chars
."field with spaces"    # double-quoted field with spaces
```

### Arrays

```jq
.[0]                    # index (0-based)
.[-1]                   # negative index — last element
.readings.[0].value     # index into a nested array's object
.[]                     # iterate array elements (or object values)
.readings[]             # iterate a named array
```

### Pipes & constants

```jq
.data | .temperature    # pipe: feed .data's result into .temperature
.sensors | .[0]
25    "active"    true    false    null   # literal constants
```

### Comparisons

`==`, `!=`, `<`, `<=`, `>`, `>=`:

```jq
.temp == 25
.status != "error"
.temp > 20
```

### Logical operators

```jq
.temp > 20 and .temp < 100
.status == "ok" or .status == "warning"
not (.status == "error")
```

### `select(...)` — filtering

`select(cond)` evaluates `cond` against the current value and:
- if `cond` is **truthy → yields the input value unchanged**;
- if `cond` is **false → yields nothing** (the parameter gets no value that cycle — this is not an error).

```jq
# payload: {"sensors":[{"id":"T1","value":23.5},{"id":"P1","value":45.2}]}
.sensors[] | select(.id == "T1") | .value      # → 23.5
.sensors[] | select(.value > 30) | .id         # → "P1"

# payload: {"status":"active","reading":42}
select(.status == "active") | .reading         # → 42
```

Combine with pipes to pick a value out of an array of readings:

```jq
.data.measurements[] | select(.sensor == "TEMP001") | .reading
```

---

## Source of truth

- Import handler: `onping/Handler/MQTT/JSON/Service.hs` (`postImportMqttJsonParametersR`) — multipart form `(File, Location int)`, route `onping/config/routes`. **Field-name gotcha:** the handler's `renderDivs $ (,) <$> fileAFormReq "File" <*> areq intField "Location"` uses those strings as *labels*; the actual multipart field *names* are Yesod's auto-generated `f1` (file) and `f2` (location int), in field order. Posting `File`/`Location` yields `400 FormFailure`. Verified against the frontend caller `OnpingFetch/OnpingFetch_ImportParameters.res`.
- Sheet parser + columns: `onping/Handler/MQTT/JSON/ImportExport.hs` (`ParameterInfoExportable`, `xlsxSheetHeaders`, PID-coverage precondition in `importMqttJsonParameters`).
- Export route reused for the coverage check: `GET /mqtt/json/param/export/{loc}/{filename}` (`Service.hs`).
- Types: `mqtt-json/mqtt-json-types/src/MQTT/JSON/Types.hs` (`ParameterInfo`, `ParameterValueTypeAssigned`, `TimeFormat`, `Writeability`, `JQTimeExpression`).
- JQ subset + `select` semantics: `plow-jq/src/Plow/JQ/V2/{Types,Eval}.hs`.

If any of these drift, re-verify against the recorded locations and update `scripts/import_params.py` and this file.
