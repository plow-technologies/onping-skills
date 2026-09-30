---
name: lj-profile
description: Look up Lumberjack profiles by OnPing location ID. Bridges the gap between location IDs and Lumberjack IDs needed by cp-list.
allowed-tools: Bash(uv run *)
---

# Lumberjack Profile Lookup

Find the Lumberjack profile associated with an OnPing location by matching the location's IP address against Lumberjack profile fields.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-locations** — Fetch locations for a site (to find location IDs)
- **cp-list** — List control parameters by Lumberjack ID (use the ID from this skill's output)

## Typical Workflow

```
1. Login (onping-login) -> access token
2. Look up Lumberjack profile by location ID (lj-profile)
3. Extract the Lumberjack ID from the matched profile
4. List control parameters (cp-list) using that Lumberjack ID
```

## Usage

Requires a valid access token and one or more numeric location IDs:

```bash
uv run ~/.claude/skills/lj-profile/scripts/lj_profile.py "$ACCESS_TOKEN" 20004
```

Run login and lookup in a single pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/lj-profile/scripts/lj_profile.py "$ACCESS_TOKEN" 20004
```

Multiple location IDs:

```bash
uv run ~/.claude/skills/lj-profile/scripts/lj_profile.py "$ACCESS_TOKEN" 20004 20005
```

## Output

- **Single location ID:** The matched Lumberjack profile JSON object, or `null` if no match
- **Multiple location IDs:** JSON object keyed by location ID, each value the matched profile or `null`

Key fields in the profile object:

- `lumberjackId` — The Lumberjack ID (integer, use this with `cp-list`)
- `lumberjackName` — Human-readable name
- `lumberjackUrl` — IP address (used for matching against the location's `url`)
- `lumberjackGroup` — Group identifier
- `lumberjackTimezone` — Timezone string
- `lumberjackArch` — Architecture (e.g. `"aarch64"`)
- `lumberjackCapabilities` — Capabilities list
- `lumberjackInternetSource` — Internet source configuration

Example (abbreviated):

```json
{
  "lumberjackId": 1001,
  "lumberjackName": "Example Company - Site A TotalFlows - LJ 1001",
  "lumberjackUrl": "192.0.2.12",
  "lumberjackArch": "aarch64",
  "lumberjackTimezone": "America/Chicago",
  "lumberjackGroup": "o000000000000000000000001",
  "lumberjackCapabilities": [],
  "lumberjackInternetSource": []
}
```

## Error Handling

- If the access token is invalid or expired, each request retries up to 3 times before failing
- Location IDs must be integers
- Locations not found or missing a `url` field produce a warning on stderr and `null` in output
- Unmatched IPs produce a warning on stderr and `null` in output
- Network errors and non-200 HTTP responses are reported to stderr

## Notes

- The `getLocationLookupId` field in the locationLister request is used to fetch individual locations. If this doesn't work for a given location, fall back to fetching all locations for the site and filtering locally.
- Profile matching uses the `lumberjackUrl` field. The raw API returns profiles as `[lumberjack_id, profile_object]` pairs; the script flattens this into a single object with `lumberjackId` added.
