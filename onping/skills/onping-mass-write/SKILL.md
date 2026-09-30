---
name: onping-mass-write
description: Build a validated OnPing mass-write CSV from timestamp+value points. Builds the file only — does NOT upload. The user takes the resulting CSV to the OnPing UI mass-import dialog, which writes to the cloud server only (not local Lumberjack edge servers).
allowed-tools: Bash(uv run *)
---

# OnPing Mass-Write CSV Builder

Build the CSV that the OnPing UI's "Mass Write CSV Import" dialog expects. The skill validates every row and emits a file (or stdout) ready for upload. **It does not perform the upload.**

## When to use

You have historical timestamp+value points you need to backfill into OnPing against a single PID, and you want a clean import file rather than hand-crafting it in a spreadsheet.

## Inputs

- **`PID`** (positional, required) — the target OnPing parameter id (numeric).
- **`--input <path>`** (optional) — read points from this file. If omitted, reads from stdin.
- **`--label <text>`** (optional) — human label that appears in row 1 column B (e.g. `North Field / Tank 2 SCADA Data`). Defaults to empty.
- **`--output <path>`** — write CSV to this path. Default: `./mass-write-<PID>-<UTC-timestamp>.csv`.
- **`--stdout`** — write CSV body to stdout instead of a file. Mutually exclusive with `--output`.

The points input is a no-header two-column CSV: `timestamp,value` per row. Timestamps must parse via `datetime.fromisoformat`; values must parse as floats.

## Usage

From a points file:

```bash
uv run ~/.claude/skills/onping-mass-write/scripts/build_csv.py \
  100001 \
  --label 'North Field / Tank 2 SCADA Data' \
  --input ~/points.csv \
  --output ~/Desktop/florence-backfill.csv
```

From stdin:

```bash
printf '2025-01-14T08:29:47,31\n2025-01-14T15:05:28,18\n' | \
  uv run ~/.claude/skills/onping-mass-write/scripts/build_csv.py 100001 --stdout
```

## Output shape

Matches the OnPing mass-import format (see `templates/MassWriteCSVImportExample.csv`):

```
,North Field / Tank 2 SCADA Data
Time,100001
2025-01-14T08:29:47,31
2025-01-14T15:05:28,18
```

Row 1: blank column A, label in column B. Row 2: literal `Time` in column A, PID in column B. Rows 3+: ISO 8601 timestamp, numeric value, sorted ascending. Lines terminate with `\r\n`.

## Validation (strict, all-or-nothing)

- PID must be numeric.
- Each input row must have exactly 2 columns.
- Each timestamp must parse via `datetime.fromisoformat`.
- Each value must parse as `float`.
- At least one data row required.
- No duplicate timestamps.
- Trailing blank lines are tolerated (ignored).

If any check fails, the script prints the offending row index and content to stderr, exits non-zero, and writes no output file.

## Cloud vs. Edge

**Important:** when you upload the resulting CSV via the OnPing UI mass-import dialog, the data lands on the **OnPing cloud server only**. It is NOT propagated to the local Lumberjack edge servers.

Implications:

- Reports and queries against OnPing cloud will see the backfilled points.
- Anything reading directly from a Lumberjack (edge-side dashboards, control-parameter scripts that read history from local storage) will NOT see this data.
- Most edge devices do not sync historical data back from cloud, so the cloud and edge views will diverge for the imported window.

This is a property of the OnPing UI mass-import flow, not of this skill — the skill itself is offline and does no network calls.

## Reference template

`templates/MassWriteCSVImportExample.csv` is the canonical example shape. The validator's behavior is calibrated to round-trip this file byte-for-byte.
