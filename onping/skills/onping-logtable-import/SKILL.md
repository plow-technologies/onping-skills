---
name: onping-logtable-import
description: >-
  Upload a multiple-rows-header log-table XLSX to POST /logtable/#LJSerial/source/import/template/multiple-rows-header (multipart form; f1=file + f2=TableId UUID). MUTATES OnPing with --yes. Requires an existing log-table source. Rejects non-integer sources (`source: TODO` placeholders included) locally to pre-empt the server's `Invalid PID or VPID format for` 400. SKILL.md documents the 4-row `event`/`name:`/`tag:`/`source:` template shape and the `f1`/`f2` positional-field gotcha.
allowed-tools: Bash(uv run *)
---

# OnPing logtable-import

Uploads an authored log-table XLSX (multi-row-header flavor) to OnPing via
`POST /logtable/#LJSerial/source/import/template/multiple-rows-header`. The
target log-table **source must already exist** on the Lumberjack — this skill
does not create sources. Its write counterpart is `onping-logtable-export` (the
POST download).

## What this skill covers (and doesn't)

- **Covers:** the multi-row-header variant of the log-table import — the one
  the Example Energy transport reference schema uses. Four header rows, then
  optional data rows.
- **Doesn't cover:** the single-header import (`POST /logtable/#LJSerial/source/import/template`)
  or the event-table import (`POST /logtable/#LJSerial/source/import/event-table`).
  Different sheet shapes, different endpoints.
- **Doesn't create sources.** The target log-table source must already exist.
  Use the OnPing UI (or a future `onping-logtable-source-create` skill wrapping
  `POST /logtable/#LJSerial/source/create`) to mint one first. The skill needs
  its `logTableSourceId` (a UUID) as input.

## The `f1` / `f2` field-name gotcha

The import handler defines its multipart form as

```haskell
form :: Form (FileInfo, Text)
form =
  renderDivs $
    (,)
      <$> fileAFormReq "File"
      <*> areq textField "TableId" Nothing
```

Those strings are **labels**, not field names. Yesod's `renderDivs`
auto-generates the actual multipart field *names* `f1`, `f2` in field order.
Posting `File` / `TableId` yields `400 FormFailure`.

The handler explicitly warns about this on `Service.hs`:

> `-- | Note: "File" and "TableId" identifiers doesn't matter, request must still use "f1" and "f2".`

So the skill sends `f1` = XLSX bytes, `f2` = TableId (UUID as text). This is
the same trap the mqtt-json and singlewell-manual imports fell into.

## Safety

- **Mutating.** A real write happens only with `--yes`. Without `--yes` (and
  with `--dry-run`) the skill validates the file locally and prints a preview,
  never POSTing. `--dry-run` wins if both are passed.
- **Pre-flight validation** is local-only (no server round-trip). The log-table
  import handler's failure modes are simple: bad UUID, permission denied, or a
  malformed XLSX — so the pre-flight is limited to sheet-shape checks. If the
  caller's group doesn't own the source's group, the handler returns
  `400 Permission Denied` and the skill surfaces that with a hint.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# Preview (validate, no write):
uv run ~/.claude/skills/onping-logtable-import/scripts/import_logtable.py \
  "$ACCESS_TOKEN" LJ_SERIAL TABLE_UUID sheet.xlsx --dry-run

# Apply:
uv run ~/.claude/skills/onping-logtable-import/scripts/import_logtable.py \
  "$ACCESS_TOKEN" LJ_SERIAL TABLE_UUID sheet.xlsx --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `lj_serial`    — Lumberjack serial (int, forwarded as a path segment)
- `table_uuid`   — target log-table source's `logTableSourceId` (UUID)
- `spreadsheet`  — path to the `.xlsx` to upload
- `--dry-run` / `--yes` — see Safety

---

## Spreadsheet format — 4 rows, then data

Row order is fixed. Column *width* is uniform across rows 2..4 (row 1 only
populates column 1, the `event` marker).

| Row | Column 1                                         | Column 2..N                                   |
|-----|--------------------------------------------------|-----------------------------------------------|
| 1   | `event`                                          | *(blank)*                                     |
| 2   | `name: <label for the trigger column>`           | `name: <label for this result column>`        |
| 3   | `tag: dateTime`                                  | `tag: result`                                 |
| 4   | `source: <integer PID>`                          | `source: <integer PID>`                       |

- **Column 1 is the event trigger.** The tag on row 3 is `tag: dateTime`; its
  `source:` PID is the parameter whose write fires a new row.
- **Every other column is a result value** snapshotted into the row when the
  trigger fires. Row 3 is `tag: result`; row 4 is the PID that supplies the
  value.
- **Non-integer sources (including `TODO`-style placeholders) are hard-blocked
  by the pre-flight.** Observed live on a test Lumberjack on 2026-07-10: the server
  rejects any non-integer source with `Invalid PID or VPID format for: <value>.
  input does not start with a digit. At row=4, col=<N>`. The skill reproduces
  this check locally rather than paying for a multipart round-trip only to see
  the 400. Callers that need to hold a "column exists but PID isn't provisioned
  yet" position must either omit the column (regenerating when the PID lands)
  or point it at a temporary integer PID.
- **Duplicate PIDs across columns** are a warning only — the server accepts
  them, but they're almost always a bug in the authoring script.

Column count is not bounded by the skill; the Example Energy Lane 1 reference sheet has
106 columns (1 trigger + 105 results) and imports fine.

## Response

On a 2xx from the import endpoint, the response body is the updated
`LogTableSource` JSON envelope (`OnpingResponse`-wrapped; on success the
envelope is `toJSON a`, i.e. the object itself). The skill prints the
returned `TableId` and the number of columns the server saved into the
selected schema version.

## Source of truth

- Import handler: `onping/Handler/OnpingLogTable/Service.hs`
  (`postLogTableSourceImportFromTemplateMultipleRowsHeaderR`). Multipart form
  `(FileInfo, Text)` at `Service.hs`. **Positional field-name comment in the form definition: `f1`/`f2` are the actual wire names**, not the label strings.
- Route: `onping/config/routes` (or thereabouts —
  `LogTableSourceImportFromTemplateMultipleRowsHeaderR`).
- Frontend caller (verified against): `OnpingFetch/OnpingFetch_OnpingLogTable.res`
  (`importLogTableSourceFromTemplateMultipleRowsHeader` builds the same
  multipart body via `mkFileFormData(blob, tableUUID)`).
- Types: `onping-logtable/onping-logtable-types/src/Onping/LogTable/Types.hs`
  (`LogTableSource`).
- Permission check: `Service.hs` — `logTableSourceGroup(routingIndex,
  tableId') ∈ Permissions.Access.getOwnedGroupIdsList`. Denial responds
  `400 Permission Denied`.
- Response envelope: `OnpingResponse a` at `onping/OnpingResponse.hs`
  (on success, JSON-encodes `a` directly; on error, `{"error": text}`).

If any of these drift, re-verify against the recorded locations and update
`scripts/import_logtable.py` and this file.
