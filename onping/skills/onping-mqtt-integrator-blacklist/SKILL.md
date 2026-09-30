---
name: onping-mqtt-integrator-blacklist
description: Read or edit the mqtt-json-integrator blacklist for one Lumberjack via GET/POST /mqtt/json/integrator/{serial}/blacklist — the list of locations and PIDs that must never be created, filtered server-side in step one of the create pipeline so they are skipped even with --all. MUTATES with --yes. Blacklisting BLOCKS CREATION but does NOT delete anything already created. The POST takes incremental add/remove ops, not a whole list, so concurrent editors do not clobber each other. PIDs need three values (location key, topic, value selector) because PidUniqueIdentifier is a record, not a scalar.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator blacklist

Manages the per-Lumberjack list of locations and PIDs the integrator must never
create.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## What it does

Step one of the create pipeline filters blacklisted entries **server-side**, so a
blacklisted candidate is skipped however it was selected — including
`onping-mqtt-integrator-create --all`. This is the durable way to say "the rules
keep generating this, and I don't want it."

Entries **never expire**. Nothing cleans the list up; it persists until removed.

## Blacklisting blocks creation — it does not delete

An object that has **already been created stays created**. Blacklisting it changes
nothing about its existence in OnPing or the driver.

To actually get rid of an object the rules insist on regenerating, do both, in
this order:

1. Delete it for real — in OnPing and in the mqtt-json driver
2. Blacklist it here, so the next rule execution cannot bring it back

Doing only step 1 means it reappears on the next create. Doing only step 2 means
it stays where it is. The `--list-candidates` output states this next to the
already-created entries, since that is where the mistake gets made.

Note also that `onping-mqtt-integrator-delete --target stored` does **not** count
as step 1 — it makes the integrator forget the record while leaving the real
objects orphaned, and actually *un-suppresses* creation.

## Incremental ops, not a whole list

The POST takes `[UpdateBlacklist]` — a list of operations, so two editors working
at once do not overwrite each other:

```json
{"tag": "BlacklistAddLocation",    "contents": {"unLocationUniqueIdentifier": "..."}}
{"tag": "BlacklistRemoveLocation", "contents": {"unLocationUniqueIdentifier": "..."}}
{"tag": "BlacklistAddPid",         "contents": {"pidLocationUniqueIdentifier": {...},
                                                "pidMqttJsonSourceId": {...}}}
{"tag": "BlacklistRemovePid",      "contents": {...}}
```

Shapes verified against
`mqtt-json-integrator-types/golden/UpdateBlacklist/`. The skill builds these for
you.

Adding and removing the same entry in one invocation is refused: the server
applies ops in order, so the outcome would depend on argument order.

## Identifying a PID takes three values

`PidUniqueIdentifier` is a two-field record — the location key plus a source id of
`(topic, valueSelector)` — not a scalar. Pass them joined by `::`:

```
--add-pid 'facility1-building2-sensor001::/sensors/TEMP001/data::.temperature'
```

`--list-candidates` prints copy-pasteable selectors for every uncreated candidate
and every already-created object, marking the ones already blacklisted.

## Safety

- **Read-only by default** — with no edit flags it just prints the current list.
- **Mutating with `--yes`.** Without it (or with `--dry-run`) the skill prints the
  exact operations it would send and exits. `--dry-run` wins if both are passed.
- **No-op detection**: adding something already blacklisted, or removing something
  that is not, is reported as a note rather than silently succeeding.
- After a write the skill re-reads the list and reports the resulting counts.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-blacklist/scripts/blacklist.py

# What is currently blocked:
uv run "$SKILL" "$ACCESS_TOKEN" 1001

# What could be blocked, with exact selectors:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --list-candidates

# Block a noisy location (preview, then apply):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --add-location 'test-rig-01'
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --add-location 'test-rig-01' --yes

# Block two PIDs:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 \
  --add-pid 'rig-01::/rig/01/debug::.raw' \
  --add-pid 'rig-01::/rig/01/debug::.spare' --yes

# Unblock:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --remove-location 'test-rig-01' --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `--json` — raw `Blacklist` JSON
- `--list-candidates` — uncreated candidates and created objects with selectors
- `--add-location KEY` / `--remove-location KEY` — repeatable
- `--add-pid 'LOCKEY::TOPIC::SELECTOR'` / `--remove-pid ...` — repeatable
- `--dry-run`, `--yes` — mutation gates

### Exit codes

- `0` — success
- `1` — malformed `--*-pid` value, add/remove conflict, or transport/auth error

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` (GET), `:247` (POST)
- Types: `mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs`
  (`Blacklist`), `:1043` (`UpdateBlacklist`)
- Lifecycle: `mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md`, "Blacklist"
- Route table: `_mqtt_integrator_routes/routes.py` (`get_blacklist`, `update_blacklist`)

## Related skills

- `onping-mqtt-integrator-create` — the pipeline that honors the blacklist
- `onping-mqtt-integrator-unprocessed --uncreated` — the candidates being generated
- `onping-mqtt-integrator-delete --target uncreated` — drop candidates once (they regenerate; blacklisting is permanent)
- `onping-mqtt-integrator-artifacts-import` — the bulk suppression path
