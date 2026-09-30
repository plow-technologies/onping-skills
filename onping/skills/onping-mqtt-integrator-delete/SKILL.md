---
name: onping-mqtt-integrator-delete
description: Delete mqtt-json-integrator uncreated candidates, created-object records, or the unprocessed queue for one Lumberjack via POST .../uncreated/delete, .../stored/delete, or .../unprocessed/json/objects/delete. MUTATES with --yes, and a full wipe additionally requires --all. All three are integrator-local and never delete OnPing or driver objects — but --target stored is dangerous: the real objects keep existing while orphaned, and forgetting the record UN-SUPPRESSES creation so a later run can make DUPLICATES. --target uncreated is nearly harmless since the next rule execution regenerates the candidates; blacklist them instead to make it stick.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator delete

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> It deletes candidates, created-object records, or raw unprocessed messages from a Lumberjack's integrator. Cleared unprocessed messages cannot be undone, deleted candidates come back on the next rule run, and deleted records can be restored only with `onping-mqtt-integrator-artifacts-import`. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Removes things from the integrator's own three stores for one Lumberjack.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## Three targets, three very different consequences

**None of these delete anything in OnPing or the mqtt-json driver.** That sounds
reassuring and is exactly why `--target stored` is dangerous.

| `--target` | What goes away | Risk |
|---|---|---|
| `uncreated` | generated candidates | low — the next rule execution regenerates them |
| `stored` | the record of what was created | **high** — see below |
| `unprocessed` | raw topic/message pairs | medium — not recoverable, no import route |

### `--target uncreated` — nearly harmless

Drops candidates the rules produced. The next execution regenerates them from the
same unprocessed data, so this is a way to tidy up, not to make something stop
appearing. Deleting a location **cascades** to its PIDs.

If you want a candidate to stay gone, use `onping-mqtt-integrator-blacklist` —
that is the mechanism designed for it.

### `--target stored` — the dangerous one

This makes the integrator **forget** that it created something. Two consequences
stack:

1. **The real objects keep existing.** The OnPing location and the mqtt-json
   driver parameters are untouched — now orphaned, referenced by nothing.
2. **Forgetting un-suppresses creation.** The create pipeline skips only what it
   has a record of. Delete the record and a later
   `onping-mqtt-integrator-create` can create **duplicates** of the very objects
   you just forgot.

So this is not a cleanup tool. Back up losslessly first with
`onping-mqtt-integrator-artifacts-export --json`, and consider blacklisting the
entries so they cannot be recreated.

### `--target unprocessed` — all or nothing

The route takes **no body and no selection**; it clears everything, so `--all` is
mandatory and `--location`/`--pid` are refused. There is no import counterpart, so
the data is gone for good — export it first if the payloads matter. Clearing is
how you resume ingestion after the queue hits its configured cap.

## Safety

- **Mutating.** Nothing happens without `--yes`; `--dry-run` wins if both are
  passed.
- **A full wipe needs `--all` as well as `--yes`.** A selection-less `--yes` is
  refused, so `--target stored --yes` cannot erase the record by accident.
- **Selectors are validated against the live set** before anything is sent — a
  typo'd key is an error, not a silent no-op.
- Each target prints its specific consequences before writing.

## Identifying entries

Locations use their unique identifier. PIDs need three values, because
`PidUniqueIdentifier` is a two-field record rather than a scalar — the location
key, topic, and value selector, joined by `::`. `--list` prints copy-pasteable
selectors.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-delete/scripts/delete.py

# See what each store holds:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --target uncreated --list
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --target stored --list

# Drop one bad candidate and its PIDs (cascades):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --target uncreated \
  --location 'test-rig-01' --yes

# Clear all candidates (they will regenerate):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --target uncreated --all --yes

# Forget one created record — preview first, and read the warning:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --target stored --location 'old-rig' 
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --target stored --location 'old-rig' --yes

# Clear the unprocessed queue:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --target unprocessed --all --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `--target {uncreated,stored,unprocessed}` — required
- `--list` — show the target's contents with selectors, then exit
- `--all` — delete everything in the target (required for a full wipe)
- `--location KEY` — repeatable; cascades to PIDs for `uncreated`
- `--pid 'LOCKEY::TOPIC::SELECTOR'` — repeatable
- `--dry-run`, `--yes` — mutation gates

### Exit codes

- `0` — success
- `1` — unknown selector, missing `--all` on an all-or-nothing target, malformed
  `--pid`, or transport/auth error

## Request shapes

Verified against `mqtt-json-integrator-types/golden/`:

```json
{"tag": "DeleteUncreatedAll"}
{"tag": "DeleteUncreatedByChoice",
 "contents": {"deleteUncreatedLocations": [...], "deleteUncreatedPids": [...]}}
```

and likewise `DeleteStoredAll` / `DeleteStoredByChoice`. The nullary tags carry
**no** `contents` key. The unprocessed route takes no body at all.

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` (uncreated), `:259`
  (stored), `:270` (unprocessed)
- Types: `mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs`
- Lifecycle: `mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md`
- Route table: `_mqtt_integrator_routes/routes.py` (`delete_uncreated`,
  `delete_stored`, `delete_unprocessed`)

## Related skills

- `onping-mqtt-integrator-blacklist` — make a candidate stay gone (what you usually want)
- `onping-mqtt-integrator-artifacts-export --json` — lossless backup before `--target stored`
- `onping-mqtt-integrator-artifacts-import` — restore a record you deleted
- `onping-mqtt-integrator-unprocessed` — inspect or export the queue before clearing it
- `onping-massdelete` — unrelated; deletes real OnPing parameters, which this skill never does
