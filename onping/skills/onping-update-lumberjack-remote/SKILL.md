---
name: onping-update-lumberjack-remote
description: Update the OnPing lumberjack-remote driver location config (primarily poll time) via authenticated read-modify-write. MUTATES OnPing with --yes. Never edits lumberjack/identity fields.
allowed-tools: Bash(uv run *)
---

# OnPing update-lumberjack-remote

> **⚠️ WARNING: this skill changes live data.**
> It changes the poll time of a live lumberjack-remote driver location on OnPing by posting the whole config record back; lumberjack and identity fields are never changed. Undo by re-running with the previous poll time, which the preview prints. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Safely updates a single lumberjack-remote driver location's configuration on OnPing by **read-modify-write**: it fetches the current full config from `/lumberjack/remote/lookup`, changes only the requested allowlisted field(s), and POSTs the whole record back to `/lumberjack/remote/update`. Backed by the shared `_driver_update_routes` module.

Set poll time (seconds) with `--poll-time`. Poll field: `remoteConfigPollFrequency`.

## Safety

- **Mutating**: a real write happens only with `--yes`. Without `--yes` (and without `--dry-run`) the skill prints the before/after diff and exits without changing anything. `--dry-run` fetches and shows the diff, never POSTs.
- **Lumberjack & identity fields are never changed.** This skill refuses to modify: `remoteConfigLocId`, `remoteConfigRefId`, `remoteConfigUrl`, `remoteConfigPort`. Drivers run on Lumberjacks; these are routing/identity keys — editing them would desync routing or retarget the wrong device. Moving a location to another lumberjack is a separate operation, out of scope here.
- Editable downstream device fields (e.g. PLC/device/gateway address) are preserved as fetched and are not touched by this skill.

## Source of truth

- Update handler: `onping/Handler/LumberjackRemote/Service.hs` (in the OnPing repo)
- Fetch endpoint: `/lumberjack/remote/lookup` · Update endpoint: `/lumberjack/remote/update`

Field keys are verified against the live Haskell record JSON. If the types drift, re-verify against the handler and update `_driver_update_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Preview (no write):
uv run ~/.claude/skills/onping-update-lumberjack-remote/scripts/update_location.py \
  "$ACCESS_TOKEN" REF_ID --poll-time 5 --dry-run
# Apply:
uv run ~/.claude/skills/onping-update-lumberjack-remote/scripts/update_location.py \
  "$ACCESS_TOKEN" REF_ID --poll-time 5 --yes
```

You need the location's **driver** to pick this skill. To resolve a bare refId to its driver, see the "Driver Updates" section of `onping/skills/SKILLS.md`.
