---
name: onping-pid-locate
description: Resolve OnPing PIDs to their location, site, company, driver source, and current value via POST /json/listers/v3/parameters. Read-only. Use when you have a bare PID — from an alarm, an audit record, or a control parameter — and need to know what and where it is.
allowed-tools: Bash(uv run *)
---

# OnPing PID Locate

Turn a bare **PID** into its location, site, company, driver source, unit, writeability, and current
value. **Read-only** — mutates nothing, so there is no `--yes` gate.

A plain-PID lookup costs **one** POST, however many PIDs you batch. A **VPID** lookup costs **two**:
the keyed route returns a virtual parameter's description but never its value, so the value comes from
a second, location-scoped call. See [How a VPID value is fetched](#how-a-vpid-value-is-fetched).

This is the PID-first lookup the rest of the catalog lacks. `onping-parameters` needs a location
*before* it can list parameters, and `onping-driver-resolve` needs a location refId — so answering
"which well is PID 500001?" used to mean guessing a location and listing it until the PID appeared.

| Artifact | Location |
| --- | --- |
| Route | `onping/config/routes` |
| Handler | `onping/Handler/JSON/Listers/ParameterLister.hs` |
| PID branch | `ParameterLister.hs` (`getTagInfoWithLocationByPIDs`) |

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-pid-locate/scripts/locate_pid.py "$ACCESS_TOKEN" 500001
```

Token comes from `onping-login`.

| Option | Default | Description |
| --- | --- | --- |
| `PID …` | *required* | One or more numeric ids; batched into a single request |
| `--vp` | off | **Treat the given ids as VPIDs.** Sends them as tagged `VPID` keys — a bare integer means PID and cannot address a virtual parameter — and fetches their values from the location-scoped route (**one extra request**) |
| `--names` | off | Resolve site and company refs to names (**2 extra calls**) |
| `--json` | off | Emit JSON keyed by PID |
| `--output PATH` | stdout | Write to a file |

Output:

```
500001  Well A-1 - ML Params  (location 20001)
        description : SAC: Operator Notes
        value       : 'Good arrivals for this well should be sub 50 mins.'  [OnPingText]
        source      : SourceManual
        site        : 3002
        company     : 100
        unit        : Pounds
        writeability: TagWriteable  (advisory — see onping-pid-write)
        slaveId/url : 1 / 192.0.2.11
        lastUpdate  : 1787328550
```

## A missing PID is silent — and means three different things

`applyMask` (`ParameterLister.hs`) keeps only tags whose `locationId` is in the caller's
authorized-location map and **drops the rest with no marker**. So these three are one
indistinguishable outcome:

- the PID does not exist
- the PID was deleted
- the PID is at a location this token cannot see

Verified live:

| Request | Response |
| --- | --- |
| `[99999999]` | `[]` |
| `[500001, 99999999, 500002]` | **2 items** |

**The trap:** the route answers `200` either way, so a caller that trusts the list length reports
"this PID doesn't exist" when it means "you can't see it" — or reports two results for three PIDs and
never notices.

This skill therefore emits **one entry per requested PID** with an explicit found state, and
**exits non-zero** when any is missing while still printing the ones that resolved:

```
99999999  NOT FOUND — not returned by the lister — the PID does not exist, has been
          deleted, or belongs to a location this token cannot see. The route drops all
          three identically with no marker, so they cannot be distinguished.
```

An empty result means **"nothing visible to you"**, not "nothing exists".

### There is a fourth outcome: the id could not be addressed at all

The three causes above describe a key that was addressed **correctly** and still came back absent.
A key this skill could not address is a different thing, and it gets different words and a different
exit code:

```
500109  NOT ADDRESSABLE — could not be addressed as a VPID by the route this skill
        used. This is a statement about this tool's reach, NOT about the parameter —
        it may well exist and be healthy. Nothing here says it does not exist.
```

A fifth, narrower outcome: a VPID whose description resolved but whose value no route would compute.
The value prints as `UNKNOWN`, never as `None` — because `None` reads as "this parameter has no value",
which is a quieter version of the same wrong answer.

| Outcome | Headline | Exit |
| --- | --- | --- |
| Resolved | the value | `0` |
| Addressed correctly, absent from the response | `NOT FOUND` + the three causes | `1` |
| Could not be addressed by key type | `NOT ADDRESSABLE` | `3` |
| Resolved, value not computable | `value : UNKNOWN` | `4` |

### Why this distinction has its own section

`NOT FOUND` on a mapped VPID was once read as **"the control loop is dead"** for four producing wells,
for 56 days. It was not. The raw output PID genuinely was stale — but the live decisions flowed through
mapped VPIDs that were **3 hours fresh**, and this skill could not address a VPID at all, so it
reported them as nonexistent and exited non-zero. Every layer of the output agreed on a wrong answer
about live equipment.

So: `NOT FOUND` is a statement about **this tool's reach**, not about the plant. If you are diagnosing
an outage, confirm you asked the question the tool can actually answer before believing a negative.

## Response order is not request order

Verified live: `[500001, 99999999, 500002]` came back **`[500002, 500001]`**.

Results are keyed by each item's own `tagInfo.parameterId`, never zipped positionally. A positional
zip would attribute one PID's location to another — and since `onping-pid-write --via-hmi` builds its
write envelope from this lookup, that mistake would aim a **write** at the wrong location while
reporting success. If you parse the raw route yourself, key by `parameterId`.

Duplicate PIDs collapse server-side (`[500001, 500001]` → 1 item); this skill de-duplicates input and
still reports one entry per PID you asked for.

## The value you get back is read-masked

Numeric values pass through the per-PID **read** mask (`tagInfoLocListDefaultTransformResult`,
`ParameterLister.hs`) before you see them; non-numeric values bypass it.

The **read mask and the write mask are separate configurations.** So the value here is not
necessarily the raw device value, and a round trip through `onping-pid-write --verify` is an
end-to-end check rather than a statement about either mask alone.

## How a VPID value is fetched

Two facts, both measured live, decide how `--vp` works.

**A bare integer means `KeyPID`.** `FromJSON OnpingKey` falls back to it for any non-object
(`Onping/Tag/Types.hs`), so a bare integer cannot address a virtual parameter — it silently asks
about a PID with that number instead. `--vp` therefore sends **tagged keys**:
`{"keyType":"VPID","keyValue":500109}`. Tagging is applied to both kinds unconditionally, since explicit
`PID` tagging returns a byte-identical item to a bare integer, and a mixed batch resolves both kinds in
one request.

**The keyed route never computes a VP result.** A tagged VPID comes back with the correct description
and `result.tag OnPingNoData`, `value null`, `lastUpdate 0` — under **all four** combinations of
`preq_optionVPCalculateResult` × `preq_optionExcludePID`. No flag changes it:

| Request `contents` | `preq_optionVP` | Items | `result.value` |
| --- | --- | --- | --- |
| `[500109]` (bare int) | `true` | **0** | — |
| `[{"keyType":"VPID","keyValue":500109}]` | `true` | 1 | **`null`** (`OnPingNoData`) |
| `[{"keyType":"PID","keyValue":500007}]` | `false` | 1 | correct |
| mixed VPID + PID | `true` | **2** | VP `null`, PID correct |

So values come from the **location-scoped** query — same path, different constructor:
`ParameterRequestLookupId` with `getLocationLookupList` and all three VP options true. That returns
**every** VP at the location (10 for location 20002), so the skill filters to the ids you asked for; a
request for one VPID reports one entry, not ten. Because that call sets `preq_optionExcludePID: true`
it is VP-only, which is what keeps the plain-PID path untouched by it.

**Cost:** one request for PIDs, two for VPIDs (plus one per additional distinct location).

**VP text values may carry surrounding whitespace.** VPID 500109 returns
`" [APPLIED] STABLE; … note.  "` — one leading space, two trailing. `--json` preserves it byte-for-byte;
do not assume trimmed strings.

## `tagLocations` is a list, but a PID always has exactly one

The v3 type is `TagInfoWithLocations` with `_tagLocations :: [Location]`, and the handler's docstring
says v3 exists to return multiple locations (`ParameterLister.hs`). For **PIDs** that is not yet
realized — `makeTagInfoWithLocations` wraps exactly one (`let locations = [location]`,
`:506-510`). Confirmed live across all 43 parameters at location 20001.

The plural is **supposed** to be real for VPIDs, which can in principle span locations — but that has
never been observed. Every VPID measured (500101–500110, at location 20002) also returned exactly one
location, including under the location-scoped route. Before 2026-08-21 the claim was untestable here,
because `--vp` could not surface a VPID at all.

So treat "a VPID may report several locations" as **unverified**, not established. This skill reads
`[0]` for a PID, reports every entry when a VPID does carry more than one, and reports an empty
`tagLocations` as not-found rather than crashing.

## `writeability` is advisory

Reported because it is useful, but it is **not** an interlock — no driver reads it from a write
request. See `onping-pid-write` for what actually decides whether a write succeeds. A `TagReadOnly`
tag is refused by the driver (verified: `400 Parameter is read only`), not by the field.

## Examples

Resolve several PIDs at once, with names:

```bash
uv run ~/.claude/skills/onping-pid-locate/scripts/locate_pid.py "$ACCESS_TOKEN" \
  500001 500002 500005 --names
```

Feed a location refId into the driver resolver — the natural next step:

```bash
LOC=$(uv run ~/.claude/skills/onping-pid-locate/scripts/locate_pid.py "$ACCESS_TOKEN" 500001 --json \
      | jq -r '.["500001"].location_id')
uv run ~/.claude/skills/onping-driver-resolve/scripts/resolve_driver.py "$ACCESS_TOKEN" "$LOC"
```

Read a **virtual** parameter — note `--vp`, without which the id is asked for as a PID and comes back
`NOT ADDRESSABLE`:

```bash
uv run ~/.claude/skills/onping-pid-locate/scripts/locate_pid.py "$ACCESS_TOKEN" 500109 500103 --vp
```

Which PIDs in a batch are visible to this token:

```bash
uv run ~/.claude/skills/onping-pid-locate/scripts/locate_pid.py "$ACCESS_TOKEN" \
  500001 99999999 500002 --json | jq 'to_entries | map({pid: .key, found: .value.found})'
```

## Errors

| Condition | Behavior |
| --- | --- |
| Non-integer PID | Caught locally; no request issued |
| No PID | argparse usage error; no request issued |
| Any PID not found | Resolved PIDs printed, then **exit 1** |
| Id not addressable by key type | `NOT ADDRESSABLE`, never a nonexistence claim; **exit 3** |
| VPID resolved but value not computable | `value : UNKNOWN` with the reason; **exit 4** |
| Expired token | Auth-redirect / HTML login detected on **every** call, including the location-scoped one; exits non-zero naming the token |
| `{"error": …}` body | Surfaced verbatim |

A non-zero exit alongside `NOT FOUND` reads as confirmation that a parameter does not exist. That is
why "could not address" (3) and "value unknown" (4) have their own codes: a caller checking only the
status can still tell the three apart.

## Related skills

- `onping-login` — get the access token
- `onping-pid-write` — write a value to a PID you resolved here
- `onping-driver-resolve` — refId → driver slug; the step *after* this one
- `onping-parameters` — list parameters when you have a **location** rather than a PID
- `onping-audit-pull` — who changed this PID, and when
