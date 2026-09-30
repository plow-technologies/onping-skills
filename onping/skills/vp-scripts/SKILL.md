---
name: vp-scripts
description: List all virtual parameter scripts in OnPing. Use as the discovery entry point to browse VP scripts before drilling into individual VPs or fetching script code.
allowed-tools: Bash(uv run *)
---

# VP Scripts

List all virtual parameter scripts registered in OnPing. This is the discovery/browsing entry point for working with VP scripts.

## Related Skills

- **vp-show** — Show configuration details for a specific virtual parameter
- **vp-script-fetch** — Fetch the actual Inferno script code by script ID
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

Requires a valid access token from onping-login. Run login and list in a single pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/vp-scripts/scripts/list_scripts.py "$ACCESS_TOKEN"
```

## Output

On success, outputs a JSON array of all virtual parameter script objects to stdout.

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
- Invalid JSON responses are reported with the raw response body
