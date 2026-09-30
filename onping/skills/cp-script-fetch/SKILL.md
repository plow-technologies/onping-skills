---
name: cp-script-fetch
description: Fetch Inferno script source and metadata for a control parameter script ID. Use after cp-list to inspect control script behavior.
allowed-tools: Bash(uv run *)
---

# Control Script Fetch

Fetch the Inferno script payload for a control parameter script ID.

## Related Skills

- **cp-list** — List control parameters and discover script IDs
- **lj-profile** — Look up the Lumberjack ID for a location ID
- **inferno-lookup** — Reference Inferno language documentation
- **onping-login** — Authenticate and get an access token
- **ml-script-models** — For an ML inference script's **model selections**. This
  route returns the full `VCMeta`, whose `author.scriptTypes[]` carries the
  `MLInferenceScript` model map, but extracting and enriching it belongs there.

## Typical Workflow

```
1. Login (onping-login) -> access token
2. List control parameters by Lumberjack ID (cp-list) — note output parameter exclusivity
3. Copy cpData.script from the control parameter of interest
4. Fetch script source and history metadata (cp-script-fetch)
5. Use inferno-lookup to interpret Inferno syntax and modules
```

## Usage

Requires a valid access token and a base64-encoded script ID:

```bash
uv run ~/.claude/skills/cp-script-fetch/scripts/fetch_control_script.py "$ACCESS_TOKEN" "SCRIPT_ID"
```

Run login and fetch in a single pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/cp-script-fetch/scripts/fetch_control_script.py "$ACCESS_TOKEN" "SCRIPT_ID"
```

## Output

On success, outputs the raw JSON response from `/script/id/{SCRIPT_ID}` to stdout.

## Error Handling

- An expired or invalid token is reported **once**, pointing at `onping-login`. The
  request is not retried: an auth failure is not transient, and the earlier
  retry loop made it read like one.
- A `404` is reported as "no such script", naming the hash queried.
- Other non-200 responses are reported with the status **and** the response body.
- Network errors and invalid JSON are reported with the raw response body.

## Notes

- Set `ONPING_BASE_URL` to target a non-production environment.
- The script hash is percent-encoded before it goes in the path. Hashes are
  base64 and end in `=`. Measured 2026-08-04, the route tolerates a raw trailing
  `=`, so the encoding is hardening against a hash containing `+` or `/`, which
  `requests` would otherwise transmit unescaped.
- `GET /script/id/` mints an LSP session UUID server-side and writes the
  server's session map, because the route exists to open the script editor. For
  bulk or programmatic metadata reads, `POST /scripts/by-hash` is preferable —
  it batches and causes no session churn. See
  `_inferno_ml_routes.scripts_by_hash`.
