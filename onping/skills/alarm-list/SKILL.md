---
name: alarm-list
description: List alarm configurations from OnPing. Use when the user asks about alarms, alarm setpoints, or alarm configurations for sites/locations.
allowed-tools: Bash(uv run *)
---

# OnPing Alarm List

List alarm configurations from OnPing, optionally filtered by site, location, or company.

## Usage

Requires a valid access token. Filters are optional — omitting all filters returns all alarms.

```bash
uv run ~/.claude/skills/alarm-list/scripts/list_alarms.py "$ACCESS_TOKEN"
```

Filter by site (uses MongoKey from `onping-sites` `key` field):

```bash
uv run ~/.claude/skills/alarm-list/scripts/list_alarms.py "$ACCESS_TOKEN" --site o00000000000000000000000c
```

Filter by location (uses MongoKey from `onping-locations` `key` field):

```bash
uv run ~/.claude/skills/alarm-list/scripts/list_alarms.py "$ACCESS_TOKEN" --location o000000000000000000000025
```

Multiple filters can be combined, and each filter flag can be repeated:

```bash
uv run ~/.claude/skills/alarm-list/scripts/list_alarms.py "$ACCESS_TOKEN" --site o00000000000000000000000c --site o00000000000000000000000d
```

Combined login + list pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/alarm-list/scripts/list_alarms.py "$ACCESS_TOKEN" --site o00000000000000000000000c
```

## Inputs

| Argument | Required | Description |
|---|---|---|
| `access_token` | Yes | OnPing OAuth2 access token (positional) |
| `--site KEY` | No | Site MongoKey to filter by (repeatable) |
| `--location KEY` | No | Location MongoKey to filter by (repeatable) |
| `--company KEY` | No | Company MongoKey to filter by (repeatable) |

**Note:** Filter values are MongoKey strings (e.g. `o00000000000000000000000c`), not numeric IDs. Get these from the `key` field in `onping-sites` or `onping-locations` output.

## Output

On success, outputs a JSON array of alarm objects to stdout. Each alarm object contains fields such as:

- `alarmMixId` — unique alarm ID
- `alarmName` — alarm name
- `alarmActive` — whether the alarm is active
- `alarmTag` — associated parameter info (tagInfo + tagLocation)
- `onpingKey` — the monitored parameter key (`keyType` + `keyValue`)
- `callOrderId` — associated call order ID
- `callOrderConfig` — call order details including `orderName` and `userNames`
- `tripTime`, `clearTime`, `recallTime` — timing configuration in seconds
- `groupId` — alarm group reference

Only successful alarm lookups (`Right` values) are included; `Left` error entries are filtered out.

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
