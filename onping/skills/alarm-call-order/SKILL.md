---
name: alarm-call-order
description: List alarm call orders and notification groups from OnPing. Use when the user asks about alarm call lists, notification recipients, or who gets called when an alarm triggers.
allowed-tools: Bash(uv run *)
---

# OnPing Alarm Call Orders

List alarm call order assignments from OnPing (read-only). Fetches alarms through `POST /alarmmix/lister`, groups them by call order ID, and shows each call order's recipients in call order: user, repeat count and notification flags.

Since onping #16132 (2026-09-16) a call order is one `orderEntries` list, not the old parallel `userNames` / `repeatCounts` lists. A server that still sends the old shape is refused with exit 3.

## Usage

Requires a valid access token. Filter by site, location, or company. The server's filters are typed as MongoKeys (`SiteId`, `LocationId`, `CompanyId`: `o` plus 24 hex digits, as `alarm-list` and `onping-sites` print them), so the examples use that form.

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/alarm-call-order/scripts/list_call_orders.py "$ACCESS_TOKEN" --site o00000000000000000000000c
```

Filter by location:

```bash
uv run ~/.claude/skills/alarm-call-order/scripts/list_call_orders.py "$ACCESS_TOKEN" --location o00000000000000000000000d
```

## Inputs

| Argument | Required | Description |
|---|---|---|
| `access_token` | Yes | OnPing OAuth2 access token (positional) |
| `--site SITE_ID [...]` | No | Site MongoKeys to filter by |
| `--location LOCATION_ID [...]` | No | Location MongoKeys to filter by |
| `--company COMPANY_ID [...]` | No | Company MongoKeys to filter by |

| Environment | Default | Description |
|---|---|---|
| `ONPING_BASE_URL` | `https://onping.plowtech.net` | OnPing server to query. Set it to target a non-production environment. |

## Output

A JSON object on stdout:

- `callOrders`: an object keyed by call order ID. Each value has:
  - `orderName`: the call order's name.
  - `entries`: the recipients in call order, each `{userId, userName, repeatCount, notificationFlags}`. `notificationFlags` is `{notificationFlagCall, notificationFlagEmail, notificationFlagText, notificationFlagTextBroadcast}`, or `null` when the entry follows the account default.
  - `userNames`, `repeatCounts`: derived from `entries`, in the same order. Kept for older consumers.
  - `alarms`: the alarms on this call order, each `{alarmName, alarmActive, alarmMixId}`. An alarm whose copy of the call order differs from the one shown also has `configConflict: true`.
- `totalAlarms`: the number of alarms (`Right` elements) read.
- `errors`: a list of `{tag, contents}` objects of two kinds:
  - the alarm lookup errors (`Left` elements, `AlarmMixError`) as the server sent them, for example `AlarmCallOrderNotFound`;
  - `CallOrderConflict` (added by the skill, not the server): two alarms on one `callOrderId` carry different copies of the call order. `contents` is `{callOrderId, keptAlarmMixId, alarmMixId, differences}`. `keptAlarmMixId` is the first alarm, whose copy `callOrders` shows. Each difference is `{field, kept, other}`, where `field` is `orderName`, `entries[i].userId`, `entries[i].userName`, `entries[i].repeatCount`, `entries[i].notificationFlags` or `entries.length`. Alarm IDs keep their tag, for example `AlarmMixIdVP:o...`, so a regular and a VP alarm with the same oid are told apart.

An empty call order (`orderEntries: []`) appears with `entries: []` and a note on stderr. It is not an error. Stderr also reports the number of `Left` errors and of conflicts, and describes each conflict.

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | HTTP error, network error, `{"error": msg}` body, auth failure or missing permission. Long error bodies are cut to their first 500 characters on stderr. The script makes one request and does not retry. A 403 whose body is the server's error-log status (`"ErrorLogCompleted"` or `"ErrorLogFailed"`) is a permission denial: the token was accepted, but the account cannot see a requested site, location or company. It prints "the account lacks permission ..." and does not suggest onping-login. Any other 401 or 403, or a 3xx (login redirect), prints "token expired or invalid; run onping-login". |
| 2 | Bad arguments |
| 3 | Unrecognised response shape, including a 200 body that is not JSON (an HTML login page, for example; the message suggests onping-login and shows the first 500 characters). Nothing is printed on stdout. For a problem inside an alarm, stderr names the element index, the alarm (`alarmMixId` with its tag), the call order (`callOrderId`, or that it is missing), the bad field (`orderEntries[i]` for an entry) and the keys found. For a problem outside an alarm, it names the element index and the keys found. A `callOrderConfig` with `userNames` and no `orderEntries` means the server predates onping #16132 (before 2026-09-16). |
| 4 | The listing was printed in full, but at least one `CallOrderConflict` is in `errors`: alarms on the same `callOrderId` carry a different `orderName` or `entries`. `callOrders` shows the first alarm's copy; stderr names the call order, both alarms and each differing field. |

Exit 3 covers: the body is not JSON or not a list; an element is neither `{"Right": ...}` nor `{"Left": ...}`; a `Left` value is not an object with exactly a string `tag` and a `contents`; an alarm lacks a string `callOrderId`; `callOrderConfig` is missing or not an object; `orderName` is missing or not a string; `orderEntries` is missing or not a list; an entry lacks a string `entryConfigUserId`, a string `entryConfigUserName` or an integer `entryConfigRepeatCount`; `entryConfigNotificationFlags` is neither `null` nor an object with the four boolean flags. Alarms that disagree on one call order exit 4, not 3.

