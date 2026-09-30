---
name: lj-restore-run
description: Restore a lumberjack from a backup. Use when the user wants to restore a specific backup file onto a lumberjack device. This is a destructive operation that stops services and overwrites state.
allowed-tools: Bash(uv run *)
---

# Lumberjack Restore — Run

Trigger a restore operation on a lumberjack device. This downloads a backup from S3, stops running services, and restores the saved state files.

**Warning:** This is a destructive operation. It kills running services on the device and overwrites files in `/home/lumberjack/Private/`.

## Related Skills

- **lj-restore-list** — List all lumberjack folders with backups on the device
- **lj-restore-backups** — List backup files for a specific lumberjack
- **lj-profile** — Look up the Lumberjack IP address from an OnPing location ID

## Typical Workflow

```
1. List lumberjack folders (lj-restore-list) -> e.g. "lumberJack-1002/"
2. List backups for that lumberjack (lj-restore-backups) -> e.g. "backupStates-25-07-16.tar.gz"
3. Restore from the chosen backup (lj-restore-run)
```

## Usage

Requires the device IP, the lumberjack folder name (as returned by `lj-restore-list`), and the backup filename (as returned by `lj-restore-backups`).

```bash
uv run ~/.claude/skills/lj-restore-run/scripts/restore.py 192.0.2.10 "lumberJack-1002/" "backupStates-25-07-16.tar.gz"
```

With a custom port:

```bash
uv run ~/.claude/skills/lj-restore-run/scripts/restore.py 192.0.2.10 "lumberJack-1002/" "backupStates-25-07-16.tar.gz" --port 8080
```

## Full Workflow Example

Discover the device IP via OnPing, then restore:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/lj-profile/scripts/lj_profile.py "$ACCESS_TOKEN" 20004
# Note the lumberjackUrl field from the output, then:
uv run ~/.claude/skills/lj-restore-list/scripts/list_lumberjacks.py 192.0.2.10
uv run ~/.claude/skills/lj-restore-backups/scripts/list_backups.py 192.0.2.10 1001
uv run ~/.claude/skills/lj-restore-run/scripts/restore.py 192.0.2.10 "lumberjack-1001/" "backupStates-25-07-16.tar.gz"
```

## Output

The server response text describing the restore outcome.

## Error Handling

- Network errors and non-200 HTTP responses are reported to stderr
- Retries up to 3 times on 3xx/4xx status codes before failing
- The restore may take time as it downloads from S3 and restarts services; the script uses a 120-second timeout
