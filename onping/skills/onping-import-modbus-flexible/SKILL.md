---
name: onping-import-modbus-flexible
description: Import an edited OnPing modbus-flexible tag spreadsheet into one location via POST /modbus/flexible/import/params (multipart f1=file, f2=location int). MUTATES OnPing with --yes. Matches rows to tags by Index (the server ignores the PID column when it rebuilds tags), refuses duplicate Index, duplicate PID and silent PID changes, and reads the result back by re-export. The flow is export → edit/append → re-import.
allowed-tools: Bash(uv run *)
---

# OnPing import-modbus-flexible

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> It overwrites the description, writeability, on-change deadband and local-only flag of every modbus-flexible tag in the sheet, creates a tag for each blank-PID row, and clears every tag's cached value until the next poll. Undo an edit by re-importing the backup the `--yes` run saves (an export taken just before the upload); created tags and PID changes cannot be undone with these skills. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Uploads an edited tag spreadsheet for one modbus-flexible location. It is the
write counterpart of `onping-export-modbus-flexible`; the location's connection
settings are managed with `onping-update-modbus-flexible`.

## A tag is its Index, not its PID

Before it reads the sheet, the server refuses the import with HTTP 403 unless
the caller owns one of the location's groups. The skill does not check
ownership itself; it reports the 403 and exits 1. Next the server requires that
the sheet's populated PIDs are exactly the location's current PIDs. Then it
**discards the PID column** and rebuilds every tag from the **Index** column.
So each row is one of:

| Row | What the server does | Skill |
|-----|----------------------|-------|
| Index is a current tag's Index, PID is that tag's PID | updates the tag | update |
| PID blank, Index is new | creates a tag and assigns a PID | create |
| PID populated, Index is not that PID's current Index | the PID **leaves the location** (its history stays on it); the row lands on a different PID | refused unless `--allow-pid-change` |

The skill also refuses, before any upload:

- **a duplicate Index** — the server keeps the upper row and silently drops the other;
- **a duplicate PID** — the server's message for it is misleading;
- **a blank-PID row whose Index belongs to a current tag** — that is not a create;
- **a current PID missing from the sheet**, or **a PID the location does not have** — the server refuses these too; the import cannot delete tags;
- **`IdecMicroSmartIndex` rows** — the server stores them in the `IdecIndex` form, so they cannot be read back by Index. Add such tags in the OnPing web page.

Index values are compared as canonical JSON (keys sorted, `17.0` = `17`), the
way the server compares decoded values.

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# 1. Export the current tags.
uv run ~/.claude/skills/onping-export-modbus-flexible/scripts/export_tags.py \
  LOCATION_ID --output tags.xlsx

# 2. Edit rows and/or append blank-PID rows, then preview:
uv run ~/.claude/skills/onping-import-modbus-flexible/scripts/import_params.py \
  LOCATION_ID tags.xlsx

# 3. Apply:
uv run ~/.claude/skills/onping-import-modbus-flexible/scripts/import_params.py \
  LOCATION_ID tags.xlsx --yes
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

### Inputs

- the token — `$ONPING_ACCESS_TOKEN` or `--token-stdin` (from `onping-login`); never an argument
- `location_id` — the location refId (int)
- `spreadsheet` — the edited `.xlsx`
- `--yes` — upload; without it the skill only previews
- `--dry-run` — preview only; wins over `--yes`
- `--allow-pid-change` — allow rows whose Index change moves a tag to a different PID
- `--backup PATH` — where `--yes` saves the pre-import export (default `./modbus-flexible-<location>-<UTC>.backup.xlsx`)

### What it prints

The preview lists the counts of updates, creates and PID changes; each field
change against the current export; each create; each PID change and each PID
that will leave the location; and anything blocking a `--yes`.

With `--yes` it saves the backup, uploads, exports the location again and
compares it with the sheet per Index: every Index present, every updated tag
keeping its PID, Description, Read/Write, On Change and Local Only as sent, and
no other tag present. It prints the PID the server gave each created or moved
row. The server may reuse a PID it gave the same Index on this location before.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | preview with nothing blocking, or upload done and read back equal |
| 1 | the sheet does not parse; a check blocks the upload (also on a preview); the export or upload failed (the server's message is printed as it came); or the **read-back differs** from the sheet |
| 2 | bad command-line arguments |

## Spreadsheet format

Sheet `Sheet1`. Row 1 is the title `Parameters`, row 2 the header, data from
row 3. The skill requires the header to name these seven columns in this order,
because the server reads columns by position:

| # | Column | Accepted | Blank means |
|---|--------|----------|-------------|
| 1 | `PID` | a whole-number cell (not text) | create |
| 2 | `Index` | a text cell holding JSON `{"tag": <family>, "contents": …}` | — (required) |
| 3 | `Description` | text, or a number (stored as text) | empty |
| 4 | `Read/Write` | `ReadOnly` or `ReadWrite`, any letter case | — (required) |
| 5 | `Data Type` | `Word8` `Word16` `Word32` `Word64` `Int8` `Int16` `Int32` `Int64` `Float` `Float16` `Double` `Text` `Undefined`, any case | none |
| 6 | `On Change` | a number cell | none |
| 7 | `Local Only` | a true/false cell, the text `true`/`false` (any case), or 0/1 | false |

Example Index (synthetic):

```json
{"tag":"SCADAPackIndex","contents":{"tag":"SCADAPackHoldingRegisterInt16","contents":17}}
```

The 24 Index families: `SpiritIndex`, `IdecIndex`, `IdecMicroSmartIndex`
(refused), `FergusonIndex`, `AutoPilotIndex`, `SCADAPackIndex`,
`AMIAnalyzerIndex`, `HarrierPlusIndex`, `MicrologixModbusIndex`,
`TotalFlowModbusIndex`, `Scanner2000Index`, `GePLCIndex`,
`EpicLiftSystemsIndex`, `ProstarPWMV2Index`, `RocModbusIndex`,
`ControlWaveIndex`, `NovusDigiRailIndex`, `AIDNP5AIndex`,
`Rosemount1000Index`, `Rosemount8700Index`, `ADAM4055Index`, `ADAM4117Index`,
`FrenicIndex`, `SiemensS7Index`. The server checks each family's contents and
rejects overlapping registers; its message is passed through.

Rules the server applies, and so the skill does too:

- A cell holding only `""` or a single space counts as blank.
- The data ends at the last row with any value, in any column. **A blank row
  inside the data fails the whole sheet.**

### What an import loses or ignores

- **Cached values.** Every tag reads no data until the location's next poll,
  including tags whose rows did not change.
- **Units.** The sheet has no units column, and the server assigns units on
  import. The skill leaves units alone and does not compare them.
- **Data Type** is used only by `IdecMicroSmartIndex`. `IdecIndex` types are
  forced by register kind, and every other family derives its type from the
  Index. The skill notes a sheet value that will be ignored; the read-back does
  not treat it as a mismatch.

## Source of truth

Server modules this skill restates (re-read them if behaviour drifts):

- `Handler.ModbusFlexible.ImportExport` — `postImportModbusFlexibleParametersR`
  (the route, the `f1`/`f2` form whose labels are `File`/`Location`; posting
  the labels as field names gives `400 FormFailure`), `checkPids`, the column
  parsers.
- `Handler.Xlsx.Sheet` and `Handler.Xlsx.Cell` — the blank-cell filter, the row
  count, and each cell type's rules.
- `Handler.ModbusFlexible.Service` — `convertToExtendedConfig` (Data Type use),
  `updateModbusFlexibleLocationParameters` (rebuild keyed by Index, register
  overlap check, PID lookup by Index).
- `SingleWell.Modbus.Flexible.AvailableIndexing` — the Index families.

If these drift, update `scripts/import_params.py`, its tests and this file.

## Related skills

- `onping-login` — get the access token
- `onping-search` — find a location's refId
- `onping-export-modbus-flexible` — the export this skill reads and re-imports
- `onping-update-modbus-flexible` — the location's connection settings, which the import does not touch
