---
name: alarm-call-order
description: List alarm call orders and notification groups from OnPing. Use when the user asks about alarm call lists, notification recipients, or who gets called when an alarm triggers.
allowed-tools: Bash(uv run *)
---

# OnPing Alarm Call Orders

List alarm call order assignments from OnPing. Fetches alarms and groups them by call order ID to show which alarms belong to which notification group.

## Usage

Requires a valid access token. Filter by site, location, or company.

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/alarm-call-order/scripts/list_call_orders.py "$ACCESS_TOKEN" --site 3003
```

Filter by location:

```bash
uv run ~/.claude/skills/alarm-call-order/scripts/list_call_orders.py "$ACCESS_TOKEN" --location 20009
```

## Inputs

| Argument | Required | Description |
|---|---|---|
| `access_token` | Yes | OnPing OAuth2 access token (positional) |
| `--site SITE_ID [...]` | No | Site IDs to filter by |
| `--location LOCATION_ID [...]` | No | Location IDs to filter by |
| `--company COMPANY_ID [...]` | No | Company IDs to filter by |

## Output

JSON object with two keys:

- `callOrders` — alarms grouped by call order ID, each with a list of `{alarmName, alarmMixId}`
- `rawAlarms` — full alarm objects from the API

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
