---
name: lj-restore-list
description: List lumberjack backup folders on a device. Use when discovering which lumberjacks have backups available at a given IP address.
allowed-tools: Bash(uv run *)
---

# Lumberjack Restore — List

List lumberjack folders that have backups available on a device running the lumberjack-restore-server.

## Related Skills

- **lj-profile** — Look up the Lumberjack IP address from an OnPing location ID
- **onping-locations** — Fetch locations for a site (to find location IDs and IPs)
- **lj-restore-backups** — List backup files for a specific lumberjack
- **lj-restore-run** — Trigger a restore from a backup

## Typical Workflow

```
1. (Optional) Find the device IP via OnPing:
   Login (onping-login) -> access token
   Look up location (onping-locations) or profile (lj-profile) -> device IP
2. List lumberjack folders with backups (lj-restore-list)
3. List backups for a specific lumberjack (lj-restore-backups)
4. Restore from a chosen backup (lj-restore-run)
```

## Usage

Requires the device IP address. Port defaults to 13201.

```bash
uv run ~/.claude/skills/lj-restore-list/scripts/list_lumberjacks.py 192.0.2.10
```

With a custom port:

```bash
uv run ~/.claude/skills/lj-restore-list/scripts/list_lumberjacks.py 192.0.2.10 --port 8080
```

## Output

JSON array of folder names representing lumberjacks with available backups:

```json
["lumberjack-1001/", "lumberJack-1002/", "v-lumberjack-1003/"]
```

## Error Handling

- Network errors and non-200 HTTP responses are reported to stderr
- Retries up to 3 times on 3xx/4xx status codes before failing
- Invalid JSON responses are reported with the raw response body
