---
name: onping-report
description: Generate a CSV report from OnPing historical data via the /tachdb/report endpoint. Use when the user needs historical parameter data exported as CSV, bulk data downloads, or time-series reports.
allowed-tools: Bash(uv run *)
---

# OnPing Report

Generate a CSV report from OnPing historical data and get a download URL.

## Usage

```bash
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  ACCESS_TOKEN START_DATE END_DATE PID [PID ...] \
  [--step SECONDS] [--resolution N] [--title TITLE] [--vpid]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `ACCESS_TOKEN` | Bearer token from `onping-login` |
| `START_DATE` | ISO 8601 start (e.g. `2026-02-22T06:00:00Z`) |
| `END_DATE` | ISO 8601 end (e.g. `2026-02-25T06:00:00Z`) |
| `PID ...` | One or more parameter IDs |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--step` | 60 | Step size in seconds (e.g. 3600 for hourly) |
| `--resolution` | 8 | Resolution exponent (2^N second rollup) |
| `--title` | "CSV Report" | Report title (used in filename) |
| `--vpid` | off | Treat PIDs as virtual parameter IDs instead of regular PIDs |

## Output

Prints a pre-signed S3 download URL to stdout. The URL points to a CSV file that can be downloaded directly (no auth needed).

## Examples

Single PID, hourly step:
```bash
TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  "$TOKEN" "2026-02-24T06:00:00Z" "2026-02-25T06:00:00Z" 500019 \
  --step 3600 --resolution 8
```

Multiple PIDs with custom title:
```bash
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  "$TOKEN" "2026-02-22T06:00:00Z" "2026-02-25T06:00:00Z" 500019 500020 500021 \
  --step 3600 --resolution 8 --title "My Report"
```

Virtual parameter IDs:
```bash
uv run ~/.claude/skills/onping-report/scripts/generate_report.py \
  "$TOKEN" "2026-02-22T06:00:00Z" "2026-02-25T06:00:00Z" 500112 --vpid
```

## Notes

- Reports with many PIDs can take over a minute to generate; the script uses a 120s timeout
- The script retries up to 3 times on auth/client errors (HTTP 3xx/4xx)
- The returned URL is typically a pre-signed S3 URL that expires after some time
