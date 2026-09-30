---
name: onping-export-lumberjack-remote
description: Download the OnPing lumberjack-remote driver tag export as XLSX. Performs an authenticated GET and writes the file locally.
allowed-tools: Bash(uv run *)
---

# OnPing export-lumberjack-remote

Downloads the tag (parameter) configuration for one OnPing lumberjack-remote location as an `.xlsx` file. Performs a real authenticated GET against `GET /lumberjack/remote/export-v2/params/{location_id}/{filename}` and writes the response body to disk.

This skill is **read-only on the server**: it issues a GET, never mutates state.

## Source of truth

- Handler: `onping/Handler/LumberjackRemote/ImportExport.hs`
- Backed by: `_driver_export_routes/routes.py`

If the route changes, re-verify against the recorded handler location and update `_driver_export_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-lumberjack-remote/scripts/export_tags.py \
    "$ACCESS_TOKEN" LOCATION_ID [FILENAME]
```

### Inputs

- `location_id` — int (LocationIdRef)
- `filename` — string — used in Content-Disposition


### Variants

- `--v1` — GET /lumberjack/remote/export/params/{location_id}/{filename}  
### Options

- `--output PATH` — write the file to this path (default: `./lumberjack-remote-<id>-<UTC-timestamp>.xlsx`)

## Output

On success, prints the absolute path of the saved file to stdout.

> **Caveat:** the OnPing handler declares `Content-Type: text/csv` but the body is real XLSX. The downloader treats it as opaque binary; the resulting file is a valid `.xlsx`.

> **Note:** V2 follows RocTlp pattern: converts parameters to LJRemoteItems before export.
