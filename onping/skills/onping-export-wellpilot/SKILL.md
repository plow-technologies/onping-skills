---
name: onping-export-wellpilot
description: Download the OnPing wellpilot driver tag export as XLSX. Performs an authenticated GET and writes the file locally.
allowed-tools: Bash(uv run *)
---

# OnPing export-wellpilot

Downloads the tag (parameter) configuration for one OnPing wellpilot location as an `.xlsx` file. Performs a real authenticated GET against `GET /wellpilot/param/export/{location_id}/{filename}` and writes the response body to disk.

This skill is **read-only on the server**: it issues a GET, never mutates state.

## Source of truth

- Handler: `onping/Handler/WellPilot/Service.hs`
- Backed by: `_driver_export_routes/routes.py`

If the route changes, re-verify against the recorded handler location and update `_driver_export_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-wellpilot/scripts/export_tags.py \
    "$ACCESS_TOKEN" LOCATION_ID [FILENAME]
```

### Inputs

- `location_id` — int (LocationIdRef)
- `filename` — string — used in Content-Disposition


### Variants

- `--cards` — GET /wellpilot/card/export/{location_id}/{filename}  
  Exports pump cards (downhole card configs) instead of tag parameters.
### Options

- `--output PATH` — write the file to this path (default: `./wellpilot-<id>-<UTC-timestamp>.xlsx`)

## Output

On success, prints the absolute path of the saved file to stdout.

