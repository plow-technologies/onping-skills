---
name: onping-locations
description: Fetch OnPing locations for given sites. Use after fetching sites (onping-sites) to list the locations belonging to those sites using their refId values.
allowed-tools: Bash(uv run *)
---

# OnPing Locations

Fetch the locations belonging to one or more OnPing sites.

## Tag Hierarchy

OnPing tags are stored in a hierarchy: **Company → Sites → Locations**. To find
locations you must walk down this chain:

1. Start with a **company ID** (e.g. `100`)
2. Fetch **sites** for that company using onping-sites — each site is a `{key, value}` object where `value.refId` is the site ID
3. Pass those `refId` values to this skill to get the **locations** under those sites

## Typical Workflow

1. Login to get an access token (onping-login)
2. Fetch sites for a company (onping-sites) with a known company ID (e.g. `100`)
3. Extract `value.refId` from the returned site objects — these are site IDs
4. Pass those site IDs to this skill to get the locations under those sites

## Usage

Requires a valid access token and one or more numeric site IDs (the `refId` from onping-sites):

```bash
uv run ~/.claude/skills/onping-locations/scripts/fetch_locations.py "$ACCESS_TOKEN" 3001
```

Combined login + fetch pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-locations/scripts/fetch_locations.py "$ACCESS_TOKEN" SITE_ID1 SITE_ID2
```

Replace `SITE_ID1`, `SITE_ID2`, etc. with numeric site IDs (`value.refId` from onping-sites output).

Full chain example — login, fetch sites for company 100, then fetch locations for site 3001:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-locations/scripts/fetch_locations.py "$ACCESS_TOKEN" 3001
```

## Output

On success, outputs a JSON array of `{key, value}` location objects to stdout.
Key fields in each `value`:

- `name` — location name (e.g. "New Plant Main PLC")
- `refId` — the location ID
- `site` — the parent site ID
- `company` — the parent company ID
- `url` — device IP address
- `slaveId` — Modbus slave ID
- `delete` — soft-delete flag

Example (abbreviated):

```json
[
  {
    "key": "o0000000000000000000000b9",
    "value": {
      "company": 100,
      "delete": 0,
      "name": "New Plant Main PLC",
      "refId": 20004,
      "site": 3001,
      "slaveId": 0,
      "url": "192.0.2.13"
    }
  }
]
```

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
- Site IDs must be integers; non-numeric values are rejected immediately
