---
name: onping-sites
description: Fetch OnPing sites for a company. Use when the user asks about OnPing sites, or needs to list sites for a company. This is the first step in the Company → Sites → Locations hierarchy.
allowed-tools: Bash(uv run *)
---

# OnPing Sites

Fetch the list of sites for a given company from OnPing.

## Tag Hierarchy

OnPing tags are organized: **Company → Sites → Locations**. This skill handles
the first hop — given a company ID, it returns that company's sites. To go
deeper, pass site `value.refId` values to onping-locations.

## Usage

Requires a valid access token (from onping-login) and a company ID. Run login
and fetch in a single pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-sites/scripts/fetch_sites.py "$ACCESS_TOKEN" COMPANY_ID
```

Replace `COMPANY_ID` with the numeric company ID.

## Output

On success, outputs a JSON array of `{key, value}` site objects to stdout.
Key fields in each `value`:

- `name` — site name (e.g. "Water Treatment Plant")
- `refId` — the site ID, used as input to onping-locations
- `cid` — the parent company ID
- `pull` — whether the site is active
- `delete` — soft-delete flag

Example (abbreviated):

```json
[
  {
    "key": "o000000000000000000000031",
    "value": {
      "cid": 100,
      "delete": 0,
      "name": "Water Treatment Plant",
      "pull": 1,
      "refId": 3001
    }
  }
]
```

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
- Invalid JSON responses are reported with the raw response body
