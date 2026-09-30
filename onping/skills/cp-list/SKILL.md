---
name: cp-list
description: List OnPing control parameters for one or more Lumberjack IDs. Use when discovering control parameter names, triggers, inputs/outputs, and script IDs.
allowed-tools: Bash(uv run *)
---

# Control Parameter List

List control parameters configured on one or more Lumberjack edge devices.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **lj-profile** — Look up the Lumberjack ID for a location ID
- **cp-script-fetch** — Fetch Inferno source and metadata by script ID
- **inferno-lookup** — Reference Inferno language docs and control-vs-virtual notes

## Typical Workflow

```
0. (Optional) Look up the Lumberjack ID for a location (lj-profile)
1. Login (onping-login) -> access token
2. List control parameters by Lumberjack ID (cp-list)
3. Copy a script ID from cpData.script
4. Fetch script source (cp-script-fetch)
5. Use inferno-lookup to review language details
```

## Usage

Requires a valid access token and one or more numeric Lumberjack IDs:

```bash
uv run ~/.claude/skills/cp-list/scripts/list_control_parameters.py "$ACCESS_TOKEN" 1001
```

Run login and list in a single pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/cp-list/scripts/list_control_parameters.py "$ACCESS_TOKEN" 1001
```

You can pass multiple Lumberjack IDs:

```bash
uv run ~/.claude/skills/cp-list/scripts/list_control_parameters.py "$ACCESS_TOKEN" 1001 1002 1003
```

## Output

- One Lumberjack ID: raw JSON array returned by `cpInferno/list`
- Multiple Lumberjack IDs: JSON object keyed by Lumberjack ID, each value the raw JSON array for that ID

> **Same-Lumberjack Constraint:** All inputs and outputs of a control parameter must belong to the same Lumberjack. Use **lj-profile** to find the Lumberjack ID for a given location ID.

> **Output Exclusivity:** Only one control parameter can write to a given output parameter ID. Each target parameter ID in `ScalarOutput` or `RecordOutput` is exclusive to that control parameter. To assign an output to a different CP, the existing assignment must be removed first.

## Error Handling

- If the access token is invalid or expired, each request retries up to 3 times before failing
- Lumberjack IDs must be integers
- Network errors and non-200 HTTP responses are reported to stderr
- Invalid JSON responses are reported with the raw response body
