---
name: onping-import-singlewell-manual
description: Upload an OnPing singlewell-manual parameter spreadsheet to POST /v2/singlewellmanual/import/params (multipart form; f1=file + f2=location int). MUTATES OnPing with --yes. CREATES and/or UPDATES manual parameters — a blank Pid row creates, a populated Pid row updates. Cannot delete, so the flow is export → edit/append → re-import. SKILL.md documents the 5-column format and value-type tags.
allowed-tools: Bash(uv run *)
---

# OnPing import-singlewell-manual

Uploads an edited/appended parameter spreadsheet for one singlewell-manual
location to OnPing via `POST /v2/singlewellmanual/import/params` (a multipart
form: `f1` = the XLSX, `f2` = the location refId int). This is the write
counterpart to `onping-export-singlewell-manual` (the GET download).

The singlewell-manual driver holds parameters whose values are entered by hand
(no polling) — the shape single-well locations use.

## This tool both CREATES and UPDATES

Unlike `onping-import-mqtt-json` (update-only), this endpoint authors new
parameters as well as updating existing ones:

- **Blank `Pid` cell** → creates a new parameter. The server assigns the Pid.
- **Populated `Pid` cell** → updates that existing parameter's description,
  type, and value.

What it **cannot** do is delete. Server-side, `checkPids` compares the sheet's
*populated* Pids against the location's existing Pids and requires them to
match exactly (`oldPids == newPids`); blank-Pid rows are excluded from that
comparison. So:

- omit an existing Pid → rejected: `missing existing pids in the spreadsheet: [...]`
- add a row with a Pid that doesn't exist yet → rejected: `some pids in the spreadsheet do not exist yet: [...]`
- repeat a `Parameter ID` → rejected: `Duplicate Parameter IDs found in spreadsheet.`

Because of this, the only safe workflow is:

```
export current  →  edit rows and/or append blank-Pid rows  →  re-import
```

1. `onping-export-singlewell-manual "$TOKEN" LOCATION_ID` — download the sheet.
2. Edit existing rows (description / type / value) and/or append new rows with a
   **blank `Pid`** to create parameters. Keep every existing Pid row present.
3. `onping-import-singlewell-manual "$TOKEN" LOCATION_ID sheet.xlsx --yes` — upload.

## Safety

- **Mutating.** A real write happens only with `--yes`. Without `--yes` (and with
  `--dry-run`) the skill validates the file, fetches the live location to check
  Pid coverage, prints a preview, and exits without POSTing. `--dry-run` wins if
  both are passed.
- Before a `--yes` upload the skill **reproduces the server's checks locally**
  (Pid coverage via the export route, duplicate `Parameter ID`, type/value
  validation) so you see the exact problem *before* a wasted upload. It refuses
  to POST a sheet that drops an existing Pid, carries an unknown Pid, duplicates
  a `Parameter ID`, or fails format validation.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# Preview (validate + coverage check, no write):
uv run ~/.claude/skills/onping-import-singlewell-manual/scripts/import_params.py \
  "$ACCESS_TOKEN" LOCATION_ID sheet.xlsx --dry-run

# Apply:
uv run ~/.claude/skills/onping-import-singlewell-manual/scripts/import_params.py \
  "$ACCESS_TOKEN" LOCATION_ID sheet.xlsx --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `location_id` — int (LocationIdRef)
- `spreadsheet` — path to the `.xlsx` to upload
- `--dry-run` / `--yes` — see Safety

---

## Parameter spreadsheet format

The sheet has **5 columns**. Row 1 is a "Parameters" title, **row 2 is the
column header**, and **data begins at row 3**. Column *order* is what the parser
reads.

| # | Column | Meaning |
|---|--------|---------|
| 1 | `Pid` | OnPing parameter id. **Blank = create** (server assigns the Pid), populated = update that parameter. Integer. |
| 2 | `Parameter ID` | The tag's alt/unit id. Integer. **Must be unique across rows.** |
| 3 | `Description` | Human label (e.g. `Casing Pressure`). |
| 4 | `Type` | The value-type tag — see below. **Honored on import** (drives how `Value` is parsed). |
| 5 | `Value` | The value, parsed according to the `Type` tag. |

> **Difference from mqtt-json:** there, the `Type` column is parsed but ignored
> on import. **Here it is honored** — changing `Type` on an existing row changes
> the stored value type, and the `Value` cell is parsed according to it.

### Value-type tags (column 4)

One of exactly these six strings (the parser rejects anything else):

| Tag | `Value` cell parsing |
|-----|----------------------|
| `DoubleTag` | numeric (decimal or whole number) |
| `NaNTag` | ignored — the parameter is a not-a-number tag (export writes `NaN`) |
| `Ascii24Tag` | ASCII text only, capped to **24 bytes** (non-ASCII is rejected) |
| `Utf8_24Tag` | UTF-8 text, capped to **24 bytes** |
| `Utf8_40Tag` | UTF-8 text, capped to **40 bytes** |
| `Utf8_184Tag` | UTF-8 text, capped to **184 bytes** |

The byte caps are applied by the server (`takeBytes`) **silently** — a value
longer than its cap is truncated, not rejected. The skill's preview **warns**
when a value exceeds its cap so you know truncation will happen.

### Create vs. update

- A **blank `Pid`** row is a create. The server inserts a new
  `OnpingParameterRaw` and assigns the Pid; you won't know the assigned Pid until
  you **re-export** after the import.
- A **populated `Pid`** row updates that existing parameter's description, type,
  and value. The `Pid` must be one that already exists on the location.

---

## Source of truth

- Import handler: `onping/Handler/SingleWellManual/ImportExportV2.hs`
  (`postImportManualParametersV2R`) — multipart form `(File, Location int)`,
  route `onping/config/routes` (`ImportManualParametersV2R`). **Field-name
  gotcha:** the handler's `renderDivs $ (,) <$> fileAFormReq "File" <*> areq
  intField "Location"` uses those strings as *labels*; the actual multipart
  field *names* are Yesod's auto-generated `f1` (file) and `f2` (location int),
  in field order. Posting `File`/`Location` yields `400 FormFailure`. Verified
  against the frontend caller
  `OnpingFetch/OnpingFetch_ImportParameters.res`
  (`ret.append("f1", blob); ret.append("f2", loc)`) and
  `OnpingFetch_SingleWellManual.res`
  (`ImportSingleWellManualParametersV2R → "/v2/singlewellmanual/import/params"`).
- Pid-coverage + duplicate-altId check: `checkPids`
  (`ImportExportV2.hs`) — `oldPids == newPids` over `mapMaybe manPid`
  (blank-Pid rows excluded), plus the unique `Parameter ID` guard.
- Sheet parser + columns: `makeOneParameter` / `getManualValueFromCell`
  (`ImportExportV2.hs`), column indices `pidCol=1 .. valCol=5` (:188),
  `firstParamRow = 3` (:166).
- New-param seeding: `updateManualLocationAndAllParams` / `insertParamInMySql`
  (`ImportExportV2.hs`) — `tagPid == 0` triggers an insert.
- Value type + byte caps: `SingleWell.Manual.Types` (`ManualValue`, `takeBytes`).
- Export route reused for the coverage check:
  `GET /v2/singlewellmanual/export/params/{loc}/{filename}`
  (`getExportManualParametersV2R`, `ImportExportV2.hs`).

If any of these drift, re-verify against the recorded locations and update
`scripts/import_params.py` and this file.
