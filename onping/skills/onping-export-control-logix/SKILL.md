---
name: onping-export-control-logix
description: Download the OnPing control-logix driver tag export as XLSX. Performs an authenticated GET and writes the file locally.
allowed-tools: Bash(uv run *)
---

# OnPing export-control-logix

Downloads the tag (parameter) configuration for one OnPing control-logix location as an `.xlsx` file. Performs a real authenticated GET against `GET /control/logix/params/export/{location_id}/{filename}` and writes the response body to disk.

This skill is **read-only on the server**: it issues a GET, never mutates state.

## Source of truth

- Handler: `onping/Handler/ControlLogix/ImportExport.hs`
- Backed by: `_driver_export_routes/routes.py`

If the route changes, re-verify against the recorded handler location and update `_driver_export_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-control-logix/scripts/export_tags.py \
    "$ACCESS_TOKEN" LOCATION_ID [FILENAME]
```

### Inputs

- `location_id` — int (LocationIdRef)
- `filename` — string — handler ignores this


### Options

- `--output PATH` — write the file to this path (default: `./control-logix-<id>-<UTC-timestamp>.xlsx`)

## Output

On success, prints the absolute path of the saved file to stdout.

> **Caveat:** the OnPing handler declares `Content-Type: text/csv` but the body is real XLSX. The downloader treats it as opaque binary; the resulting file is a valid `.xlsx`.

> **Note:** Path order differs from siblings: '/params/export/' not '/export/params/'.
