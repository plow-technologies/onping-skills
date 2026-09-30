---
name: onping-pid-write
description: Write a typed value to an OnPing PID via POST /source/param/write-onping-result (or writeV2 with --via-hmi). MUTATING — requires --yes. Use when setting a setpoint, an operator note, or any live parameter value. Writes are asynchronous; --verify polls before reporting.
allowed-tools: Bash(uv run *)
---

# OnPing PID Write

Write a value to a PID. **MUTATING** — nothing happens without `--yes`.

This is the catalog's first skill that writes a **live value to physical equipment**. Every other
mutating OnPing skill changes configuration. `onping-mass-write` is not an exception: it builds a CSV
for the UI and makes no HTTP call.

| Artifact | Location |
| --- | --- |
| Default route | `config/routes` → `Handler/Source/Params.hs` |
| `--via-hmi` route | `config/routes` → `Handler/Hmi/HmiViewer.hs` |
| Dispatch | `onping-core Haxl write dispatch` |
| Write mask | `onping-core write-mask module` |

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# dry run first — prints the resolved location NAME and the mask verdict
uv run ~/.claude/skills/onping-pid-write/scripts/write_pid.py "$ACCESS_TOKEN" 500005 --value 42

# then commit
uv run ~/.claude/skills/onping-pid-write/scripts/write_pid.py "$ACCESS_TOKEN" 500005 --value 42 --verify --yes
```

| Option | Default | Description |
| --- | --- | --- |
| `PID` | *required* | The numeric PID to write |
| `--value F` | — | Write an `OnPingDouble` (**masked**) |
| `--int N` | — | Write an `OnPingInt` (**masked**) |
| `--text S` | — | Write an `OnPingText` (not masked) |
| `--bool true\|false` | — | Write an `OnPingBool` (not masked) |
| `--via-hmi` | off | Use `writeV2` instead of the default route — see below |
| `--verify` | off | Poll for the value to land, then report sent vs. landed |
| `--verify-timeout S` | 15 | How long to wait for an async write to become readable |
| `--verify-interval S` | 1 | Seconds between read-back polls |
| `--names` | off | Resolve site/company names for the report |
| `--json` | off | Emit a JSON report |
| `--yes` | off | **Required to actually write** |

Exactly one value flag is required and they are mutually exclusive.

## The type is always explicit — never inferred

`--value 4`, `--int 4`, and `--text 4` take genuinely different paths: the first two are mask-eligible,
the third is not, and text into a numeric parameter is rejected. Inferring a type from the shape of
the input would make `--text 0` and `--text off` behave differently for the same intent, so the flag
decides. `--text 0` writes the **string** `"0"`.

The other 11 `OnPingResult` constructors are deliberately not emittable: `OnPingNaN`, `OnPingNoData`,
`OnPingNotYetPolled`, `OnPingMaskUnit`, `OnPingLocal` are *states* rather than values, and
`OnPingSource`, `OnPingEpoch`, `OnPingWord16/32/64`, `OnPingDownHoleCard` have no established write
use through these routes.

A current-type/new-type mismatch is **warned about, not blocked** — a `SourceManual` text tag
legitimately holds text, and only the driver knows what it accepts:

```
WARNING : current value is OnPingDouble but writing OnPingText; if this
          parameter is numeric, expect WriteErrorDoubleConversion
```

## Why this is not the route your browser uses

The OnPing UI writes through `POST /hmi/devices/writeV2`, which takes a whole ten-field `TagInfo` and
**trusts the routing fields inside it**. `postWriteDeviceV2R` rewrites only the username and forwards
the rest; nothing re-derives `locationId` or `localParameterId` from `parameterId`. Downstream,
`writeOnpingParameter'` dispatches on `(sourceId, result)` and hands your `locationId` to whichever
driver `sourceId` names.

So on that route:

- a stale or wrong `localParameterId` sends the write **down the wrong protocol driver**;
- a wrong `locationId` sends it **to another location**.

Neither is validated, and the permission check authorizes the *supplied* location — so with rights to
both you get a success status. For an agent assembling JSON from a lister response, that is a
foot-gun with no feedback.

`POST /source/param/write-onping-result` has no such surface. It takes `[pid, value]`, looks the PID
up server-side, and builds the envelope itself — hardcoding `companyId`/`siteId` to `0` and
`description`/`unit`/`lastUpdate` to placeholders, which proves those seven fields are inert on the
write path. **Two inputs you cannot get wrong instead of ten you can.**

### When you do need `--via-hmi`

One case: **writing a string to a TotalFlow parameter.** `writeOnpingParameter'` (V2) has a
`SourceTotalFlow` + `OnPingText` arm that `writeOnpingParameter` (V1) lacks entirely, so V1 falls
through to `"incorrect protocol type"`. That single arm is the *only* behavioral difference between
`/hmi/devices/write` and `writeV2` — which is why V2 is a strict superset and there is no `--v1` flag.

Even with `--via-hmi`, this skill builds the envelope from the **live lookup**, never from
user-supplied routing fields. The flag changes the route, not who resolves the routing.

Note the different success codes: the default route returns **`201`**, `--via-hmi` returns `200`. A
`200`-only check would report every default-route write as a failure.

## Writes are asynchronous — a success status is not a landed value

Measured live: the write returned `201` in **0.44s**, and the new value was not readable for
**~2.9s**. During that window the lister still returns the **old** value and `lastUpdate` still holds
its pre-write timestamp.

So a single immediate read-back reports the previous value and misclassifies a perfectly good write as
`differs`. `--verify` instead **polls until `lastUpdate` advances**, then compares. It cannot poll for
value *equality*, because a masked write legitimately lands a different value and equality might never
arrive.

## Numeric writes pass through a write mask that can change the value

`tagInfoListDefaultTransformResultWithWriteMask` looks up a per-PID mask script and **replaces** your
value with its output. On a mask error it falls back to the unmasked value **silently**
(`either (const defaultVal) …`, `Mask.hs`).

| Value type | Masked? |
| --- | --- |
| `OnPingDouble`, `OnPingInt` | **yes** |
| `OnPingWord16/32/64` (default route) | **yes** |
| `OnPingText`, `OnPingBool` | no — `buildTag` short-circuits them |

An empty mask result is its own failure (`WriteErrorEmptyMasks` / `"problem occured applying write
mask"`) and means **nothing was written**.

**The write mask and the read mask are different configurations.** The write path applies the write
mask; the read-back reads through the *read* mask (`ParameterLister.hs`). So `--verify` is an
end-to-end round-trip check and **cannot** tell you the write mask was the identity.

### The three `--verify` outcomes

| Outcome | Meaning | Exit |
| --- | --- | --- |
| `match` | Landed value equals what you sent | 0 |
| `differs` | Landed value differs; both are shown | **0** |
| `unverified` | The write was accepted; the value was not confirmable | 1 |

`differs` is **not an error** — a scaling mask makes it the expected result. Three things explain it:
the write mask, the read mask, or driver quantization (a `Double` into a 16-bit register).

`unverified` means exactly what it says. The write **was accepted**; only the confirmation failed.
Nothing in that output says the write did not happen, because it probably did — verified live: a write
reported `unverified` under a zero timeout and the value was present moments later.

## `writeability` is not a safety interlock

`TagWriteability` rides in the envelope and **no driver reads it from your request**. The only
`writeability` checks in the write path read the driver's own *stored* value.

So sending `TagWriteable` for a read-only tag does not force a write, and `TagReadOnly` does not
prevent one. This skill reports the field and never refuses on it — a local gate would invent a
guarantee that does not exist. The server enforces it instead; verified live against a read-only
modbus tag:

```
WRITE FAILED (HTTP 400)
  server: Failed writing to ModbusFlexible. Reason: Parameter is read only
```

## A virtual parameter is not a write target

VPIDs are **computed** from other parameters, so no route here can write one. If you target a virtual
parameter, this skill says so and names it:

```
500109 is a VIRTUAL parameter (SAC: Operator Message (Mapped), location 20002). Virtual
parameters are COMPUTED from other parameters and cannot be written through these routes —
write the upstream parameter its script reads instead. Nothing about this says the parameter
does not exist; use onping-pid-locate --vp to read it.
```

That last sentence is load-bearing. Until 2026-08-21 the same input failed with the shared lookup's
not-found note — *"the PID does not exist, has been deleted, or belongs to a location this token cannot
see"* — all three false for a VP updating every few minutes. A `NOT FOUND` on a live mapped VPID was
read as "the control loop is dead" for four producing wells over 56 days. Read a VPID with
`onping-pid-locate --vp`; to change a computed value, write the upstream parameter.

## You cannot attribute a write to another user

`reqWriteUsername` is **required** by the `WriteRequest` parser and its value is **discarded** — the
handler overwrites it from the authenticated session (`HmiViewer.hs`). So it is always sent as
`""` and there is deliberately **no flag** for it; a flag there would look like write attribution the
route does not offer.

Verified live: a `--via-hmi` write sent with `reqWriteUsername: ""` was attributed in the audit trail
to the token's own user, identically to the default-route writes.

## Errors are classified by payload, never by status

The two routes use incompatible envelopes, and **the HMI route returns `500` for client-caused
failures including permission denials** — so the status code alone cannot classify anything. This
skill reads the payload: the `error` string on the source route, the `tag` chain on the HMI route.

Verified live — a read-only rejection arriving as a `500`:

```
WRITE FAILED (HTTP 500)
  server: ClientRequestError -> WriteFailedError -> WriteErrorGeneric -> Failed writing to
          ModbusFlexible. Reason: Parameter is read only
  note: this route returns 500 for client-caused failures too (including permission
        denials), so the 500 does not by itself mean a server fault.
```

Messages that read as something other than what they mean, all translated while the server's verbatim
text is always shown:

| Server text | What it actually means |
| --- | --- |
| `failed to lookup one group by LocationId` | The location is in **zero or 2+ permission groups**, so it cannot be written through **any** of these routes regardless of your rights. A configuration fact, not a lookup bug. |
| `failed to write parameter, insufficient permissions` | You do not **own** the location's group. `ownedGroupsByUserId` is stricter than the read visibility that let the lookup succeed — **locating a PID does not mean you can write it.** |
| `Failed to lookup parameter by pid before writing` | The PID does not exist, or resolved to other than exactly one tag. |
| `… values are mismatched` | The value's type does not match the parameter's stored type. Verified: the singlewell-manual driver rejects this itself with a `400`, before `WriteErrorDoubleConversion`. |
| `Parameter is read only` / `is not writable` | The driver enforced its **own stored** writeability (see above). |
| `WriteErrorEmptyMasks` | The mask produced nothing — **nothing was written**. |

## Examples

Dry run — always do this first; it names the location so a human can sanity-check it:

```bash
uv run ~/.claude/skills/onping-pid-write/scripts/write_pid.py "$ACCESS_TOKEN" 500005 --value 42 --names
```

Set a numeric setpoint and confirm it landed:

```bash
uv run ~/.claude/skills/onping-pid-write/scripts/write_pid.py "$ACCESS_TOKEN" 500005 \
  --value 42 --verify --yes
```

Write an operator note (text — no masking):

```bash
uv run ~/.claude/skills/onping-pid-write/scripts/write_pid.py "$ACCESS_TOKEN" 500001 \
  --text "Good arrivals for this well should be sub 50 mins." --yes
```

A string to a TotalFlow parameter — the one case that needs the HMI route:

```bash
uv run ~/.claude/skills/onping-pid-write/scripts/write_pid.py "$ACCESS_TOKEN" <tflow-pid> \
  --text "STATUS OK" --via-hmi --yes
```

Slow link or a busy server — wait longer for confirmation:

```bash
uv run ~/.claude/skills/onping-pid-write/scripts/write_pid.py "$ACCESS_TOKEN" 500005 \
  --value 42 --verify --verify-timeout 45 --yes
```

Review what you just did:

```bash
uv run ~/.claude/skills/onping-audit-pull/scripts/audit_pull.py "$ACCESS_TOKEN" \
  --type manual --terms 500005 --since 2026-08-21T00:00:00Z
```

## Audit trail

Every write is attributed to the **token's user** and lands in the audit trail as `manual` (or the
driver-specific write type). `onping-audit-pull` is how a write gets reviewed after the fact — and the
way to confirm a dry run really issued nothing.

## Related skills

- `onping-login` — get the access token
- `onping-pid-locate` — resolve the PID first; shares this skill's lookup
- `onping-audit-pull` — who wrote what, and when
- `onping-driver-resolve` — which driver a location uses
- `onping-mass-write` — **does not write.** Builds a CSV for the UI's mass-import dialog, for bulk
  historical loads, and lands cloud-only
