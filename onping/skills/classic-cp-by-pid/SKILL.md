---
name: classic-cp-by-pid
description: Look up classic (legacy, non-Inferno) OnPing control parameters by outputPID via POST /cp/by-pid. Resolve outputPIDs from Dhall files to CPIDs for deletion. NOT for Inferno CPs (cpInferno/*).
allowed-tools: Bash(uv run *)
---

# Classic Control Parameter Lookup by outputPID

Look up classic (legacy, **non-Inferno**) control parameters on OnPing by **outputPID**, resolving to their **CPID** (`controlParameterID`). This mirrors the **by-pid lookup** in the OnPing web UI's `/v3/control-parameter?pid=<outputPID>` page — a single `POST /cp/by-pid` with the bare outputPID as the JSON body, one request per outputPID.

> **Classic, not Inferno.** This skill operates on the **classic** control-parameter engine (`/cp/*`) — the same engine that `classic-cp-dhall` imports and exports, and `classic-cp-delete` deletes. It is **not** the Inferno CP system (`cpInferno/*`) that `cp-list`, `cp-import-json`, and `cp-script-fetch` use. Do **not** use this skill to look up an Inferno control parameter.

> **outputPID vs CPID — two distinct id spaces.** Classic-CP Dhall files (from `classic-cp-dhall export`) key every entry by **outputPID** (the PID each CP writes to), **not** by CPID. The `classic-cp-delete` skill needs **CPIDs**. This lookup bridges the gap: feed it the outputPIDs from a Dhall file, and it returns the CPIDs you can pass to the deleter.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **classic-cp-dhall** — Import/export/disable classic CPs (same `/cp/*` engine); the `export` command produces Dhall files keyed by outputPID
- **classic-cp-delete** — Delete classic CPs by CPID; use this lookup first to turn Dhall outputPIDs into deletable CPIDs
- **cpid-migration** — Overall migration runbook (Phase 3 resolves outputPIDs to CPIDs before disabling/removing)
- **cp-list** / **cp-import-json** — Inferno CP system (**different** engine — not what this looks up)

## When to Use

When you have a classic-CP Dhall file (or raw outputPIDs from the OnPing UI) and need to:

- Confirm which CPIDs correspond to those outputPIDs before deleting with `classic-cp-delete`.
- Verify a classic CP record's state (enabled, script preview) before taking action.

A typical workflow: `classic-cp-dhall export` → extract the outputPIDs → this lookup → feed the CPIDs into `classic-cp-delete`.

## Usage

Requires a valid access token and one or more numeric outputPIDs.

**Look up a single outputPID:**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/classic-cp-by-pid/scripts/lookup_cp_by_pid.py "$ACCESS_TOKEN" 500016
```

**Batch lookup** (one `POST /cp/by-pid` per outputPID; a not-found on one does not stop the rest):

```bash
uv run ~/.claude/skills/classic-cp-by-pid/scripts/lookup_cp_by_pid.py "$ACCESS_TOKEN" 500016 500018 500017
```

**Resolve Dhall outputPIDs to CPIDs for deletion:**

```bash
# 1. Look up the outputPIDs and get just the CPIDs
CPIDS=$(uv run ~/.claude/skills/classic-cp-by-pid/scripts/lookup_cp_by_pid.py \
  "$ACCESS_TOKEN" 500016 500018 500017 --cpids-only)
# 2. Delete them (irreversible; requires --yes)
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py \
  "$ACCESS_TOKEN" $CPIDS --yes
```

## Flags

- `--json` — Emit JSON instead of a table (maps each input outputPID to `{cpid, enabled, outputWrite, script_preview}` or `{cpid: null, note: "..."}`).
- `--cpids-only` — Print only the resolved CPIDs space-separated (skip not-found; suitable for piping into `classic-cp-delete`).

## Output

- **Default (table):** columns `outputPID`, `cpid`, `enabled`, and a truncated script preview (~50 chars). Not-found outputPIDs show `cpid: null` with a note.
- **`--json`:** an object mapping each input outputPID (as string key) to its resolved record or a not-found marker.
- **`--cpids-only`:** just the CPIDs (space-separated) that resolved; not-found outputPIDs are omitted.

Exit 0 even if some outputPIDs are not-found (clean miss); exit non-zero only on auth/HTTP/parse failure.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/cp/by-pid` | POST | `application/json` | bare outputPID integer (e.g. `500016`) | 2xx with the CP record object on success; `null` if not-found |

The body is the **bare outputPID integer**, not an object or array — exactly what the UI sends. To look up multiple outputPIDs, the skill loops the call once per outputPID.

The returned CP record has keys: `controlParameterID` (the CPID), `controlParameterOutputWrite` (echo of outputPID), `controlParameterEnabled`, `controlParameterInputs`, `controlParameterSchedule`, `controlParameterScript`, `controlParameterStepSize`, `controlParameterWriteToken`.

## Authentication

`/cp/by-pid` accepts **Bearer token auth** from `onping-login` (verified). Session cookies (as in browser network requests) also work, but bearer tokens are preferred for scripted use.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit) and reports no outputPID as resolved.
- **Not-found outputPID** — a `null` (or empty) 200 body means no classic CP writes that outputPID. Reported as `not found` with `cpid: null` and a note (may be Inferno-written, or already deleted). Exit stays 0.
- **Non-200 (non-auth)** — reported as a per-outputPID error with the raw response; other outputPIDs still run.
