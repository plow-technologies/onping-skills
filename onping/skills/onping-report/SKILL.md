---
name: onping-report
description: Generate a csv or xlsx report from OnPing historical data via the /tachdb/report endpoint. Use when the user needs historical parameter data exported as a csv file or an Excel (xlsx) workbook, bulk data downloads, or time-series reports.
allowed-tools: Bash(uv run *)
---

# OnPing Report

Ask OnPing for a csv or xlsx report of historical data and get the report URL. The server writes the file after it answers; see [Generation is asynchronous](#generation-is-asynchronous).

## Usage

```bash
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  START_DATE END_DATE PID [PID ...] \
  [--format csv|xlsx] [--step SECONDS] [--resolution N] [--title TITLE] [--vpid]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `START_DATE` | ISO 8601 start, in UTC (e.g. `2026-02-22T06:00:00Z`) |
| `END_DATE` | ISO 8601 end, in UTC (e.g. `2026-02-25T06:00:00Z`) |
| `PID ...` | One or more parameter IDs |

The access token is not an argument; see the note under Examples.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | csv | `csv` or `xlsx`. Any other value exits 2 and sends no request. For csv the request does not carry a `format` field (the server default is csv); for xlsx it sends `"format": "xlsx"` |
| `--step` | 60 | Step size in seconds (e.g. 3600 for hourly) |
| `--resolution` | 8 | Resolution exponent (2^N second rollup) |
| `--title` | "CSV Report" for csv, "Report" for xlsx | Report title (becomes part of the file name) |
| `--vpid` | off | Treat PIDs as virtual parameter IDs instead of regular PIDs |

The xlsx file is the server's own Office Open XML workbook (`.xlsx`, ECMA-376): one sheet named "report", row 1 holds location names, row 2 holds `Time` and the parameter descriptions, data starts at row 3. The skill does not write or edit the workbook.

## Output

Prints one URL to stdout and nothing else, for both formats. Diagnostics go to stderr.

The URL is an OnPing route, `/s3/availableFile/<user>/<date>/<file>`. It is not a pre-signed S3 URL. The route is served to the logged-in user who owns the file, so open it in a browser session of that user. Whether it also accepts a bearer token has not been checked, and this skill does not download the file.

Exit codes: 0 success; 1 a request error, a non-200 reply, a reply that is not JSON, or a decoded value that is not a URL; 2 a usage or token-shape error (nothing is sent).

## Generation is asynchronous

The server answers the request at once and builds the file afterwards, in a background task that only logs a failure. So:

- Exit 0 and a URL do not show that the file exists. A failed generation still leaves a URL.
- A request for a file that is not stored yet answers HTTP 200 with an HTML page that says "Failed to find Report, it may still be generating. Try again in a few moments." Wait and request the URL again.
- The 120-second timeout is the limit of the request to `/tachdb/report`. It is not a limit on generation, which can take longer for many PIDs or a long range.
- The download route labels the body `text/csv` even for xlsx. Save the response as bytes, never as text. An xlsx file starts with the two bytes `PK`; a body that does not is not a workbook (most likely the HTML page).

## Time zone

`START_DATE` and `END_DATE` are UTC. The row timestamps in the file are written by the server in America/Chicago local time (CST or CDT) and no offset is written, in csv and in xlsx. The zone cannot be chosen. Worked example: a request from `2026-02-22T06:00:00Z` to `2026-02-23T06:00:00Z` covers 00:00 to 00:00 in the file, because Chicago is UTC-6 in February; the same instants in July (UTC-5) start at 01:00 in the file. In xlsx the cell is an Excel date serial of that local time, shown as `MM/DD/YYYY HH:MM:SS`.

Inferred, not read from a report: when the clocks go back in autumn the local hour repeats, so a report across that change can hold duplicate timestamps.

## Known limits of the output

- The server does not quote or escape csv cells. A comma, quote or newline in a description or text value can break a row.
- A csv text value that starts with `=`, `+`, `-` or `@` is read as a formula by Excel. Text in the xlsx file is stored as a string and is not.
- Excel stops at 1,048,576 rows per sheet. Neither the skill nor the server guards the row count: a 1-second step over 13 days exceeds it. What the server does at the cap is inferred, not observed.
- PIDs the caller may not read are dropped by the server without a message. If none remain, the server answers 500.
- Inferred, not seen in the files read: the csv has no byte-order mark, so Excel may misread non-ASCII descriptions.
- `--vpid` applies to every PID given; a mix of regular and virtual PIDs needs two runs, and each run gives its own file.

## Examples

Single PID, hourly step, csv:
```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  "2026-02-24T06:00:00Z" "2026-02-25T06:00:00Z" 500019 \
  --step 3600 --resolution 8
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

An xlsx workbook:
```bash
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  "2026-02-24T06:00:00Z" "2026-02-25T06:00:00Z" 500019 \
  --step 3600 --format xlsx
```

Multiple PIDs with custom title:
```bash
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  "2026-02-22T06:00:00Z" "2026-02-25T06:00:00Z" 500019 500020 500021 \
  --step 3600 --resolution 8 --title "My Report"
```

Virtual parameter IDs:
```bash
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  "2026-02-22T06:00:00Z" "2026-02-25T06:00:00Z" 500112 --vpid
```

## Notes

- The script makes 3 attempts in total on an HTTP 3xx or 4xx reply, one straight after the other with no wait, then exits 1. Any other non-200 status is not retried.
- The server throttles report requests per user (30 in 2 minutes, read from source; the HTTP status of a throttled reply was not determined), so do not loop on failures.
- Tests (no network, no token): `cd onping/skills && uv run --with pytest --with requests pytest -q onping-report/tests`
