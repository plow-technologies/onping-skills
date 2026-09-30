---
name: classic-cp-export
description: Export classic (legacy, non-Inferno) OnPing control parameters by CPID via POST /cp/export. Returns a Dhall backup file. Use before classic-cp-delete or during CPID migration. NOT for Inferno CPs (cpInferno/*).
allowed-tools: Bash(uv run *)
---

# Classic Control Parameter Export

Export classic (legacy, **non-Inferno**) control parameters from OnPing by CPID. This mirrors the **export** action in the OnPing web UI's `/v3/control-parameter` page — a single `POST /cp/export` with a JSON CPID-array body, returning a Dhall control-parameter file.

> **Classic, not Inferno.** This skill operates on the **classic** control-parameter engine (`/cp/*`) — the same engine that `classic-cp-dhall` imports and exports. It is **not** the Inferno CP system (`cpInferno/*`) that `cp-list`, `cp-import-json`, and `cp-script-fetch` use. Do **not** use this skill to export an Inferno control parameter.

> **Backup before delete.** This is the recommended way to back up classic CPs before disabling or deleting them during a CPID migration or teardown. The exported Dhall file round-trips through `classic-cp-dhall import` if you need to restore.

> **CPID vs outputPID id spaces.** The **request** body is keyed by **CPID** (`controlParameterID`), but the **exported Dhall** entries are keyed by **`outputPID`** (the PID each CP writes to). When composing `classic-cp-export` → `classic-cp-delete`, use `classic-cp-by-pid` to map outputPIDs back to CPIDs — the delete endpoint needs the CPID.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **classic-cp-delete** — Delete classic CPs by CPID (this export is the recommended backup step before delete)
- **classic-cp-by-pid** — Resolve outputPID → CPID (to find the CPIDs for the exported entries)
- **classic-cp-dhall** — Import/export/disable classic CPs (same `/cp/*` engine; has an `export` subcommand — this standalone is the discoverable, family-consistent entry point)
- **classic-cp-list** — List all classic CPs for a Lumberjack (to get the CPIDs to export)
- **cpid-migration** — Overall migration runbook (Phase 3 disables/removes old classic CPs)
- **cp-list** / **cp-import-json** — Inferno CP system (**different** engine — not what this exports)

## When to Use

When you want a **backup** of classic (legacy) control parameters:

- Before disabling or deleting a classic CP during a CPID migration or teardown
- Before modifying a classic CP with `classic-cp-dhall disable-all` + `import`
- To archive the current state of classic CPs for a Lumberjack

Get the CPIDs from the web UI (`/v3/control-parameter`), a `classic-cp-list` result, or a migration plan.

## Usage

Requires a valid access token and one or more numeric classic CPIDs.

**Export to a file:**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/classic-cp-export/scripts/export_classic_cp.py \
  "$ACCESS_TOKEN" --cpids 10001 --output backup.dhall
```

**Export multiple CPs (batched in a single request):**

```bash
uv run ~/.claude/skills/classic-cp-export/scripts/export_classic_cp.py \
  "$ACCESS_TOKEN" --cpids 10001 10002 10003 --output classic-cps-backup.dhall
```

**Print to stdout only (no file):**

```bash
uv run ~/.claude/skills/classic-cp-export/scripts/export_classic_cp.py \
  "$ACCESS_TOKEN" --cpids 10001
```

**Recommended migration flow — export, then delete:**

```bash
# 1. Export the classic CPs as a backup
uv run ~/.claude/skills/classic-cp-export/scripts/export_classic_cp.py \
  "$ACCESS_TOKEN" --cpids 10001 10002 10003 --output classic-cps-backup.dhall

# 2. Delete them (irreversible)
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py \
  "$ACCESS_TOKEN" 10001 10002 10003 --yes
```

## Flags

- `--cpids CPID [CPID ...]` — One or more classic CPIDs to export. **Required.**
- `--output PATH` — Write the Dhall export to the given file path. If omitted, only prints to stdout. The status line (`Exported N CPs to <path>`) goes to stderr so a stdout redirect yields a clean Dhall file.

## Output

- **Success:** writes the Dhall control-parameter file to `--output` (if given) and prints it to stdout. The status line goes to stderr. Exit 0.
- **Failure:** a non-200 response (e.g. a bad CPID → HTTP 500 with a JSON `{"error": ...}` envelope) surfaces the raw body, writes no file, and exits non-zero. An expired token (303 → /auth/login or HTML body) fails fast with a diagnostic and writes no file.

The exported Dhall is a `List` of CP records, each:

```dhall
{ outputPID : Natural
, inputPIDs : List Natural
, script : Text
, stepSize : Natural
, schedule : < OnInputChange | OnInputChangeExcept : List Natural | Periodic : Integer | OnCronSchedule : Text >
, enabled : Bool
, token : Optional Text
}
```

Note the entries are keyed by `outputPID`, **not** the CPID you requested. To find the CPID for a given outputPID, use `classic-cp-by-pid`.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/cp/export` | POST | `application/json` | JSON array of CPID integers (e.g. `[10001,10002]`) | HTTP 200 with `content-type: text/x-dhall;charset=utf-8` on success; HTTP 500 with JSON `{"error": ...}` envelope if any CPID is invalid |

The body is a **JSON array of CPIDs**, not a per-CPID loop — the endpoint handles the batch in a single request. If any CPID in the array is non-existent or invalid, the entire request fails (HTTP 500) rather than returning partial results.

## Authentication

`/cp/export` accepts **Bearer token auth** from `onping-login` (verified). Session cookies (as in browser network requests) also work, but bearer tokens are preferred for scripted use.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML body fails fast (non-zero exit, no file written) with a diagnostic.
- **Non-existent CPID** — OnPing returns HTTP 500 with a JSON `{"error": ...}` envelope naming a downstream 404. The script surfaces the raw response and exits non-zero; no file is written. One bad CPID fails the whole batch (all-or-nothing).
- **Non-200 response** — surfaced as-is, no file written, exit non-zero.
