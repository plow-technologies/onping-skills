---
name: onping-mqtt-integrator-config
description: Read or update one Lumberjack's mqtt-json-integrator MQTT config (broker, topic, auto-execute flag, unprocessed-queue cap) via GET/POST /mqtt/json/integrator/{serial}/mqtt/config. Read-modify-write, because the handler consumes a whole MqttConfig and a partial body would drop fields. MUTATES OnPing only with --yes; refuses to change the Company/Site/Group identity fields that decide where generated objects land. Keyed by LJSerial, not location refId.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator config

> **⚠️ WARNING: this skill changes live data.**
> It rewrites a Lumberjack's integrator MQTT settings (broker, topic, auto-execute, queue cap). Undo by re-running with the previous values, which the before/after diff prints. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Reads and edits the MQTT connection settings at the top of the integrator UI for
one Lumberjack: which broker and topic to subscribe to, whether generation rules
fire automatically on every message, and whether the unprocessed queue is capped.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver** — it watches MQTT traffic and generates locations and PIDs from
pattern rules. Integrator routes are keyed by **`LJSerial`**; the driver skills
(`onping-*-mqtt-json`) are keyed by location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## Safety

- **Mutating.** A real write happens only with `--yes`. With no flags at all the
  skill just prints the current config. If you pass edit flags without `--yes`
  (or with `--dry-run`) it prints a before/after diff and exits without POSTing.
  `--dry-run` wins if both are passed.
- **Read-modify-write, always.** The handler is
  `requireInsecureJsonBody :: MqttConfig`, i.e. a whole-record write — a partial
  body silently drops every field it omits. The skill GETs the live record,
  overlays only the flags you passed, and POSTs the complete record back. If the
  GET fails, nothing is written.
- **Company / Site / Group are not editable here.** Those three fields decide
  where every generated location and PID is filed. Repointing them mid-stream
  splits one logical dataset across two destinations while leaving
  already-created objects behind, so the skill refuses and re-asserts the check
  after building the payload. Use the OnPing UI if that is genuinely intended.
- **No-op edits are detected.** Values that already match are dropped from the
  diff, so `--yes` on an unchanged config performs no write.

## Fields

| Field | Editable | Meaning |
|---|---|---|
| `mqttConfigBroker` | yes | Broker URI; expected to start with `mqtt://`, may carry `:port` |
| `mqttConfigTopic` | yes | Topic filter to subscribe to; `#` means everything |
| `mqttConfigExecuteRulesOnMessageReceive` | yes | Run all rules on every received message |
| `mqttConfigUnprocessedJsonObjectsSize` | yes | Cap on stored unprocessed objects; `null` = unlimited |
| `mqttConfigCompanyIdRef` | **no** | Company that owns generated objects |
| `mqttConfigSiteIdRef` | **no** | Site that owns generated objects |
| `mqttConfigGroupId` | **no** | Group that owns generated objects |

Verified against `mqtt-json-integrator-types/golden/MqttConfig/MqttConfig.json`.

## Two behaviors worth knowing before you edit

**The queue cap does not evict.** Once the stored unprocessed count reaches
`mqttConfigUnprocessedJsonObjectsSize`, new topic/message pairs are **ignored** —
existing data is preserved and incoming data is dropped, not rotated. To resume
ingestion you must raise or remove the cap, or clear the queue with
`onping-mqtt-integrator-unprocessed --clear`. (`data-lifetime-and-uniqueness-rules.md`,
"Life Cycle".)

**Auto-execute off means nothing happens on its own.** With
`--no-auto-execute`, rules never run against incoming data until something
triggers them; use `onping-mqtt-integrator-reports --execute` (or the UI) to run
them manually. Rule execution is blocking and single-threaded server-side.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-config/scripts/integrator_config.py

# Read the current config:
uv run "$SKILL" "$ACCESS_TOKEN" 1001

# Raw JSON:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --json

# Preview a topic change (no write):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --topic 'example/production/#'

# Apply it:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --topic 'example/production/#' --yes

# Turn off auto-execute and cap the queue at 5000:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --no-auto-execute --queue-cap 5000 --yes

# Remove the cap:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --no-queue-cap --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running `mqtt-json-integrator-server`
- `--broker URI` / `--topic FILTER` — connection settings
- `--auto-execute` / `--no-auto-execute` — the on-message rule trigger
- `--queue-cap N` / `--no-queue-cap` — the unprocessed-queue limit
- `--json` — raw config JSON (read mode only)
- `--dry-run`, `--yes` — mutation gates

A broker without the `mqtt://` prefix is written but warned about on stderr; the
UI documents that prefix as required.

## Finding the serial

The integrator must be installed on the target LJ. Use `lj-profile` to map an
OnPing location id to an `LJSerial` and `lj-deploy` to confirm
`mqtt-json-integrator-server` is installed. OnPing itself 404s the
router-address auto-update route when that package is absent
(`Handler/MqttJsonIntegrator/Service.hs`), which is a decent liveness
check.

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` (GET), `:126` (POST)
- Type: `mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs`
- Route table: `_mqtt_integrator_routes/routes.py` (`get_config`, `post_config`)

## Related skills

- `onping-mqtt-integrator-unprocessed` — see what the broker/topic is actually collecting
- `onping-mqtt-integrator-rules-export` / `-rules-import` — the rules themselves
- `onping-mqtt-integrator-reports` — rule-execution history and errors
- `lj-profile`, `lj-deploy` — find the serial, confirm the package is installed
