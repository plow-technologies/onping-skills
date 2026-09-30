---
name: vp-script-fetch
description: Fetch the Inferno script code for a virtual parameter by script ID. Use when you need to read or analyze the actual VP script source code.
allowed-tools: Bash(uv run *)
---

# VP Script Fetch

Fetch the actual Inferno script code for a virtual parameter by its script ID.

## Related Skills

- **vp-scripts** — List all VP scripts to find script IDs
- **vp-show** — Show VP configuration and metadata for context
- **inferno-lookup** — Reference documentation for understanding the Inferno script syntax

## Typical Workflow

```
1. Login (onping-login) → access token
2. List all VP scripts (vp-scripts) → find script of interest
3. Show VP details (vp-show) → see configuration, inputs, script reference
4. Fetch script code (vp-script-fetch) → read the actual Inferno code
5. Use inferno-lookup to understand the script syntax
```

## Usage

Requires a valid access token and a script ID (base64-encoded string). Run login and fetch in a single pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/vp-script-fetch/scripts/fetch_script.py "$ACCESS_TOKEN" "SCRIPT_ID"
```

Replace `SCRIPT_ID` with the base64-encoded script ID (e.g. `"JJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJ="`).

## Output

On success, outputs a JSON object containing the Inferno script content to stdout.

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
- Invalid JSON responses are reported with the raw response body
