---
name: onping-audit-pull
description: Pull the OnPing audit trail via POST /log/audit2/query — who changed a setpoint, alarm, site, or dashboard, and when. Read-only. Use when a question is about history and attribution rather than current state.
allowed-tools: Bash(uv run *)
---

# OnPing Audit Pull

Query the OnPing audit trail. Read-only — the route is a POST but mutates nothing, so there is no
`--yes` gate.

One route covers **all three audit backends** — the OnPing audit server, RTU Manager write audits, and
the OnPing authentication server. The handler fans out to them and normalizes 30 payload types into
a single view, which is why this skill wraps one route instead of three services.

| Artifact | Location |
| --- | --- |
| Route | `onping/config/routes` |
| Handler | `onping/Handler/Audit/AuditService.hs` |
| Query implementation | `onping-core Haxl audit client` |
| Type list route | `onping/config/routes` (not called — see below) |

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-audit-pull/scripts/audit_pull.py \
    "$ACCESS_TOKEN" --type controllogix --since 2026-08-01T00:00:00Z
```

Token comes from `onping-login`.

| Option | Default | Description |
| --- | --- | --- |
| `--type NAME` | *required* | Audit type wire name; repeatable |
| `--since ISO` | none | Lower bound on `edited-on` |
| `--until ISO` | none | Upper bound on `edited-on` |
| `--terms STR` | `""` | Relevance search terms, passed through verbatim |
| `--max-pages N` | 50 | Stop after N pages of 10 records |
| `--all` | off | Walk until exhausted, ignoring `--max-pages` |
| `--empty-page-limit N` | 10 | Give up after N *consecutive* empty pages |
| `--csv` | off | Emit CSV envelope columns |
| `--pretty` | off | Indent the JSON |
| `--output PATH` | stdout | Write to a file, only on success |
| `--list-types` | — | Print accepted type names and exit |

Timestamps are ISO 8601 and **must carry a timezone** (`Z` or an offset like `-05:00`). A naive
timestamp is rejected locally, because the server rejects it too
(`could not parse date: Unexpected end-of-input, expecting timezone`).

## Pagination: an empty page does NOT mean the end

Page size is **hardcoded to 10** server-side (`Client.hs`) and no request field reaches it, so
there is deliberately no `--size` flag. The script paginates for you.

The end-of-data signal is a **null `meta_nextKey`**, and it arrives one page *late* — the key is built
from the last hit of the page, so it stays non-null on the last page that still carries data:

| Request | Items | `meta_nextKey` |
| --- | --- | --- |
| 1–3 | 10 each | set |
| 4 | 5 | **still set** |
| 5 | 0 | null → done |

**The trap:** empty pages also appear *mid-walk*, and data resumes after them. Elasticsearch returns
audit *pointers*, which the handler then hydrates from three backends; a page whose 10 pointers all
fail to hydrate — permission-scoped away, or dangling — comes back empty while pagination is nowhere
near done.

Verified on `--type usertag`: the **first five pages are empty**, then data runs for 70 more pages.
Across 75 pages the runs of consecutive empty pages were 5, 1, 4, 7, 2, 1.

So a caller who stops at the first empty page reports **zero records** for `usertag` against a result
set that yields hundreds. Do not treat an empty page as the end.

`--empty-page-limit` (default 10, chosen above the longest observed run of 7) bounds the case where a
walk genuinely ends on a run of empties. Hitting it is reported as `stop_reason: "empty_run"` and
counts as **cut short, not complete** — it is a heuristic, and the server was still offering a key.

## Three different incomplete outcomes, and what each means

| Output state | Meaning | What to do |
| --- | --- | --- |
| `stop_reason: "max_pages"` | Hit the page cap | Pass `--all` or narrow the range |
| `stop_reason: "empty_run"` | Hit the consecutive-empty bound | Raise `--empty-page-limit` |
| `shortfall: true` | Walk *completed*; fewer records than the index counted | Nothing — they are not retrievable by you |

**`shortfall` is not a bug in this skill.** A completed walk can retrieve fewer records than
Elasticsearch counted, because the hydration step drops pointers that do not resolve. Verified:
`--type site --terms Example` retrieves **3 records against `meta_count: 4`**, reproducibly, ending
on a null key with no truncation. Don't go hunting a phantom pagination fault. It is suppressed when
the count is saturated (below) or when the walk was cut short, since truncation already explains a gap.

## `meta_count` saturates at 10000 — it is a ceiling, not a total

`server_reported_count` comes from Elasticsearch with `track_total_hits` at its default, so it stops
counting at 10000:

| Query (no range, no terms) | `meta_count` |
| --- | --- |
| `controllogix` | 10000 |
| `alarm` | 10000 |
| `location` | 10000 |
| `controllogix` + `site` + `alarm` + `location` | 10000 |
| `site` | **3311** |
| `controllogix`, one-day range | **267** |

`site` and the windowed query prove the figure is exact *below* the ceiling. Four unrelated queries
returning exactly `10000` is the ceiling.

**Reporting "10,000 audit records" is wrong.** When `count_saturated` is true the figure means
"≥ 10000". Narrow `--since`/`--until` to get an exact count. Always prefer the script's own
`retrieved` for "how many records do I actually have."

## Search terms rank — they do not filter

`--terms` becomes an Elasticsearch `query_string`, and the handler appends `type:<name>` terms for each
requested audit type (`Client.hs`). Terms affect **relevance, not membership**, which produces a
result that inverts the usual intuition:

| `--terms` (type `controllogix`, no range) | Records |
| --- | --- |
| `500008` | **35** |
| `zzzznope` | 0 |
| `500008 zzzznope` | **34** |
| `500008 OR zzzznope` | 35 |
| `500008 AND zzzznope` | 0 |

Adding a term that matches **nothing** *removed* a record. Paginating both sets fully shows why: the
35-record set was never a strict PID filter — it included a **different** PID (`500009`) matched by
full-text relevance, and the second term diluted scoring enough to push it out. Counts are stable
across reruns, so this is deterministic.

**Consequences for how you query:**

- **Type and time range are the real filters.** Narrowing the range is the reliable way to scope.
- **For an exact match** — "only records touching PID 500008" — post-filter the returned records on
  `json`, whose payload key varies by audit type (e.g. `controllogixWriteOnpingId`). The skill does not
  do this for you because the key differs per type.
- **Field-scoped search does not work here.** `nosuchfield:xyz` is not an error — it returns `200` with
  zero matches. And `edited-by:someone@example.com` does **not** filter: it returned records from three
  different users. Post-filter on `editedBy` instead.

The script passes terms through verbatim and never injects operators or quoting — rewriting them would
return something other than what you asked for, and would diverge from the OnPing UI that shares this
endpoint.

## You cannot query as another user

`auditquery_userIdent` is **required** by the request parser — omitting it is a 400 — and its value is
**discarded**: the handler overwrites it from the authenticated session (`AuditService.hs`). Sending
`nobody@example.com` returns results identical to sending `""`.

So there is deliberately **no flag** for it. A flag there would look like user filtering and would
silently return a full, unfiltered result set. To see one user's changes, post-filter on `editedBy`.

**Results are scoped to your permission groups** server-side (`buildUserFilter`, `Client.hs`), and
nothing in the response says anything was withheld. Two users running an identical query legitimately
get different results. An empty result means **"none visible to you"**, not "none exist".

## Audit types

Requesting at least one `--type` is required: an empty type list short-circuits server-side to an empty
result (`Client.hs`), which would look like "no audits exist". The script refuses it locally.

The 30 wire names below come from `GET /log/audit2/available-audits` (`config/routes`). This skill
embeds them rather than calling that route, because the list is a constant that changes only when
OnPing ships a new audit type.

| Wire name | Display | Wire name | Display |
| --- | --- | --- | --- |
| `group` | Groups | `opcua` | OPC UA Writes |
| `usertag` | User Settings | `chartreport` | Chart Report Writes |
| `alarm` | Alarms | `userauthentication` | Authentication |
| `masktype` | Masks | `virtualparameter` | Virtual Parameters |
| `callorder` | Call Orders | `unico` | Unico Writes |
| `location` | Locations | `lufkin` | Lufkin Writes |
| `site` | Sites | `mqttjson` | MqttJson Writes |
| `company` | Companies | `dnp3` | DNP3 Writes |
| `dashboard` | Dashboards | `tablesource` | Table Sources |
| `tflow` | TotalFlow Writes | `tableview` | Table Views |
| `micrologix` | Micrologix Writes | `groupcapability` | Group Capability |
| `bristol` | Bristol Writes | `logtablesource` | Log Table Sources |
| `manual` | Manual Writes | `logtableview` | Log Table Views |
| `roctlp` | Roc TLP Writes | `modbus` | Modbus Flexible Writes |
| `controllogix` | ControlLogix Writes | `hazardpro` | Hazard Pro Writes |

`vpalarm` is also accepted, though `available-audits` omits it.

**`alarm` already includes `vpalarm` records.** The handler injects `VPAlarmAudit` whenever
`AlarmAudit` is requested (`Client.hs`) — verified live — so requesting both types **duplicates**
records rather than adding coverage.

**Multi-type queries are not interleaved.** Results sort by `edited-on` descending across all requested
types, so a high-volume type fills every page and starves a low-volume one: `controllogix` + `site`
returned 10 `controllogix` and zero `site` on the first page. **Query a low-volume type on its own.**

## Time ranges

The three server variants have an **asymmetric payload shape**, which the script handles:

| Flags | Wire payload |
| --- | --- |
| `--since` only | `{"tag":"RangeGte","contents":"<t>"}` — a **bare string** |
| `--until` only | `{"tag":"RangeLte","contents":"<t>"}` — a **bare string** |
| both | `{"tag":"RangeGteLte","contents":["<t1>","<t2>"]}` — a **two-element array** |
| neither | `null` — unrestricted |

Narrowing the range is the primary tool for both an exact `meta_count` and keeping a walk inside the
page cap.

## Output

JSON by default:

```json
{
  "retrieved": 35,
  "server_reported_count": 35,
  "count_saturated": false,
  "truncated": false,
  "stop_reason": null,
  "empty_pages": 0,
  "shortfall": false,
  "items": [
    {
      "editedOn": "2026-08-10T14:04:51.364199Z",
      "editedBy": "someone@example.com",
      "type": "controllogix",
      "type_raw": "\"controllogix\"",
      "action": "Update",
      "description": "ControlLogix Writes - Afterflow Minimum Setpoint in Minutes",
      "json": {
        "controllogixWriteOnpingId": 500008,
        "controllogixWriteTagName": "AfterFlow_Min_SPT",
        "controllogixWriteVal": { "type": "Real", "value": 4 }
      }
    }
  ]
}
```

**`auditview_type` is double-encoded on the wire.** The server sends the literal 14 characters
`"\"controllogix\""` — quotes included — because `auditTypeFrontEndText` JSON-encodes the type and
stores the result in a text field (`AuditFrontEndResult.hs`). The script strips them into `type` and
keeps the server's value in `type_raw` so the transformation is auditable rather than silent.

`json` is the payload **verbatim**, and its shape varies by audit type — a ControlLogix write carries
`controllogixWrite*` keys, a site audit carries something else. Nothing normalizes across the 30 types.

`action` is one of `Create`, `Delete`, `Update`, `Revert`, `Unknown`. The server maps any unrecognized
action to `Unknown` (`AuditAction.hs`), so a new server-side action degrades rather than breaking.

`--csv` emits exactly six envelope columns — `editedOn`, `editedBy`, `type`, `action`, `description`,
`json` — with `json` as an embedded JSON string so CSV stays lossless. It does **not** expand the
payload into columns; there is no stable schema across 30 audit types.

## Examples

Recent ControlLogix writes at one site, exact count:

```bash
uv run ~/.claude/skills/onping-audit-pull/scripts/audit_pull.py "$ACCESS_TOKEN" \
  --type controllogix --since 2026-08-09T00:00:00Z --until 2026-08-10T00:00:00Z
```

Everything for one PID, as CSV — note terms rank, so verify by post-filtering:

```bash
uv run ~/.claude/skills/onping-audit-pull/scripts/audit_pull.py "$ACCESS_TOKEN" \
  --type controllogix --terms 500008 \
  --since 2025-08-10T00:00:00Z --until 2026-08-10T00:00:00Z \
  --csv --output writes.csv
```

Exact post-filter on the payload, which `--terms` cannot do:

```bash
uv run ~/.claude/skills/onping-audit-pull/scripts/audit_pull.py "$ACCESS_TOKEN" \
  --type controllogix --terms 500008 --since 2025-08-10T00:00:00Z \
  | jq '[.items[] | select(.json.controllogixWriteOnpingId == 500008)]'
```

One user's recent changes — post-filter, since `edited-by:` does not work:

```bash
uv run ~/.claude/skills/onping-audit-pull/scripts/audit_pull.py "$ACCESS_TOKEN" \
  --type controllogix --since 2026-08-01T00:00:00Z \
  | jq '[.items[] | select(.editedBy == "someone@example.com")]'
```

A sparse type where empty pages appear — needs a generous page budget:

```bash
uv run ~/.claude/skills/onping-audit-pull/scripts/audit_pull.py "$ACCESS_TOKEN" \
  --type usertag --max-pages 100
```

## Errors

All server errors arrive as `{"error": "<text>"}` and are surfaced verbatim.

| Condition | Behavior |
| --- | --- |
| Unknown `--type` | Caught locally; no request issued |
| No `--type` | Caught locally; no request issued |
| Naive or malformed timestamp | Caught locally; no request issued |
| `--since` after `--until` | Caught locally; no request issued |
| Expired token | Bounded retries, then exits non-zero naming the token as the likely cause |
| `500` | Exits non-zero; the real cause is logged server-side only and is not client-visible |

`--output` writes **only** after a fully successful walk; on any failure nothing is created.

## Related skills

- `onping-login` — get the access token
- `onping-search` — find sites, locations, and parameters when you don't have IDs
- `onping-report` — historical *parameter values*, as opposed to configuration-change history
- `cp-list`, `onping-hmi-export`, `onping-line-graph-get` — current state of the things this skill
  reports changes to
