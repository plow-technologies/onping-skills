---
name: ml-parameter-update
description: Update OnPing Inferno inference (ml-) parameters — swap script hashes, rewire input/output PIDs, and adjust resolution via read-modify-write on /inferno/ml/inference/update. Use to apply post-retrain deployment changes without touching the OnPing web UI.
allowed-tools: Bash(uv run *)
---

# ML Parameter Update

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> `update` and `restore-export` overwrite an inference parameter's script hash, input and output PID bindings, and resolution. There is no undo; export the current state first with `ml-parameter-export` so you can put it back with `restore-export`. Both preview by default and change nothing until you pass `--apply`.

List, fetch, and update OnPing inference parameters (`InferenceParamX`). Uses strict read-modify-write semantics against `PUT /inferno/ml/inference/update`.

## Use This Skill For

- Swapping the Inferno script hash on a deployed ml-parameter after a script update
- Adding, changing, or removing input/output PID bindings on a live ml-parameter
- Changing the execution resolution (seconds)
- Diffing a proposed change with `--dry-run` before applying
- Restoring the bindings, script hash, and resolution of an existing multi-well parameter from one reviewed `ml-parameter-export --unwrap-single` backup
- Bulk workflows: list params by script hash, then apply the same edit to each

## Do Not Use This Skill For

- Uploading new TorchScript model versions — use `ml-model-manage`
- Updating model card / docs fields on a version — use `ml-model-docs`
- Creating or deleting inference parameters (provisioning + EC2 teardown) — out of scope
- Editing which parent models a script references — belongs in the script LSP session, not this API

## Related Skills

- `onping-login` for access tokens
- `ml-model-manage` for parent model / version upload
- `ml-model-docs` for version metadata edits
- `cp-import-json` for the analogous control-parameter import flow

## Commands

Resolve commands relative to this skill directory.

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
```

### List

```bash
# All accessible params
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" list

# Filter by exact script hash
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" list \
  --script-hash CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=

# Substring match on param name
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" list \
  --name-filter example
```

### Get

```bash
# Bare InferenceParamX
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" get \
  --param-id 00000000-0000-4000-8000-00000000c004

# With-sources variant (includes SourceInfo per binding)
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" get \
  --param-id 00000000-0000-4000-8000-00000000c004 --with-sources
```

### Update (dry-run by default)

```bash
# Dry-run a script-hash swap — no PUT is issued
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" update \
  --param-id <UUID> \
  --script-hash <NEW_SCRIPT_HASH>

# Apply (destructive) — always dry-run first
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" update \
  --param-id <UUID> \
  --script-hash <NEW_SCRIPT_HASH> \
  --apply

# Replace existing bindings or add new ones
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" update \
  --param-id <UUID> \
  --set-input casing_psi_in=500012 \
  --set-input new_channel_in=999123 \
  --set-output alert_pumper_out=500026

# Drop an existing binding (requires explicit allow flag)
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" update \
  --param-id <UUID> \
  --allow-remove-input well_specific_notes_in \
  --apply
```

### Restore an existing multi-well parameter (dry-run by default)

`restore-export` accepts **one bare export object**, not the multi-item export array. The current live ID, group, company, schedule, name, and description must match the backup. Its PIDs must be positive and the input/output arrays must all have the same nonzero width. A hash and width precondition prevents a stale packet from silently overwriting another revision.

```bash
# Preview only; the live parameter remains unchanged.
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" restore-export \
  --param-id <EXISTING_UUID> --file <ONE_BARE_EXPORT_JSON> \
  --expect-script <CURRENT_SERVING_HASH> --expect-current-width 4

# MUTATING: use only after separate operator approval, review of the preview,
# a fresh live read and a plan to verify the actual device/parameter result.
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" restore-export \
  --param-id <EXISTING_UUID> --file <ONE_BARE_EXPORT_JSON> \
  --expect-script <CURRENT_SERVING_HASH> --expect-current-width 4 --apply
```

For the Well A-2 rollback, the backup's old hash/three-wide PID arrays are the **desired** state. `--expect-script` must name the **current four-wide serving** hash at rollback time, not the old backup hash. Do not pass `--apply` on the basis of a dry-run alone: the PUT has no live write proof yet. First confirm a tested restoration route and the operator's per-hop approval. An export that reads as a no-op against the old live parameter checks the backup's match, **not** the four-to-three restore.

Scalar `update --set-input/--set-output` flags deliberately refuse a multi-well parameter; a single PID cannot replace a whole well array. The complete export form prevents an accidental partial-width change.

## CRITICAL: Do not hand-craft the PUT body

The current `PUT /inferno/ml/inference/update` handler consumes a complete `InferenceParamX` envelope with a **top-level `id`** and nested `param` containing bare PIDs (`int` or `[int]`). The handler derives and permission-checks SourceInfo from those PIDs. It does **not** consume `{param, sources}`: that shape omits the required top-level ID. This is verified against `onping/Handler/Inferno/ML/Parameters.hs::putUpdateInferenceParamR` and `addSources`. This helper fetches live state first, overlays only reviewed fields, and sends the full envelope. Never craft a PUT from a stale well directory or a multi-item export array.

`get --with-sources` returns `SourceInfo` objects for scalar bindings and nonempty **arrays of SourceInfo** for multi-well bindings. The live Well A-2 ROC parameter has three SourceInfo objects per binding; treating an array as one object was the original read-path defect.

Rules:

1. **Always dry-run before apply.** `update` and `restore-export` issue no PUT without `--apply`. A preview is not a tested production rollback.
2. **Dropping a scalar binding requires `--allow-remove-input NAME` or `--allow-remove-output NAME`.** `restore-export` replaces the complete map only from an explicitly named, reviewed backup.
3. **Unspecified fields are preserved.** The full live envelope keeps `active`, `schedule`, `description`, and all bindings not named in scalar `update`. `restore-export` refuses changes to name, description, company, group, or schedule.
4. **Set-by-name is scalar only.** `--set-input casing_psi_in=X` replaces one PID; any multi-well array requires a complete export object.
5. **A rollback PUT cannot undo controller writes.** Re-read both inference parameters and the device after any separately approved apply.

## Typical workflow: post-retrain script-hash swap

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# 1. Upload the new TorchScript version (separate skill)
# 2. Identify all deployed params on the old script hash
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" list \
  --script-hash <OLD_SCRIPT_HASH>

# 3. Dry-run the swap on each param ID
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" update \
  --param-id <UUID> --script-hash <NEW_SCRIPT_HASH>

# 4. Apply after reviewing each diff
uv run ~/.claude/skills/ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" update \
  --param-id <UUID> --script-hash <NEW_SCRIPT_HASH> --apply
```

## Notes

- Set `ONPING_BASE_URL` to target a non-production environment.
- A successful PUT restarts the param's orchestrator-side evaluation. Expect a brief gap in the output PIDs while the new script loads.
- Error responses from OnPing are surfaced verbatim to stderr; exit code 1 means the change did not apply.
- The response-shape guard refuses to PUT when the GET is missing required top-level keys, which is your signal that the OnPing API contract changed and the skill's fixtures need a refresh.
