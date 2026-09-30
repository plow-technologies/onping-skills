---
name: classic-cp-list
description: List classic (legacy, non-Inferno) OnPing control parameters by Lumberjack serial via POST /cp/list/by-lj-ident-key. Discover CPIDs for classic-cp-delete or outputPIDs for classic-cp-by-pid. NOT for Inferno CPs (cpInferno/*).
allowed-tools: Bash(uv run *)
---

# Classic Control Parameter List

List classic (legacy, **non-Inferno**) control parameters on OnPing by Lumberjack **serial number**. This mirrors the list action in the OnPing web UI's `/v3/control-parameter` page — a single `POST /cp/list/by-lj-ident-key` with a tagged identity-key body, one request per serial.

> **Classic, not Inferno.** This skill operates on the **classic** control-parameter engine (`/cp/*`) — the same engine that `classic-cp-dhall` imports/exports and `classic-cp-delete` removes. It is **not** the Inferno CP system (`cpInferno/*`) that `cp-list` and `cp-import-json` use. Do **not** use this skill to list Inferno control parameters (use `cp-list` for those).

> **Input contract differs from cp-list.** This endpoint takes a **tagged identity key** (`{"tag":"IdentityKeySerialNum","contents":<serial>}`), not a bare Lumberjack ID. The Lumberjack **serial number** this endpoint expects may differ from the numeric "Lumberjack ID" used by `cp-list` and `lj-profile`. v1 supports serial-number input only; other identity-key variants are unverified and documented as TODO.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **classic-cp-delete** — Delete classic CPs by CPID (same `/cp/*` engine)
- **classic-cp-dhall** — Import/export/disable classic CPs (same `/cp/*` engine)
- **classic-cp-by-pid** — Look up a classic CP by its output parameter ID
- **cp-list** — List Inferno CPs (**different** engine — `cpInferno/*`, takes a bare Lumberjack ID)
- **lj-profile** — Look up Lumberjack profiles by location ID
- **cpid-migration** — Overall migration runbook (Phase 3 discovers classic CPs to disable/remove)

## When to Use

Use this skill to discover what classic control parameters exist on a Lumberjack:

- You have a Lumberjack serial and need to know the CPIDs (for `classic-cp-delete`) or outputPIDs (for `classic-cp-by-pid`).
- You're migrating from classic to Inferno CPs and need the list of old CPs to disable or remove.
- You want to audit which classic CPs are running on a given Lumberjack.

Each returned record carries both `controlParameterID` (CPID) and `controlParameterOutputWrite` (outputPID), so a single list call gives the whole-Lumberjack outputPID↔CPID mapping.

## Usage

Requires a valid access token and one or more Lumberjack serial numbers.

**List classic CPs for a single serial:**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19
```

**Batch** (one `POST /cp/list/by-lj-ident-key` per serial):

```bash
uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19 20 21
```

**Get just the CPIDs for piping into classic-cp-delete:**

```bash
CPIDS=$(uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19 --cpids-only)
echo "Found CPIDs: $CPIDS"
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py "$ACCESS_TOKEN" $CPIDS --yes
```

**Filter to enabled CPs only:**

```bash
uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19 --enabled-only
```

**Full JSON output:**

```bash
uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19 --json
```

## Flags

- `--json` — Emit full CP records as JSON (single serial: `[records...]`, batch: `{"serial": [records...]}`) instead of a table.
- `--cpids-only` — Print only the CPIDs (space-separated, across all serials) for piping into `classic-cp-delete`. Respects `--enabled-only`.
- `--enabled-only` — Filter to CPs where `controlParameterEnabled == true`.

## Output

- **Default:** a table per serial with columns `cpid`, `outputPID`, `enabled`, `schedule` (compact: tag + contents), and a truncated script preview (~40 chars). A count line (to stderr) like `18 readable classic CPs on serial 1002`.
- **--cpids-only:** just the CPIDs, space-separated (to stdout). **Readable CPs only** — CPs the token cannot read are excluded (you can't act on them anyway).
- **--json:** an object with `cps` (full records, each with `controlParameterID`, `controlParameterOutputWrite`, `controlParameterEnabled`, `controlParameterInputs`, `controlParameterSchedule`, `controlParameterScript`, `controlParameterStepSize`, `controlParameterWriteToken`), plus `prohibited` (CPIDs the token cannot read) and `other` (any unrecognized elements) when present.
- **Not-readable CPs:** the response may include `{"tag":"ProhibitedReadControlParameter","contents":<cpid>}` elements — classic CPs the token's user is not permitted to read (only the CPID is returned, no record). These are reported separately (a stderr line in table mode, the `prohibited` array in `--json`) so the count is honest — they are **not** silently dropped, but they are **not** included in the readable table or `--cpids-only`.
- **Empty result:** a serial with no classic CPs reports zero CPs and exits 0 (not an error).
- **Exit codes:** 0 on success (including empty list); non-zero on auth/HTTP/parse failure.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/cp/list/by-lj-ident-key` | POST | `application/json` | `{"tag":"IdentityKeySerialNum","contents":<serial:int>}` | 200 → JSON list; elements are `{"tag":"ReadableControlParameter","contents":{...record...}}` or `{"tag":"ProhibitedReadControlParameter","contents":<cpid>}` |

The body is a **tagged identity key**, not a bare integer like `cpInferno/list`. The verified variant is `IdentityKeySerialNum` with an integer payload (the Lumberjack serial). Other identity-key tag names (`IdentityKeyLumberJackId`, etc.) returned HTTP 400 and are unverified; v1 supports serial-number input only.

## Authentication

`/cp/list/by-lj-ident-key` accepts **Bearer token auth** from `onping-login` (verified). Session cookies (as in browser network requests) also work, but bearer tokens are preferred for scripted use.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit) and lists no CPs.
- **Non-200 response** — surfaced as an error with the status code and response body excerpt; exit non-zero.
- **Serial with no classic CPs** — an empty list is a valid success; exit 0.

## Workflows

### Discover and delete classic CPs

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# 1. List classic CPs and see what's there
uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19

# 2. Back up the classic CPs first
CPIDS=$(uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19 --cpids-only)
uv run ~/.claude/skills/classic-cp-dhall/scripts/classic_cp_dhall.py \
  export "$ACCESS_TOKEN" --cpids $CPIDS --output classic-cps-backup.dhall

# 3. Delete them
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py \
  "$ACCESS_TOKEN" $CPIDS --yes
```

### Audit which classic CPs are still enabled

```bash
uv run ~/.claude/skills/classic-cp-list/scripts/list_classic_cps.py "$ACCESS_TOKEN" 19 --enabled-only
```

## Implementation Notes

- **Serial vs Lumberjack ID:** The Lumberjack "serial number" this endpoint expects may differ from the "Lumberjack ID" (a numeric ID used by `cp-list`, `lj-profile`). They are not necessarily the same value; this skill takes the serial that `/cp/list/by-lj-ident-key` expects. If a mapping is needed (serial → Lumberjack ID or vice versa), that is lj-profile / location-lookup territory, out of scope here.
- **Identity-key variants:** Only `IdentityKeySerialNum` (serial number) is verified in v1. Other variants (by Lumberjack name, by ID, etc.) are unverified and TODO once their exact tag names and payloads are confirmed from the OnPing type source or captured requests.
- **Response shape:** The top level is a bare list (not an `OnpingResponse` wrapper). Each element is `{"tag":"ReadableControlParameter","contents":{...}}` where `contents` is the CP record. The script tolerates a bare CP record defensively.
- **Schedule rendering:** The `controlParameterSchedule` is itself a tagged object (e.g. `{"tag":"OnCronSchedule","contents":"0 0 1/1 * *"}` or `{"tag":"OnInputChange"}`). The table displays it compactly as `tag [contents]`.
