---
name: classic-cp-dhall
description: Import, export, and modify classic (legacy) OnPing control parameters in Dhall format. Use during CPID migration to disable old CPs before importing Inferno replacements.
allowed-tools: Bash(uv run *)
---

# Classic Control Parameter Dhall

Import, export, and modify classic (legacy, non-Inferno) control parameters on OnPing using the Dhall format. These endpoints operate on the **old** CP engine (`/cp/import`, `/cp/export`), not the Inferno CP system.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **cp-list** — List Inferno CPs (different system)
- **cp-import-json** — Import Inferno CPs (different system)
- **cpid-migration** — Overall migration runbook

## When to Use

During a CPID migration, **before** importing new Inferno CPs:

1. Export the current classic CPs as a Dhall backup (or use the existing dhall file from the project)
2. Create a disabled variant with all CPs set to `enabled = False`
3. Import the disabled variant to turn off the old CP engine
4. Then import the new Inferno CPs via `cp-import-json`

## Commands

### disable-all — Create a disabled copy of a Dhall CP file

Reads a classic CP Dhall file and writes a copy with every `enabled = True` changed to `enabled = False`. Does not touch OnPing — purely a local file operation.

```bash
uv run ~/.claude/skills/classic-cp-dhall/scripts/classic_cp_dhall.py \
  disable-all --input cps.dhall --output cps-off.dhall
```

### import — Import a Dhall CP file into OnPing

Posts the Dhall file body to `POST /cp/import`. This **creates or updates** classic CPs — if a CP with the same output PID already exists, it is overwritten. Use this to disable old CPs by importing the `disable-all` output.

```bash
uv run ~/.claude/skills/classic-cp-dhall/scripts/classic_cp_dhall.py \
  import "$ACCESS_TOKEN" --input cps-off.dhall
```

Pipeline login and import:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/classic-cp-dhall/scripts/classic_cp_dhall.py \
    import "$ACCESS_TOKEN" --input cps-off.dhall
```

### export — Export classic CPs from OnPing by CPID

Fetches classic CPs from OnPing by CPID and writes the Dhall output. Useful for creating a backup before migration.

```bash
uv run ~/.claude/skills/classic-cp-dhall/scripts/classic_cp_dhall.py \
  export "$ACCESS_TOKEN" --cpids 12345 12346 12347 --output backup.dhall
```

## Typical Migration Workflow

```
1. Login (onping-login) -> access token
2. (Optional) Export current classic CPs as backup (export)
3. Create disabled variant (disable-all --input original.dhall --output off.dhall)
4. Import disabled variant to turn off old engine (import --input off.dhall)
5. Import new Inferno CPs (cp-import-json)
6. Verify Inferno CPs running (cp-list + cp-import-json fetch-normalize)
```

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/cp/import` | POST | Dhall | `[ControlParameterRequest]` | JSON array of `(ControlParameter, UpdateResponse)` |
| `/cp/export` | POST | JSON | `[CPID]` (integers) | Dhall file (attachment) |

### ControlParameterRequest Dhall type

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

## Authentication

Both `/cp/import` and `/cp/export` accept **Bearer token auth** from `onping-login`. Session cookies (as seen in browser network requests) also work, but Bearer tokens are preferred for scripted use.

## Key Pitfalls

1. **Import is addOrUpdate** — importing a Dhall file with the same output PIDs as existing CPs will **overwrite** those CPs. This is the intended behavior for disabling.
2. **Output PID conflict** — the import endpoint rejects files where two entries share the same `outputPID`.
3. **Script type checking** — the import endpoint runs a type checker on each script. If a script has syntax errors, the import will fail.
