# Inferno Control vs Virtual Parameters

This note complements `inferno-virtual-control.md`. The core Inferno syntax and modules are shared, but OnPing uses different runtime models for virtual parameters and control parameters.

## What Is Shared

- Same Inferno language syntax (functions, let bindings, pattern matching, modules)
- Same standard modules documented in `inferno-virtual-control.md` (Base, Array, Option, Text, Time)
- Same script fetch endpoint shape (`/script/id/{SCRIPT_ID}`), with script type metadata in response

## Runtime Differences (OnPing Model)

| Aspect | Virtual Parameters | Control Parameters |
| --- | --- | --- |
| Execution location | Evaluated in VP context | Evaluated on Lumberjack engine host |
| Scheduling | Derived from VP evaluation context | Explicit trigger config in payload (`cpData.trigger`) |
| Trigger modes | Not represented as CP-style trigger objects | `OnInputChange` and `OnCronSchedule` patterns observed |
| Output binding | VP configuration-specific | Explicit `cpData.outputs` with `ScalarOutput` or `RecordOutput` (each output parameter ID exclusive to one CP) |
| Identity | VP IDs and script references | `cpId.engineHost` + `cpId.perEngineId` per Lumberjack |

## Control Trigger Patterns

From `cpInferno/list`, control parameters include runtime trigger metadata:

- `OnInputChange` with:
  - `OnInputChangeOnly` and explicit input IDs
  - `OnInputChangeAny`
- `OnCronSchedule` with:
  - cron expression string
  - optional `{ "maxInterval": N }` object

## Control Output Patterns

From `cpInferno/list`, control parameters define write targets in `cpData.outputs`. The output type **must** match the script's return expression — a mismatch causes **silent runtime failure** (the CP runs but writes no values).

**How output type is determined:**

| Script return expression | Output type | Friendly JSON |
| --- | --- | --- |
| Bare scalar (e.g. `x + 1`, `someValue`) | `ScalarOutput` | `"outputs": pid` |
| Single-field record (e.g. `{output = expr}`) | `RecordOutput` | `"outputs": {"output": pid}` |
| Multi-field record (e.g. `{a = e1, b = e2}`) | `RecordOutput` | `"outputs": {"a": pidA, "b": pidB}` |

> **WARNING:** Never assume the output type from the CP name or from other CPs using a different script. Always fetch the script via **cp-script-fetch** and inspect its return expression. Example: epoch time writer CPs return `{output = Time.timeToInt adjustedTime}` (a record), not a bare scalar — using scalar format silently fails.

> **Output Exclusivity Rule:** Each output parameter ID can be written by at most one control parameter. Once a parameter ID appears in a control parameter's `cpData.outputs` (whether as a `ScalarOutput` target or within a `RecordOutput` mapping), that parameter ID is unavailable as an output for any other control parameter. When examining existing CPs or planning new ones, check all `cpData.outputs` across the relevant Lumberjack to confirm the target is not already claimed.

## Practical Workflow

1. Use `cp-list` to fetch control parameters by Lumberjack ID.
2. Read `cpData.trigger`, `cpData.inputs`, `cpData.outputs`, and `cpData.script`.
3. Use `cp-script-fetch` with `cpData.script` to fetch Inferno source/history payload.
4. Use `inferno-virtual-control.md` for language reference while interpreting the control script.
5. Confirm the script's return type (bare scalar vs record) matches the `cpData.outputs` format. Fetch the script source if needed.

## Notes

- This document captures observed API/runtime differences, not a complete validator for every deployment policy.
- If a construct compiles but behavior differs at runtime, treat `cpData` trigger/output config as the first troubleshooting surface.
