---
name: onping-export-sparkplug-bridge
description: Download the OnPing sparkplug-bridge driver tag export as XLSX. Performs an authenticated GET and writes the file locally.
allowed-tools: Bash(uv run *)
---

# OnPing export-sparkplug-bridge

Downloads the tag (parameter) configuration for one OnPing sparkplug-bridge location as an `.xlsx` file. Performs a real authenticated GET against `GET /sparkplug/bridge/export/{lumberjack_serial}/{filename}` and writes the response body to disk.

This skill is **read-only on the server**: it issues a GET, never mutates state.

## Source of truth

- Handler: `onping/Handler/SparkplugBridge/ImportExport.hs`
- Backed by: `_driver_export_routes/routes.py`

If the route changes, re-verify against the recorded handler location and update `_driver_export_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-sparkplug-bridge/scripts/export_tags.py \
    "$ACCESS_TOKEN" LUMBERJACK_SERIAL [FILENAME]
```

### Inputs

- `lumberjack_serial` — int (LJSerial) — Lumberjack serial number, NOT a location ID
- `filename` — string — used in Content-Disposition


### Options

- `--output PATH` — write the file to this path (default: `./sparkplug-bridge-<id>-<UTC-timestamp>.xlsx`)

## Output

On success, prints the absolute path of the saved file to stdout.

> **Note:** Outlier: keyed by Lumberjack serial, not LocationIdRef. Endpoint is /sparkplug/bridge/export/, not /location/export/.
