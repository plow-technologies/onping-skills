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

stdout is always the server JSON, unchanged (`cp-import-json` and `cpid-migration` read it as-is). Each array element is tagged; since onping 2026.10.14.0 (#16220) there are four tags:

| `tag` | `contents` | Meaning |
|---|---|---|
| `ReadableControlParameterInferno` | `{"cpId": {...}, "cpData": {...}}` | A CP you can read. |
| `OrphanedControlParameterInferno` | `[{"cpId": {...}, "cpData": {...}}, [<missing PID>, ...]]` (an **array**, not an object) | An output PID was deleted. The CP still holds its other outputs. Shown to users who can access the Lumberjack and read its inputs; it can be repointed through `/cpInferno/update` or deleted through `/cpInferno/delete` (no skill here wraps either). Before #16220 it was listed as prohibited. |
| `ProhibitedReadControlParameterInferno` | the CPID `{"engineHost": ..., "perEngineId": ...}` | You may not read this CP. Since #16220 a failed permission lookup is reported this way too. |
| `FailedToReadControlParameterInfernoPermissions` | the CPID | The permission lookup failed (still in the type; `/cpInferno/list` reports such failures as prohibited since #16220). |

When any element is not `ReadableControlParameterInferno`, the script prints a notice on **stderr** (stdout is unchanged and the exit code stays 0): the count per tag; each orphan's cpId, name and missing output PIDs; each prohibited or failed CPID; and any unknown tag by name. For example:

```
cp-list: Lumberjack 1001: 2 element(s), 1 not readable as a normal CP (ReadableControlParameterInferno=1, OrphanedControlParameterInferno=1):
  [1] orphaned: 1001-00000000-0000-4000-8000-00000000c002 "Example Orphaned Passthrough" missing output PIDs [500015]
```

Use `2>/dev/null` to silence it, or keep stderr separate when redirecting stdout to a file.

> **Same-Lumberjack Constraint:** All inputs and outputs of a control parameter must belong to the same Lumberjack. Use **lj-profile** to find the Lumberjack ID for a given location ID.

> **Output Exclusivity:** Only one control parameter can write to a given output parameter ID. Each target parameter ID in `ScalarOutput` or `RecordOutput` is exclusive to that control parameter. To assign an output to a different CP, the existing assignment must be removed first.

## Error Handling

- If the access token is invalid or expired, each request retries up to 3 times before failing
- Lumberjack IDs must be integers
- Network errors and non-200 HTTP responses are reported to stderr
- Invalid JSON responses are reported with the raw response body
- Orphaned, prohibited, failed and unknown-tag elements are reported on stderr and are not errors (exit 0)
