---
name: onping-mqtt-integrator-unprocessed
description: Inspect the mqtt-json-integrator unprocessed queue for one Lumberjack via GET /mqtt/json/integrator/{serial}/unprocessed/data — the raw MQTT topic/message pairs collected, plus the uncreated locations and PIDs the rules generated from them. Read-only by default; --clear --yes drops ALL pairs unconditionally (no selection possible, no undo, no import counterpart). The queue does NOT evict when capped — it ignores new messages, which is the usual reason a healthy broker looks silent. Entries are unique per (topic, message) pair, not per topic.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator unprocessed

Shows the front of the integrator pipeline for one Lumberjack: what MQTT data has
arrived, and what the rules have made of it but not yet created.

```
MQTT -> [unprocessed] -> [rules] -> uncreated -> created -> mqtt-json driver
          ^ this skill              ^ this skill too
```

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## Safety

- **Read-only by default.** Inspection makes only GETs.
- **`--clear` is destructive and unconditional.** The delete route takes no body
  and no selection: it drops **all** stored topic/message pairs. It does not
  touch rules, uncreated objects, or created objects. Requires `--yes`;
  `--dry-run` wins if both are passed.
- **No undo, no import route.** The stored payloads are the only record of what
  the broker actually sent, and there is no way to put them back. Use
  `--export PATH` before clearing if they matter.

## The three collections

One `GET` returns all of `UnprocessedData`:

| Field | What it is |
|---|---|
| `unprocessedJsonObjects` | raw `[topic, message]` **pairs** (2-element arrays) |
| `uncreatedLocations` | locations the rules produced, not yet created |
| `uncreatedPids` | PIDs the rules produced, not yet created |

**Uniqueness is per (topic, message) pair, not per topic.** The queue is a set of
pairs, so the same topic with two different payloads occupies two entries, and the
same payload on two topics likewise. `--topics` shows which topics carry more than
one distinct message.

## Two behaviors that explain most confusion

**A capped queue ignores rather than evicts.** Once the stored count reaches
`mqttConfigUnprocessedJsonObjectsSize`, new messages are **dropped** and existing
data is preserved. A correctly configured broker can therefore look completely
silent. Fix by raising the cap
(`onping-mqtt-integrator-config --queue-cap` / `--no-queue-cap`) or clearing here.

**Data present but nothing uncreated means the rules matched nothing.** That is a
rules problem, not an ingestion problem — check
`onping-mqtt-integrator-rules-export --summary`, validate expressions with
`onping-mqtt-integrator-rule-parse`, and confirm the rules actually ran via
`onping-mqtt-integrator-reports`. The skill prints this hint when it sees that
state.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-unprocessed/scripts/unprocessed.py

# Counts and health hints:
uv run "$SKILL" "$ACCESS_TOKEN" 1001

# What topics are arriving:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --topics

# Look at real payloads (to write JQ selectors against):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --show 3

# What the rules have generated but not created:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --uncreated

# Back up the payloads:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --export /tmp/unprocessed-1001.json

# Clear the queue (preview, then apply):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --clear
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --clear --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `--json` — raw `UnprocessedData` JSON
- `--export PATH` — write the topic/message pairs via the server's own export
  route, which returns **only** the pairs (not the uncreated sets)
- `--topics` — distinct topics with a per-topic message count
- `--show N` — print the first N pairs in full
- `--uncreated` — list uncreated locations and PIDs
- `--clear`, `--dry-run`, `--yes` — the destructive path

## Practical use: writing rules against real payloads

`--show N` is the fastest way to get the JSON your rules must parse. Copy a real
payload, work out the JQ selectors for value and timestamp, validate them with
`onping-mqtt-integrator-rule-parse --jq-only`, then put them in the rules sheet.
Doing it in that order avoids the common loop of importing a sheet, seeing zero
objects generated, and not knowing whether the rule or the data is wrong.

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` (GET), `:148`
  (export), `:270` (delete)
- Type: `mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs`
- Lifecycle: `mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md`,
  "Unprocessed Data"
- Route table: `_mqtt_integrator_routes/routes.py` (`get_unprocessed`,
  `export_unprocessed`, `delete_unprocessed`)

## Related skills

- `onping-mqtt-integrator-config` — the broker/topic/queue-cap settings that decide what lands here
- `onping-mqtt-integrator-rule-parse` — validate selectors against payloads seen here
- `onping-mqtt-integrator-create` — turn the uncreated objects into real ones
- `onping-mqtt-integrator-blacklist` — stop specific uncreated objects from ever being created
- `onping-mqtt-integrator-delete --target uncreated` — drop generated candidates without creating them
