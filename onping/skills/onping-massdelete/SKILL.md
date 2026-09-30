---
name: onping-massdelete
description: Delete OnPing historian samples by posting a JSON array of {deletePid, deleteDate} to POST /massdelete/execute. Input is the event-report CSV shape with populated cells rewritten to `1.0`. MUTATES OnPing with --yes; --dry-run previews locally. Chunks large payloads. SKILL.md documents the CSV shape and the UTC-timestamp policy.
allowed-tools: Bash(uv run *)
---

# OnPing massdelete

Deletes `(PID, timestamp)` historian samples via
`POST /massdelete/execute`. Input is a CSV in the OnPing event-report shape;
every non-blank data cell must be the literal string `1.0` (the delete
marker). The skill converts the CSV to the JSON array shape the endpoint
wants, POSTs it (chunking if large), and reports how many entries the server
acknowledged as deleted vs. failed.

The endpoint is destructive — samples replaced with `mempty` in TachDB are
gone. There's no undo. `--yes`-gated.

## Wire contract

- **Route:** `POST /massdelete/execute`
- **Body:** JSON array
  ```json
  [
    {"deletePid": 500004, "deleteDate": "2026-07-10T01:32:27Z"},
    {"deletePid": 500003, "deleteDate": "2026-07-10T01:32:27Z"},
    ...
  ]
  ```
- **Response envelope:**
  ```json
  {
    "successes": [
      {"responsePid": 500004,
       "responseWriteTime": {"tag": "PastWriteTime",
                             "contents": "2026-07-10T01:32:27Z"}}
    ],
    "failures": [ /* same shape */ ]
  }
  ```
  Note: keys are `responsePid` and `responseWriteTime` (not `pid`/`timing`).
  `WriteTime` is a tagged union with `WriteNow` (nullary) or
  `PastWriteTime <ISO>`; delete responses always fall in the `PastWriteTime`
  branch.

## Sibling: onping-mass-write

Different scope. `onping-mass-write` builds a CSV for the OnPing UI's
mass-import dialog and does NOT upload; it's for authoring historic value
writes, not deletions. Don't confuse them.

## Timestamp policy — UTC only, `Z`-suffixed on the wire

`PlowUTCTime`'s FromJSON delegates to aeson's `UTCTime` parser, which
**requires** a timezone marker (either `Z` or `±HH:MM`). Naive strings are
rejected. This skill's policy:

- **Naive input** (`2026-07-09T20:00:04`, no offset) → treated as UTC, emitted
  as `2026-07-09T20:00:04Z`. This matches the standard OnPing event-report
  export.
- **Offset-bearing input** (`2026-07-09T15:00:04-05:00`) → converted to UTC,
  emitted as `2026-07-09T20:00:04Z`.
- **Broken timestamp** → hard-blocked with the row number so you can fix the
  CSV.

Second precision only — the handler buckets to whole seconds
(`plowUTCTimeToInt`), so `.123` fractional seconds don't help you.

> **Watch out:** if your event report is exported in *local time* (rare, but
> possible in some UI configurations), the naive→UTC policy will delete
> points at the *wrong* server timestamps. Convert to UTC before running the
> skill, or add explicit offsets to the CSV.

## CSV shape

Two header rows, then data rows.

| Row       | Column 1              | Columns 2..N              |
|-----------|-----------------------|---------------------------|
| 1         | (empty)               | human labels — ignored    |
| 2         | `Time` (placeholder)  | **integer PIDs**          |
| 3, 4, ... | ISO-8601 timestamp    | `1.0` (delete) **or** blank (skip) |

Example (3 rows, 2 PIDs → 3 delete entries):

```csv
,Well A - Value,Well A - Time
Time,500004,500003
2026-07-09T20:00:04,1.0,1.0
2026-07-09T20:00:05,,1.0
```

produces

```json
[
  {"deletePid": 500004, "deleteDate": "2026-07-09T20:00:04Z"},
  {"deletePid": 500003, "deleteDate": "2026-07-09T20:00:04Z"},
  {"deletePid": 500003, "deleteDate": "2026-07-09T20:00:05Z"}
]
```

### Why `1.0` is a hard requirement

The wire doesn't care — the handler only sees the JSON array; the CSV is
just an authoring surface. But **any non-`1.0` populated cell is a hard
error**, not a silent skip. Rationale: an OnPing event-report export is
full of real numeric values (temperatures, pressures, etc.), and the intended
workflow is to sed-replace every populated numeric cell to `1.0` first. If
half the cells still hold real values, the skill would silently under-delete
— a foot-gun. So the pre-flight refuses.

If you need to convert an event-report CSV into a delete manifest, do:

```bash
# treat every non-empty non-Time cell as "delete this point"
# (simple version — refine if you have string/mixed cells)
uv run --no-project python3 - <<'PY'
import csv
rows = list(csv.reader(open("report.csv")))
for r in rows[2:]:
    for i in range(1, len(r)):
        if r[i].strip():
            r[i] = "1.0"
csv.writer(open("report_ones.csv", "w")).writerows(rows)
PY
```

## Chunking

Payloads larger than `--max-batch` (default 5000 entries) are split into
sequential POSTs; successes and failures are aggregated. Chunks run
sequentially, not in parallel, so a mid-run failure leaves you with a
clean recoverable state: chunks 1..(k-1) applied, chunk k failed, chunks
(k+1)..N never sent. The skill reports which chunk failed and how many
entries were already submitted so you can trim the CSV and retry the tail.

## Safety

- **Mutating.** A real delete happens only with `--yes`. Without `--yes` (or
  with `--dry-run`) the skill validates the CSV, prints a preview (entry
  count, unique PIDs, first/last timestamp), and exits without POSTing.
  `--dry-run` wins if both are passed.
- **No server-side preview.** Deferred to a follow-on
  `onping-massdelete-preview` skill wrapping `POST /massdelete/preview`. For
  now, run `--dry-run` locally and eyeball the summary before adding `--yes`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# Preview (validate, no delete):
uv run ~/.claude/skills/onping-massdelete/scripts/massdelete.py \
  "$ACCESS_TOKEN" delete.csv --dry-run

# Apply:
uv run ~/.claude/skills/onping-massdelete/scripts/massdelete.py \
  "$ACCESS_TOKEN" delete.csv --yes

# Force smaller chunks (e.g. for very large deletes):
uv run ~/.claude/skills/onping-massdelete/scripts/massdelete.py \
  "$ACCESS_TOKEN" delete.csv --yes --max-batch 1000
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `csv_path`     — path to the CSV described above
- `--dry-run` / `--yes` — see Safety
- `--max-batch N` — chunk size (default 5000)
- `--verbose` — dump full JSON responses to stderr per chunk

### Exit codes

| Exit | Meaning |
|------|---------|
| 0    | Every chunk 2xx, `failures == []` (or dry-run with 0 errors) |
| 1    | Validation errors, or one chunk failed with non-2xx (partial delete applied), or server reported non-empty `failures` list |

## Source of truth

- Execute handler: `onping/Handler/MassWrite/Service.hs`
  (`postMassDeleteExecuteR`) — decodes body as `[DeleteRequest]`; wraps result
  as `OnpingResponse MassWriteResponse`.
- Request type: `onping-types/onping-base-types/src/Onping/Types/GenericWriteRequest.hs`
  (`DeleteRequest {deletePid :: PID, deleteDate :: PlowUTCTime}`, Generic ToJSON/FromJSON).
- Response type: `mass-writes-types/src/MassWrites/Types.hs,199`
  (`MassWriteResponseItem {responsePid, responseWriteTime}` +
  `MassWriteResponse {successes, failures}`). Pure Generic derivation —
  field names on the wire equal the selectors verbatim.
- `WriteTime`: `mass-writes-types/src/MassWrites/Types.hs`
  (`WriteNow | PastWriteTime PlowUTCTime` — aeson TaggedObject encoding).
- `PlowUTCTime`: a shared time type
  (FromJSON delegates to `UTCTime`'s FromJSON — requires a timezone marker).
- Frontend caller: `OnpingFetch/OnpingFetch_MassWrite.res`
  (`deleteExecute` — JSON-array body, `POST /massdelete/execute`).
- Route: `onping/config/routes` (`/massdelete/execute MassDeleteExecuteR POST`).

If any of these drift, re-verify against the recorded locations and update
`scripts/massdelete.py` and this file.
