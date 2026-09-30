---
name: lj-restore-backups
description: List available backup files for a lumberjack. Use when the user wants to see what backups exist for a specific lumberjack ID on a device.
allowed-tools: Bash(uv run *)
---

# Lumberjack Restore — List Backups

List available backup files for a specific lumberjack on a device running the lumberjack-restore-server.

## Related Skills

- **lj-restore-list** — List all lumberjack folders with backups on the device
- **lj-restore-run** — Trigger a restore from a backup
- **lj-profile** — Look up the Lumberjack IP address from an OnPing location ID

## Typical Workflow

```
1. List lumberjack folders (lj-restore-list) -> pick a lumberjack ID
2. List backups for that lumberjack (lj-restore-backups)
3. Restore from a chosen backup (lj-restore-run)
```

## Usage

Requires the device IP and a lumberjack ID (the numeric part from the folder name, e.g. "1001" from "lumberjack-1001/").

```bash
uv run ~/.claude/skills/lj-restore-backups/scripts/list_backups.py 192.0.2.10 1001
```

With a custom port:

```bash
uv run ~/.claude/skills/lj-restore-backups/scripts/list_backups.py 192.0.2.10 1001 --port 8080
```

## Output

JSON array of backup filenames:

```json
["backupStates-25-07-16.tar.gz", "backupStates-25-07-15.tar.gz"]
```

Empty lines in the server response are filtered out.

## Error Handling

- Network errors and non-200 HTTP responses are reported to stderr
- Retries up to 3 times on 3xx/4xx status codes before failing
- Empty responses produce an empty JSON array
