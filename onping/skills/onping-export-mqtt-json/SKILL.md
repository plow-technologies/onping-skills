---
name: onping-export-mqtt-json
description: Download the OnPing mqtt-json driver tag export as XLSX. Performs an authenticated GET and writes the file locally.
allowed-tools: Bash(uv run *)
---

# OnPing export-mqtt-json

Downloads the tag (parameter) configuration for one OnPing mqtt-json location as an `.xlsx` file. Performs a real authenticated GET against `GET /mqtt/json/param/export/{location_id}/{filename}` and writes the response body to disk.

This skill is **read-only on the server**: it issues a GET, never mutates state.

## Source of truth

- Handler: `onping/Handler/MQTT/JSON/Service.hs`
- Backed by: `_driver_export_routes/routes.py`

If the route changes, re-verify against the recorded handler location and update `_driver_export_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-mqtt-json/scripts/export_tags.py \
    "$ACCESS_TOKEN" LOCATION_ID [FILENAME]
```

### Inputs

- `location_id` — int (LocationIdRef)
- `filename` — string — used in Content-Disposition


### Variants

- `--all` — GET /mqtt/json/param/export/all  
  Developer-only; gated by MqttJsonDumpParametersFlag feature flag. Returns a JSON dump of all ungrouped locations' parameters, NOT XLSX.
### Options

- `--output PATH` — write the file to this path (default: `./mqtt-json-<id>-<UTC-timestamp>.xlsx`)

## Output

On success, prints the absolute path of the saved file to stdout.

