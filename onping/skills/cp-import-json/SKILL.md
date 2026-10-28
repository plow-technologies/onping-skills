---
name: cp-import-json
description: Format and validate OnPing control-parameter JSON imports. Use to normalize friendly JSON, expand omitted defaults, validate trigger/output rules, and optionally fetch+normalize from cp-list.
allowed-tools: Bash(uv run *)
---

# Control Parameter Import JSON

Normalize, expand, validate, and fetch+normalize control-parameter JSON import payloads.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **lj-profile** — Look up the Lumberjack ID for a location ID
- **cp-list** — List control parameters by Lumberjack ID
- **cp-script-fetch** — Fetch script metadata referenced by control parameters
- **inferno-cp-import** — Push the shaped/validated CP array into OnPing (`POST /cpInferno/import`); this skill only shapes/validates, it does not write
- **inferno-lookup** — Inferno language and control runtime notes

## Scope

- JSON-first workflow (YAML and Dhall are out of scope for this skill version)
- Deterministic conversion between verbose and friendly CP JSON
- Semantic validation checks, including output PID exclusivity warnings

## Commands

```bash
uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py normalize --input cp.json
```

```bash
uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py expand --input cp-friendly.json
```

```bash
uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py validate --input cp-friendly.json
```

```bash
uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py validate --strict --input cp-friendly.json
```

## Fetch + Normalize

Requires a valid access token and one or more Lumberjack IDs:

```bash
uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py fetch-normalize "$ACCESS_TOKEN" 1001
```

Pipeline login and fetch-normalize:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py fetch-normalize "$ACCESS_TOKEN" 1001 1002
```

## Orphaned and Not-Readable CPs

`cp-list` output is a tagged list (see the cp-list Output section). Since onping 2026.10.14.0 (#16220) it can hold `OrphanedControlParameterInferno` elements: CPs whose output PID was deleted (`contents` is `[{cpId, cpData}, [<missing PID>, ...]]`). An orphan still holds its other outputs, but re-importing it as-is points at PIDs that do not exist.

- **`normalize` and `fetch-normalize` turn cp-list output into an import array.** Each `ReadableControlParameterInferno` element loses its `{tag, contents}` wrapper and becomes its `{cpId, cpData}` object: a friendly `cpId` string and the normalised `cpData`, in one normalize pass. `/cpInferno/import` reads `cpData` nested like this, and `inferno-cp-import` accepts it, so `cp-list` → `normalize` → `inferno-cp-import` works with no manual step.
- **The default trigger is omitted, on a create and an update alike.** The server's friendly format omits `OnInputChangeAny` and reads a missing trigger back as `OnInputChangeAny` (onping-frontend-types `ControlParametersInferno.hs`), so `/cpInferno/export/json` output has no trigger for such a CP. `normalize` matches it, and `inferno-cp-import` accepts an update with no trigger, previewing it as `trigger=<default: OnInputChangeAny>`.
- **Malformed elements are dropped and normalize exits 1.** A Readable or Orphaned element with no usable `{cpId, cpData}` (no `cpData` object, or no `cpId`, which would turn it into a create) is left out of the output and listed on stderr as malformed. The output is still written, but `normalize` and `fetch-normalize` exit 1. `validate` reports it as `malformed_element`, once per element.
- **A dropped element is removed, never left as `null`.** In an array it is left out; as a value under the root object its key is removed. When the document root is itself a list element that is not kept (not readable, an omitted orphan, or malformed), `normalize` writes `[]`, says so on stderr, and exits 1.
- **Orphans are omitted by default** and each omitted one is listed on stderr (path, cpId, name, missing PIDs, and any output PIDs it still claims). Pass `--include-orphans` to keep them, unwrapped like a readable CP; the kept ones are still listed on stderr. An omitted orphan still holds its live outputs on the server, so normalize also warns when a kept CP writes one of those PIDs (output exclusivity).
- **`validate`** reports each orphan as `orphaned_cp` at the element's path (for example `$[1]`) with the missing PIDs: a warning by default, an error under `--strict` (the code stays `orphaned_cp`).
- **`ProhibitedReadControlParameterInferno` and `FailedToReadControlParameterInfernoPermissions`** elements (contents: only the CPID) raise `not_readable` in `validate`, with the CPID: a warning by default, an error under `--strict`. `normalize` drops them (they hold no CP to import) and lists each one on stderr with its CPID.
- **An element with an unknown tag** (a `{tag, contents}` entry in a list array that is none of the four tags) raises `unknown_tag` in `validate` (warning; error under `--strict`), and `normalize` drops it with a stderr notice naming the tag. A tagged `outputs` or `trigger` inside a CP is not a list element.
- To fix an orphan, repoint its output through `/cpInferno/update` or delete it through `/cpInferno/delete`; no skill here wraps either.

```bash
# Keep orphans in the normalised document (default: omitted, listed on stderr)
uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py fetch-normalize "$ACCESS_TOKEN" 1001 --include-orphans

# cp-list -> normalize -> preview the import (one Lumberjack: the output is an array)
uv run ~/.claude/skills/cp-list/scripts/list_control_parameters.py "$ACCESS_TOKEN" 1001 > before.json
uv run ~/.claude/skills/cp-import-json/scripts/cp_import_json.py normalize --input before.json --output cps.json
uv run ~/.claude/skills/inferno-cp-import/scripts/import_inferno_cp.py "$ACCESS_TOKEN" --input cps.json --dry-run
```

With several Lumberjack IDs, `fetch-normalize` returns an object keyed by Lumberjack ID; import each array separately.

## Conversion Rules

See `references/json-rules.md` for all defaults and friendly/generic mapping rules used by this skill.

## CRITICAL: Outputs Must Match Script Return Type

Before writing `"outputs"` for any CP, you **must** fetch the script source via **cp-script-fetch** and inspect its return expression. A mismatch between the script's return type and the `outputs` format causes **silent runtime failure** — the CP executes but writes no values.

**Decision rule:**

1. **Bare scalar return** (script body ends with an expression like `x + 1` or `someValue`) → use scalar format:
   ```json
   "outputs": 500010
   ```

2. **Record return** (script body ends with `{fieldName = expr, ...}`) → use record format with **exact field names** from the script:
   ```json
   "outputs": {"output": 500010}
   ```

**Real bug example:** Four epoch time writer CPs (script `KKKKKKKK...`) return `{output = Time.timeToInt adjustedTime}` — a single-field record. They were incorrectly written as `"outputs": 500010` (scalar). The fix was `"outputs": {"output": 500010}`. The CPs ran without error but silently failed to write until corrected.

> **Rule of thumb:** When in doubt, fetch the script. Never guess the output format from the CP name or from other CPs that use a different script.

## Output

- `normalize` / `fetch-normalize`: friendly JSON; cp-list elements become `{cpId, cpData}` import entries (orphans omitted unless `--include-orphans`; not-readable and unknown-tag elements dropped; malformed elements dropped with exit 1; a dropped root element becomes `[]` with exit 1; every one of these listed on stderr)
- `expand`: explicit JSON (list elements are not filtered or unwrapped)
- `validate`: machine-readable report with `ok`, `errors`, `warnings`, and `stats` (`stats` also counts `orphanedControlParameters`, `notReadable`, `unknownTags` and `malformedElements`)

> **Same-Lumberjack Constraint:** All inputs and outputs of a control parameter must belong to the same Lumberjack. Use **lj-profile** to find the Lumberjack ID for a given location ID.

## Error Handling

- Invalid JSON input exits nonzero with parse details
- Validation exits nonzero when errors are present
- `--strict` upgrades warnings to errors (`orphaned_cp`, `not_readable` and `unknown_tag` keep their code; other warnings become `strict_warning`)
- `fetch-normalize` retries auth redirects up to 3 times and fails on non-200 HTTP responses
