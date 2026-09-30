---
name: onping-mqtt-integrator-rule-parse
description: Validate mqtt-json-integrator generation-rule expressions via POST /mqtt/json/integrator/rule/parse (full grammar) or /jq/rule/parse (JQ-only). Read-only, stateless, and NOT scoped to a Lumberjack — no serial needed. Use before onping-mqtt-integrator-rules-import, whose only other failure signal is a 400 megaparsec dump. A parse failure arrives as HTTP 200 with a FailedToParseRules tag, so status alone is not a verdict; this skill exits non-zero instead. SKILL.md documents the rule grammar (static text, {topic|s#pat#rep#} sed, {jq}, template fields).
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator rule-parse

Validates one or more mqtt-json-integrator rule expressions against OnPing's own
parser. This is the cheapest useful thing in the integrator family: it needs no
Lumberjack, changes nothing, and catches the errors that otherwise surface only
as a rejected spreadsheet import.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. It watches MQTT traffic and generates locations and PIDs from
pattern rules; the driver skills (`onping-*-mqtt-json`) work one layer down on
objects that already exist. See `_mqtt_integrator_routes/SKILL.md`.

## Safety

**Read-only and stateless.** Both routes only parse a string. They are not
scoped to an `LJSerial`, do not read or write stored rules, and cannot affect
unprocessed data, artifacts, or anything in OnPing. There is no `--yes` because
there is nothing to gate.

## Two parsers, two different answers

| Flag | Server function | Accepts | Use for sheet columns |
|---|---|---|---|
| `--full` (default) | `Rules.parseRules` | static text, `{topic\|s#pat#rep#}` sed, `{jq}`, `{jq}` with template fields | Location Name, Location Match, PID Topic, PID Description |
| `--jq-only` | `Rules.parseRuleJqOnly` | plain JQ selectors only — rejects the sed/topic forms | PID Time, PID Value |

Validating a PID Value with `--full` will pass expressions the real PID-value
path rejects, so match the flag to the column.

## The two traps

**The request body is a bare JSON string.** The handler is
`requireInsecureJsonBody :: Handler Text`, so the wire body is `"…rule…"` —
quotes included, no wrapper object. `{"rule": "..."}` returns 400. The script
handles this; the note matters if you ever curl it by hand.

**A parse failure comes back as HTTP 200.** The response is a `RulesParseResult`:

```json
{"tag": "ParsedRulesSuccesfully"}
{"tag": "FailedToParseRules", "contents": "<megaparsec error>"}
```

`ParsedRulesSuccesfully` is misspelled server-side; that is the real tag. Because
both outcomes are 200s, checking status is not enough — this skill exits **1**
when any expression fails so it can gate a pipeline.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# Validate a location-match rule (full grammar):
uv run ~/.claude/skills/onping-mqtt-integrator-rule-parse/scripts/parse_rule.py \
  "$ACCESS_TOKEN" '{topic|s#/([^/]*)/([^/]*)/([^/]*)/*.*#\1-\2-\3#}'

# Validate a PID value selector (JQ only):
uv run .../parse_rule.py "$ACCESS_TOKEN" --jq-only '.temperature'

# Validate a whole column at once, one expression per line:
uv run .../parse_rule.py "$ACCESS_TOKEN" --file location-rules.txt

# Machine-readable:
uv run .../parse_rule.py "$ACCESS_TOKEN" --json '.timestamp'
```

**Quote every expression in single quotes.** Rules contain `{`, `}`, `#`, `|` and
backslash escapes; unquoted, the shell mangles them and you validate something
other than what you wrote.

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `rule...` — one or more expressions
- `--file PATH` — read expressions from a file, one per line; blank lines and
  `#` comment lines are skipped
- `--full` / `--jq-only` — pick the parser (default `--full`)
- `--json` — emit `{mode, checked, failed, results[]}` instead of text

### Exit codes

- `0` — every expression parsed
- `1` — at least one failed to parse, or a transport/auth error

## Rule grammar reference

Three constructs compose freely inside one expression.

**Static text** — anything outside braces is literal.

**Sed on the topic** — `{topic|s#pattern#replacement#}`. The delimiter is
whatever character follows `s` (`#`, `/`, `@`, …), and `\1`, `\2` … are capture
backreferences:

```
Topic: /facility1/building2/sensor001/data
{topic|s#/([^/]*)/([^/]*)/([^/]*)/.*#\1-\2-\3#}   -> facility1-building2-sensor001
{topic|s#.*/([^/]*)/.*#\1#}                        -> sensor001
```

**JQ on the message** — `{.field}` or a bare selector, applied to the JSON
payload. `.timestamp`, `.temperature`, `select(...)` and friends.

**Template fields** — a JQ expression may reference discovered fields, in which
case the parser substitutes dummy values before validating. Expressions it deems
"complex" skip JQ validation entirely (`isComplexExpression` in `Parse.hs`), so a
`ParsedRulesSuccesfully` on a template expression is weaker evidence than on a
plain one.

Worked examples for both rule kinds are in
`~/all/mqtt-json-integrator/README.md` ("Rule Examples", "SED Expression Guide").

## Which sheet column is which

The rules spreadsheet's uniqueness key is column 3, **Location Match** — a
location's identity is the output of that rule against a topic/message pair.
Column 2, Location Name, is display only and need not be unique. Likewise PID
identity is column 5, **PID Topic**. Validating those two columns matters most,
since a rule that parses but matches nothing silently generates zero objects.

## Source of truth

- Handlers: `onping/Handler/MqttJsonIntegrator/Service.hs` and `:296`
- Parser: `mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types/Rules/Parse.hs`
- Result type: `onping-frontend-types/src/OnPing/Frontend/Types/MqttJsonIntegrator.hs`
- Route table: `_mqtt_integrator_routes/routes.py` (`parse_rule`, `parse_jq_rule`)

## Related skills

- `onping-mqtt-integrator-rules-export` / `-rules-import` — the XLSX read/write path
- `onping-mqtt-integrator-reports` — where rule-execution errors actually surface
- `inferno-lookup` — unrelated; Inferno scripts, not integrator rules
