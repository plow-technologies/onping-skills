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

- `normalize` / `expand` / `fetch-normalize`: transformed JSON
- `validate`: machine-readable report with `ok`, `errors`, `warnings`, and `stats`

> **Same-Lumberjack Constraint:** All inputs and outputs of a control parameter must belong to the same Lumberjack. Use **lj-profile** to find the Lumberjack ID for a given location ID.

## Error Handling

- Invalid JSON input exits nonzero with parse details
- Validation exits nonzero when errors are present
- `--strict` upgrades warnings to errors
- `fetch-normalize` retries auth redirects up to 3 times and fails on non-200 HTTP responses
