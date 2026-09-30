---
name: onping-search
description: Search OnPing for sites, locations, parameters, or any other entities by keyword. Useful for finding resources when you don't know the exact IDs.
allowed-tools: Bash(uv run *)
---

# OnPing Search

Search across all OnPing entities (sites, locations, parameters, etc.) by keyword.

## Usage

Requires a valid access token (from onping-login) and a search query. The server infers the user from the Bearer token.

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-search/scripts/search.py "$ACCESS_TOKEN" "North Field 12"
```

### Pagination

- `--size N` — Number of results to return (default: 10)
- `--from N` — Result offset for pagination (default: 0)

```bash
uv run ~/.claude/skills/onping-search/scripts/search.py "$ACCESS_TOKEN" "North Field" --size 20 --from 10
```

## Output

On success, outputs raw JSON search results to stdout.

## Error Handling

- If the access token is invalid or expired, the script retries up to 3 times before failing
- Network errors and non-200 HTTP responses are reported to stderr
