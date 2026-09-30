---
name: onping-parameters
description: Fetch OnPing parameters for given locations. Use after fetching locations (onping-locations) to list the parameters belonging to those locations using their refId values.
allowed-tools: Bash(uv run *)
---

# OnPing Parameters

Fetch the parameters belonging to one or more OnPing locations.

## Tag Hierarchy

OnPing tags are stored in a hierarchy: **Company → Sites → Locations → Parameters**. To find
parameters you must walk down this chain:

1. Start with a **company ID** (e.g. `100`)
2. Fetch **sites** for that company using onping-sites — each site is a `{key, value}` object where `value.refId` is the site ID
3. Fetch **locations** for those sites using onping-locations — each location has a `value.refId` that is the location ID
4. Pass those location `refId` values to this skill to get the **parameters** under those locations

## Typical Workflow

1. Login to get an access token (onping-login)
2. Fetch sites for a company (onping-sites) with a known company ID (e.g. `100`)
3. Fetch locations for those sites (onping-locations) using site `refId` values
4. Extract `value.refId` from the returned location objects — these are location IDs
5. Pass those location IDs to this skill to get the parameters under those locations

## Usage

Requires a valid access token and one or more numeric location IDs (the `refId` from onping-locations):

```bash
uv run ~/.claude/skills/onping-parameters/scripts/fetch_parameters.py "$ACCESS_TOKEN" 20003
```

Combined login + fetch pipeline:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-parameters/scripts/fetch_parameters.py "$ACCESS_TOKEN" LOCATION_ID1 LOCATION_ID2
```

Replace `LOCATION_ID1`, `LOCATION_ID2`, etc. with numeric location IDs (`value.refId` from onping-locations output).

Full chain example — login, fetch sites for company 100, fetch locations for site 3001, then fetch parameters for location 20003:

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-parameters/scripts/fetch_parameters.py "$ACCESS_TOKEN" 20003
```

### Virtual Parameter Options

- `--vp` — include virtual parameters in the response
- `--vp-calc` — include virtual parameters with calculated results
- `--exclude-pid` — exclude PID parameters

```bash
uv run ~/.claude/skills/onping-parameters/scripts/fetch_parameters.py "$ACCESS_TOKEN" 20003 --vp --vp-calc
```

## Output

On success, outputs raw JSON to stdout. The response shape depends on the OnPing API version and the parameters present at the given locations.

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
- Location IDs must be integers; non-numeric values are rejected immediately
