---
name: onping-update-mqtt-json
description: Update the OnPing mqtt-json driver location config via authenticated read-modify-write. MUTATES OnPing with --yes. This driver does NOT poll — `--poll-time` is rejected.
allowed-tools: Bash(uv run *)
---

# OnPing update-mqtt-json

Safely updates a single mqtt-json driver location's configuration on OnPing by **read-modify-write**: it fetches the current full config from `/mqtt/json/location/fetch`, changes only the requested allowlisted field(s), and POSTs the whole record back to `/mqtt/json/location/update`. Backed by the shared `_driver_update_routes` module.

**This driver does not poll** — it has no poll-time field, so `--poll-time` is not accepted. (Use a safe allowlisted field if/when one is added.)

## Safety

- **Mutating**: a real write happens only with `--yes`. Without `--yes` (and without `--dry-run`) the skill prints the before/after diff and exits without changing anything. `--dry-run` fetches and shows the diff, never POSTs.
- **Lumberjack & identity fields are never changed.** This skill refuses to modify: `mqttLocMongoId`, `mqttLocInfo.locInfoLocId`, `mqttLocUrl`, `mqttLocPort`. Drivers run on Lumberjacks; these are routing/identity keys — editing them would desync routing or retarget the wrong device. Moving a location to another lumberjack is a separate operation, out of scope here.
- Editable downstream device fields (e.g. PLC/device/gateway address) are preserved as fetched and are not touched by this skill.

## Source of truth

- Update handler: `onping/Handler/MQTT/JSON/Service.hs` (in the OnPing repo)
- Fetch endpoint: `/mqtt/json/location/fetch` · Update endpoint: `/mqtt/json/location/update`

Field keys are verified against the live Haskell record JSON. If the types drift, re-verify against the handler and update `_driver_update_routes/routes.py`.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Preview (no write):
uv run ~/.claude/skills/onping-update-mqtt-json/scripts/update_location.py \
  "$ACCESS_TOKEN" REF_ID --dry-run
# Apply:
uv run ~/.claude/skills/onping-update-mqtt-json/scripts/update_location.py \
  "$ACCESS_TOKEN" REF_ID --yes
```

You need the location's **driver** to pick this skill. To resolve a bare refId to its driver, see the "Driver Updates" section of `onping/skills/SKILLS.md`.
