---
name: onping-mqtt-integrator-reports
description: Read mqtt-json-integrator rule-execution reports for one Lumberjack via GET /mqtt/json/integrator/{serial}/execute/rules/report — the ONLY place execution errors and match counts surface, since the execute route itself returns an empty envelope. --execute --yes runs all stored rules against all stored unprocessed data (blocking, serialized server-side, creates nothing in OnPing) and then prints the resulting report. --delete-all --yes clears the whole history; no per-report delete exists. The counts report NEW objects only, so 0/0 means "nothing new", not necessarily "nothing matched".
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator reports

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> `--execute` runs the generation rules and adds candidates and a report; `--delete-all` clears every execution report. Clearing reports cannot be undone; remove added candidates with `onping-mqtt-integrator-delete --target uncreated`. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Reads the history of rule executions for one Lumberjack's integrator, and
triggers a run.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## Why this skill exists

`POST .../generation/rules/execute` returns an **empty success envelope** no
matter what happened. It does not tell you how many rules ran, what they matched,
or what failed. All of that lives in the `ExecuteRulesReport` the run leaves
behind — so this is the only place execution errors are visible at all. The skill
therefore folds the execute route in and reads the resulting report for you.

## Safety

- **Read-only by default.**
- **`--execute` mutates integrator state** (it appends uncreated candidates and a
  report) but creates **nothing** in OnPing or the mqtt-json driver. Requires
  `--yes`. It is blocking and serialized server-side — the server refuses
  concurrent executions — and can take a while against a large queue with many
  rules.
- **`--delete-all` is destructive**: it clears every report. There is no
  per-report delete and no undo. Requires `--yes`.
- `--dry-run` wins over `--yes` for both.

This is also the one integrator mutation that is a real HTTP `DELETE`; every
other one is a `POST`.

## Report fields

| Field | Meaning |
|---|---|
| `executeRulesReportSource` | `ExecuteRulesManual` or `ExecuteRulesAutomatic` (bare string) |
| `executeRulesReportExecuteTime` | ISO-8601 UTC |
| `executeRulesCount` | rules evaluated |
| `executeRulesNewUncreatedLocationsCount` | **new** uncreated locations produced |
| `executeRulesNewUncreatedPidsCount` | **new** uncreated PIDs produced |
| `executeRulesErrors` | list of error strings |

Verified against
`mqtt-json-integrator-types/golden/ExecuteRulesReport/ExecuteRulesReport.json`.

## Reading the counts correctly

**"NEW" is doing real work in those field names.** The counts report only what a
run *added*. Re-running over data whose objects were already generated reports
`0 / 0` — that means "nothing new", not "nothing matched". The interpretation
depends on context:

| Counts | Errors | Meaning |
|---|---|---|
| `0 / 0` on already-processed data | none | normal; everything was already generated |
| `0 / 0` on fresh data | none | **the rules matched nothing** — a rules or selector problem |
| non-zero | none | working; candidates are waiting for `-create` |
| any | some | rules ran but partially failed; read the error text |

When a run produces nothing new, the skill says which case it thinks you are in
and points at `onping-mqtt-integrator-unprocessed --show 3` for comparing real
payloads against your selectors.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-reports/scripts/reports.py

# Full history, newest first:
uv run "$SKILL" "$ACCESS_TOKEN" 1001

# Just the last run:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --latest

# Only runs that failed — exits 1 if any exist:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --errors-only

# Trigger a run and read its report:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --execute --yes

# Preview what a run would do:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --execute

# Clear the history:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --delete-all --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `--json` — raw report array
- `--latest` / `--limit N` — trim the output
- `--errors-only` — only reports with errors; **exits 1** if any are found
- `--execute` — run all stored rules (needs `--yes`)
- `--delete-all` — clear all reports (needs `--yes`)
- `--dry-run`, `--yes` — mutation gates

### Exit codes

- `0` — success
- `1` — transport/auth error, `--errors-only` found failures, or the report from
  a `--execute` run recorded errors

## When you need `--execute`

- `mqttConfigExecuteRulesOnMessageReceive` is off (see
  `onping-mqtt-integrator-config`), so rules never fire on their own
- you just imported a new rule set and want it applied to data already queued,
  without waiting for fresh MQTT traffic
- you are debugging a rule and want a deterministic run against a fixed queue

An empty report list means the rules have never run on this LJ — either
auto-execute is off and nobody has run them manually, or the history was cleared.

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` (GET), `:281`
  (DELETE), `:265` (execute)
- Type: `mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs`
- Route table: `_mqtt_integrator_routes/routes.py` (`get_reports`,
  `delete_reports`, `execute_rules`)

## Related skills

- `onping-mqtt-integrator-unprocessed` — the data a run consumes, and the candidates it produces
- `onping-mqtt-integrator-rules-export` / `-rules-import` — the rules being executed
- `onping-mqtt-integrator-rule-parse` — validate an expression before importing it
- `onping-mqtt-integrator-create` — turn the resulting candidates into real objects
- `onping-mqtt-integrator-config` — the auto-execute flag
