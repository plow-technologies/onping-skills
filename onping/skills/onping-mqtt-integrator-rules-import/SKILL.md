---
name: onping-mqtt-integrator-rules-import
description: Upload a generation-rule XLSX to POST /mqtt/json/integrator/{serial}/rules/import (multipart form; f1 = the file). MUTATES OnPing with --yes. DESTRUCTIVE — this REPLACES THE ENTIRE RULE SET, so any rule missing from the sheet is deleted, and every surviving rule is renumbered because identifiers are derived from row order. The skill fetches the live rules first and reports exactly what would be added, kept, and DROPPED before writing. Rules are grouped by CONSECUTIVE rows sharing columns 1-3; non-adjacent blocks for one location silently become two rules. SKILL.md documents the 12-column format and the f1 field-name gotcha.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator rules-import

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> It replaces every generation rule on a Lumberjack's integrator and renumbers all rule ids; `--execute` also runs the new rules. There is no undo; export the current rules first with `onping-mqtt-integrator-rules-export` and re-import that sheet to restore them. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Uploads an edited generation-rule spreadsheet for one Lumberjack's integrator.
This is the write counterpart to `onping-mqtt-integrator-rules-export`.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## This replaces everything — it is not a merge

The handler routes to `postImportGenerationRules`, whose own docstring says "this
overwrite any existing rules". The upstream lifecycle doc is blunter:

> "when you import it deletes everything and rebuilds the rule system from the
> excel file. When you import an excel file you should have all the rules you want
> in there. Otherwise, you will have to redefine them."

So the workflow is **export → edit → import**, and the sheet must contain every
rule you intend to keep. There is no server-side merge and no undo.

To make that survivable, the skill **fetches the live rules before uploading** and
prints a diff — added, kept, and `DROPPED` — with every rule that would be deleted
named explicitly. An empty sheet is refused outright rather than silently wiping
the LJ.

## Identifiers get renumbered

`reconstructGenerationRules` assigns every `LocationRuleIdentifier` and
`PidRuleIdentifier` from **row order**. Even a byte-identical round-trip renumbers
all of them, so anything holding a rule id externally is stale afterward.

The spreadsheet cannot express ids at all. To change one rule while preserving
ids, use the incremental `POST .../generation/rules` path with
`UpdateGenerationRules` ops (`RepsertLocationRule`, `RemovePidRule`, …) — that
route is documented in `_mqtt_integrator_routes/routes.py` (`post_rules`) but is
not wrapped by this skill.

## Row grouping — the silent failure

Rules are grouped by **consecutive** rows whose columns 1-3 (Location Selector
Name, Location Name, Location Match) are identical. Two non-adjacent blocks for
the same location become **two separate location rules** with duplicated PIDs, and
the server accepts that without complaint. The pre-flight warns when it sees it;
sort the sheet so each location's rows sit together.

A row with columns 4-12 all empty is a location-only rule. Filling only some of
them is rejected with `Row <n> has incomplete PID data`.

## The `f1` field-name gotcha

The import handler defines its multipart form as:

```haskell
form :: Form FileInfo
form = renderDivs $ fileAFormReq "File"
```

`"File"` is a **label**, not a field name. Yesod's `renderDivs` auto-generates the
actual multipart field *names* positionally, so it is **`f1`**. Posting `File`
yields `400 FormFailure`. The frontend confirms it
(`OnpingFetch_ImportParameters.res` does `ret.append("f1", blob)`). Same trap
as the logtable and singlewell-manual imports.

## Safety

- **Mutating.** No POST without `--yes`. Without it (or with `--dry-run`) the
  skill validates the sheet, diffs it against the live rules, previews the result,
  and exits. `--dry-run` wins if both are passed.
- **Pre-flight validation is local plus one GET.** Header row must match the rules
  schema exactly; a sheet whose headers match the *artifacts* schema is rejected
  with a pointer to the right skill. Every row is checked for the required
  location columns, the all-or-nothing PID block, and the enum vocabularies —
  including column 11, which is a **boolean** in this sheet and
  `ReadOnly`/`Writeable` in the artifacts sheet.
- **An empty sheet is refused**, since importing it would delete every rule.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-rules-import/scripts/import_rules.py

# 1. Back up (mandatory in practice):
uv run ~/.claude/skills/onping-mqtt-integrator-rules-export/scripts/export_rules.py \
  "$ACCESS_TOKEN" 1001 --out before-import.xlsx

# 2. Edit before-import.xlsx, then preview — shows what would be dropped:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 edited.xlsx

# 3. Apply:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 edited.xlsx --yes

# Apply and immediately run the new rules:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 edited.xlsx --yes --execute
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `spreadsheet` — path to the rules XLSX
- `--execute` — after a successful import, run the new rules against stored
  unprocessed data (blocking; creates nothing in OnPing)
- `--skip-live-check` — skip the add/drop diff; you lose the deletion warning
- `--dry-run`, `--yes` — mutation gates

### Exit codes

- `0` — validated and (with `--yes`) uploaded
- `1` — validation failure, header mismatch, empty sheet, or transport/auth error

## After importing

The new rules are **stored but not run**. They fire on the next message if
`mqttConfigExecuteRulesOnMessageReceive` is on; otherwise trigger them with
`--execute` or `onping-mqtt-integrator-reports --execute --yes`. Either way the
outcome — matches, counts, errors — is only visible in the execution report, since
the execute route returns an empty envelope.

Importing rules creates nothing in OnPing. It produces *uncreated candidates*;
`onping-mqtt-integrator-create` is what turns those into real objects.

## The 12 columns

| # | Header | Notes |
|---|---|---|
| 1 | Location Selector Name | internal label |
| 2 | Location Name | display name; need not be unique |
| 3 | Location Match | **uniqueness key** — a location is the output of this rule |
| 4 | PID Selector Name | internal label |
| 5 | PID Topic | **PID uniqueness key** |
| 6 | PID Time | JQ selector |
| 7 | PID Time Format | `ISO`, `LumberjackTime`, `Format: <fmt>` |
| 8 | PID Description | |
| 9 | PID Value | JQ selector |
| 10 | PID Type | `Bool`, `Double`, `Utf8Text24`, `Utf8Text40`, `Utf8Text184` |
| 11 | PID Read Only | **BOOLEAN** here; strings in the artifacts sheet |
| 12 | PID Local Only | `LocalOnly` or `PushToRTUClient` |

Validate edited expressions in columns 2, 3, 5, 8 with
`onping-mqtt-integrator-rule-parse` and columns 6, 9 with
`... rule-parse --jq-only` before uploading. Schema lives in
`_mqtt_integrator_routes/rules_sheet.py`.

## Source of truth

- Handler: `onping/Handler/MqttJsonIntegrator/Service.hs`
- Rebuild logic: `onping/Handler/MqttJsonIntegrator/Rules/ImportExport.hs`
  (`reconstructGenerationRules`, `groupByLocationId`)
- Lifecycle: `mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md`,
  "Processing Rules"
- Route table: `_mqtt_integrator_routes/routes.py` (`import_rules`)

## Related skills

- `onping-mqtt-integrator-rules-export` — step one; also `--json` for rule ids
- `onping-mqtt-integrator-rule-parse` — validate expressions before uploading
- `onping-mqtt-integrator-reports` — the only place execution results appear
- `onping-mqtt-integrator-create` — create the objects the rules generate
