---
name: onping-export-micrologix
description: Download the OnPing micrologix driver tag export as XLSX. Performs an authenticated GET and writes the file locally.
allowed-tools: Bash(uv run *)
---

# OnPing export-micrologix

Downloads the tag (parameter) configuration for one OnPing micrologix location as an `.xlsx` file. Performs a real authenticated GET against `GET /micrologix/export/params/{location_id}/{filename}` and writes the response body to disk.

This skill is **read-only on the server**: it issues a GET, never mutates state.

## Source of truth

- Handler: `onping/Handler/Micrologix/ImportExport.hs`
- Backed by: `_driver_export_routes/routes.py`

If the route changes, re-verify against the recorded handler location and update `_driver_export_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-micrologix/scripts/export_tags.py \
    "$ACCESS_TOKEN" LOCATION_ID [FILENAME]
```

### Inputs

- `location_id` — int (LocationIdRef) — OnPing location for the Micrologix device
- `filename` — string — handler ignores this (any non-empty token works, e.g. 'tags.xlsx')


### Options

- `--output PATH` — write the file to this path (default: `./micrologix-<id>-<UTC-timestamp>.xlsx`)

## Output

On success, prints the absolute path of the saved file to stdout.

> **Caveat:** the OnPing handler declares `Content-Type: text/csv` but the body is real XLSX. The downloader treats it as opaque binary; the resulting file is a valid `.xlsx`.
