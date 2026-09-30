---
name: onping-export-singlewell-manual
description: Download the OnPing singlewell-manual driver tag export as XLSX. Performs an authenticated GET and writes the file locally.
allowed-tools: Bash(uv run *)
---

# OnPing export-singlewell-manual

Downloads the tag (parameter) configuration for one OnPing singlewell-manual location as an `.xlsx` file. Performs a real authenticated GET against `GET /v2/singlewellmanual/export/params/{location_id}/{filename}` and writes the response body to disk.

This skill is **read-only on the server**: it issues a GET, never mutates state.

## Source of truth

- Handler: `onping/Handler/SingleWellManual/ImportExportV2.hs`
- Backed by: `_driver_export_routes/routes.py`

If the route changes, re-verify against the recorded handler location and update `_driver_export_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-singlewell-manual/scripts/export_tags.py \
    "$ACCESS_TOKEN" LOCATION_ID [FILENAME]
```

### Inputs

- `location_id` — int (LocationIdRef)
- `filename` — string — handler ignores this


### Variants

- `--v1` — GET /singlewellmanual/export/params/{location_id}/{filename}  
  V1 filters parameters to ManualValueDouble / ManualValueAsciiText24 / NaNTagValue only.
### Options

- `--output PATH` — write the file to this path (default: `./singlewell-manual-<id>-<UTC-timestamp>.xlsx`)

## Output

On success, prints the absolute path of the saved file to stdout.

> **Caveat:** the OnPing handler declares `Content-Type: text/csv` but the body is real XLSX. The downloader treats it as opaque binary; the resulting file is a valid `.xlsx`.
