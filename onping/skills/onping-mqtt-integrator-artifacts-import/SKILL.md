---
name: onping-mqtt-integrator-artifacts-import
description: Upload an artifacts XLSX to POST /mqtt/json/integrator/{serial}/artifacts/import (multipart form; f1 = the file). MUTATES the integrator's record with --yes but CREATES NOTHING in OnPing or the mqtt-json driver — the route that creates real objects is POST .../artifacts (onping-mqtt-integrator-create). Its actual purpose is SUPPRESSION: anything recorded as created is skipped by the create pipeline. A repsert, not a replace — absent rows are not deleted. Column 3 (Location ID Ref) is trusted verbatim and never verified. The export that produces this sheet is lossy, so back up with --json first.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator artifacts-import

Writes to the integrator's record of objects it created, for one Lumberjack.

## The name collision, up front

Two routes differ by one path segment and do completely different things:

| Route | What it does | Skill |
|---|---|---|
| `POST .../artifacts/import` | repserts the integrator's own **record**; creates nothing | **this skill** |
| `POST .../artifacts` | five-stage **create** of real OnPing locations and driver parameters | `onping-mqtt-integrator-create` |

If you want objects to exist, you want the other skill.

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**, not location refId. See
`_mqtt_integrator_routes/SKILL.md`.

## What this is actually for

The create pipeline **skips anything already recorded as created**. So writing a
record is how you suppress creation. The upstream lifecycle doc names this
directly:

> "the user can import Created Objects from Excel. This does not generate anything
> on mqtt-json or OnPing. It just stores them in mqtt-json-integrator-server and
> can be used to prevent Creatable Objects from being turned into Created Objects."

Two real uses:

- **Suppress creation** of objects that already exist (e.g. ones made by hand, or
  by a different LJ) so the integrator does not duplicate them.
- **Restore a record** after `onping-mqtt-integrator-delete --target stored`
  forgot it — which is important, because forgetting also *un-suppresses*
  creation and invites duplicates.

For blocking a specific object permanently, `onping-mqtt-integrator-blacklist` is
the purpose-built tool; this route is the bulk path.

## Repsert, not replace

Unlike `-rules-import`, this import is **keyed**: locations upsert by
`storedLocationUniqueIdentifier` (column 1) and PIDs by their
(location, topic, value-selector) triple. **Rows absent from the sheet are not
deleted.** Removing a record needs
`onping-mqtt-integrator-delete --target stored`.

Because PIDs live in a set keyed on those three fields, duplicate rows collapse
silently — the skill warns when it sees them.

## Two things the server does not check

**Column 3, "Location ID Ref", is trusted verbatim.** It becomes both
`storedLocationIdRef` and every PID's `storedPidLocationIdRef`, with no
verification that the refId exists in OnPing. A wrong number yields a record
pointing at the wrong location, or at nothing. The skill at least enforces that
it is an integer.

**The export → import round trip is lossy.** `Artifacts/ImportExport.hs` drops
`localParameterTime` and collapses unrecognized values to `Double 0.0` / `"0.0"`.
Re-importing an exported sheet therefore **degrades** the record. Back up with
`onping-mqtt-integrator-artifacts-export --json` (lossless) before doing it.

## The `f1` field-name gotcha

The handler's form is `renderDivs $ fileAFormReq "File"`. `"File"` is a **label**;
Yesod's `renderDivs` names fields positionally, so the real multipart field is
**`f1`**. Posting `File` yields `400 FormFailure`. Same trap as the rules import,
the logtable import, and singlewell-manual.

## Safety

- **Mutating** (integrator store only). No POST without `--yes`; without it, or
  with `--dry-run`, the skill validates, compares against the live record, and
  previews. `--dry-run` wins if both are passed.
- **Header check rejects the wrong flavor.** A rules sheet uploaded here is
  refused with a pointer to `-rules-import`. Column 11 differs between the two
  (`ReadOnly`/`Writeable` here, boolean there), as does the meaning of column 5.
- **Conflict detection.** A location key appearing twice with different
  name/refId is an error, since the record is keyed on column 1 and one row would
  silently win.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-artifacts-import/scripts/import_artifacts.py

# 1. Lossless backup first:
uv run ~/.claude/skills/onping-mqtt-integrator-artifacts-export/scripts/export_artifacts.py \
  "$ACCESS_TOKEN" 1001 --json --out backup-1001.json

# 2. Preview the import:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 artifacts.xlsx

# 3. Apply:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 artifacts.xlsx --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `spreadsheet` — path to the artifacts XLSX
- `--skip-live-check` — skip the new/overwritten comparison
- `--dry-run`, `--yes` — mutation gates

### Exit codes

- `0` — validated and (with `--yes`) uploaded
- `1` — validation failure, header mismatch, empty sheet, or transport/auth error

## The 12 columns

| # | Header | Notes |
|---|---|---|
| 1 | Location Unique Identifier | **the record key** |
| 2 | Location Name | |
| 3 | Location ID Ref | **integer**; OnPing refId, trusted verbatim |
| 4 | PID Description | |
| 5 | PID Topic | a resolved topic (not a rule) — part of the PID key |
| 6 | PID Value Selector | plain JQ — part of the PID key |
| 7 | PID Time Selector | plain JQ |
| 8 | PID Time Format | `ISO`, `LumberjackTime`, `Format: <fmt>` |
| 9 | PID Value Type | `Bool`, `Double`, `Utf8Text24`, `Utf8Text40`, `Utf8Text184` |
| 10 | PID Value | captured value as text |
| 11 | PID Read Only | **`ReadOnly` / `Writeable`** — boolean in the rules sheet |
| 12 | PID Local Only | `LocalOnly` or `PushToRTUClient` |

Schema lives in `_mqtt_integrator_routes/rules_sheet.py`.

## Source of truth

- Handler: `onping/Handler/MqttJsonIntegrator/Service.hs`
- Rebuild logic: `onping/Handler/MqttJsonIntegrator/Artifacts/ImportExport.hs`
  (`reconstructArtifacts`)
- Lifecycle: `mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md`,
  "Created Objects"
- Route table: `_mqtt_integrator_routes/routes.py` (`import_artifacts`)

## Related skills

- `onping-mqtt-integrator-artifacts-export` — step one; use `--json` for a lossless backup
- `onping-mqtt-integrator-create` — the route that actually creates objects
- `onping-mqtt-integrator-blacklist` — the purpose-built way to block one object
- `onping-mqtt-integrator-delete --target stored` — remove records (leaves real objects orphaned)
