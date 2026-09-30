---
name: onping-logtable-export
description: Download a log-table source's XLSX (multi-row-header variant) from POST /logtable/#LJSerial/source/export/query/multiple-rows-header/#String. Resolves the source record via GET /logtable/#LJSerial/source/list, then POSTs the required (LogTableSource, Int) tuple as the JSON body. Read-only.
allowed-tools: Bash(uv run *)
---

# OnPing logtable-export

Downloads a log-table source's XLSX (multi-row-header variant) from OnPing. Its
write counterpart is `onping-logtable-import`, together giving the
`export → edit → re-import` round trip every other OnPing driver skill uses.

**Read-only** on the server: the endpoint is a POST, but its payload is the
source record and it doesn't mutate state. No `--yes` gate.

## Endpoint

- **Route:** `POST /logtable/#LJSerial/source/export/query/multiple-rows-header/#String`
- **Path segment `#String`:** a filename passed through to the response's
  `Content-Disposition`; the skill uses the local output filename here.
- **Body (JSON):** a tuple `[LogTableSource, Int]`. The `Int` is the source's
  `logTableSourceSchemaVersion` — which schema slot of the source to render.
  The frontend caller
  (`OnpingLogTable/Configure/OnpingLogTable_Configure_ImportFromTemplate.res`)
  passes `t'.logTableSourceSchemaVersion` verbatim, and this skill copies that
  field directly from the fetched source record.
- **Response:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  — the XLSX bytes. Written to disk unchanged.

## Why the skill lists sources first

The export handler requires the full `LogTableSource` record, not just a
TableId. Rather than making the caller hand-assemble that JSON, the skill:

1. Calls `GET /logtable/#LJSerial/source/list` (handler
   `onping/Handler/OnpingLogTable/Service.hs`).
2. Filters the returned `[LogTableSource]` by `logTableSourceId == <table_uuid>`.
3. POSTs `[matchingSource, matchingSource.logTableSourceSchemaVersion]` to the
   export endpoint.

If the TableId isn't found on the LJ, the skill exits non-zero and names the
LJ and TableId — no POST to the export endpoint is made.

There is no `source/get/<uuid>` route in `config/routes`; `source/list` is the
only supported lookup path today.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

uv run ~/.claude/skills/onping-logtable-export/scripts/export_logtable.py \
  "$ACCESS_TOKEN" LJ_SERIAL TABLE_UUID [FILENAME]
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `lj_serial`    — Lumberjack serial (int, forwarded as a path segment)
- `table_uuid`   — log-table source's `logTableSourceId` (UUID)
- `filename`     — optional local output path.
                   Default: `./logtable-<lj>-<uuid>-<UTC-ISO-timestamp>.xlsx`

On success, the skill writes the response body to that path and prints the
absolute file path to stdout.

## Source of truth

- Export handler: `onping/Handler/OnpingLogTable/Service.hs`
  (`postLogTableSourceExportQueryMultipleRowsHeaderR`). Body destructured as
  `payload@(t, _version) <- requireInsecureJsonBody :: Handler (LogTableSource, Int)`.
  Response is
  `TypedContent "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`.
- List handler: `onping/Handler/OnpingLogTable/Service.hs`
  (`getLogTableSourceListR`) — returns
  `OnpingResponse [LogTableSource]`, filtered server-side to the caller's
  owned-or-member groups.
- Routes: `onping/config/routes` (`LogTableSourceListR`) and
  `onping/config/routes`
  (`LogTableSourceExportQueryMultipleRowsHeaderR`).
- Types: `onping-logtable/onping-logtable-types/src/Onping/LogTable/Types.hs`
  (the `LogTableSource` record, carrying the `logTableSourceSchemaVersion` field).
- Frontend callers (verified against):
  - `OnpingFetch/OnpingFetch_OnpingLogTable.res`
    (`exportLogTableSourceQueryMultipleRowsHeader` — builds
    `Aeson.Encode.tuple2(encodeLogTableSource, Encode.int, (table, version))`
    as the request body).
  - `OnpingLogTable/Configure/OnpingLogTable_Configure_ImportFromTemplate.res,163`
    (calls that helper with `t'.logTableSourceSchemaVersion` for the `version`
    argument).
- Response envelope for the *list* call: `OnpingResponse a` at
  `onping/OnpingResponse.hs` — success case JSON-encodes `a` (i.e. the array)
  directly; error case is `{"error": text}`.

If any of these drift, re-verify against the recorded locations and update
`scripts/export_logtable.py` and this file.
