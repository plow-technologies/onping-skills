---
name: vp-show
description: Show configuration details for a virtual parameter by ID, including name, inputs, and script reference. Use when you need VP metadata before fetching the script code.
allowed-tools: Bash(uv run *)
---

# VP Show

Show the configuration and metadata for a specific virtual parameter in OnPing, including its name, inputs, and script reference.

## Related Skills

- **vp-scripts** — List all VP scripts to find VP IDs
- **vp-script-fetch** — Fetch the actual Inferno script code referenced by this VP
- **inferno-lookup** — Reference documentation for the Inferno scripting language

## Typical Workflow

```
1. Login (onping-login) → access token
2. List all VP scripts (vp-scripts) → find script of interest
3. Show VP details (vp-show) → see configuration, inputs, script reference
4. Fetch script code (vp-script-fetch) → read the actual Inferno code
5. Use inferno-lookup to understand the script syntax
```

## Usage

Requires a valid access token and a numeric VP ID. Run login and show in a single pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/vp-show/scripts/show_vp.py "$ACCESS_TOKEN" VP_ID
```

Replace `VP_ID` with the numeric virtual parameter ID (e.g. `500111`).

## Output

On success, outputs a JSON object with the VP configuration to stdout, including name, inputs, script reference, and other metadata.

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
- Invalid JSON responses are reported with the raw response body
