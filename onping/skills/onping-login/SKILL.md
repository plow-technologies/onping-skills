---
name: onping-login
description: Authenticate with OnPing via OAuth2 and get an access token. Use when needing to access OnPing APIs or when the user mentions OnPing login, authentication, or session.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Login

Get an OAuth2 access token for OnPing API access.

## Usage

Run the login script — it reads the refresh token from `ONPING_REFRESH_TOKEN` env var, a plaintext `refresh_token` file, or a GPG-encrypted `refresh_token.gpg` file. Prefer running it from a project root (the script will pick up the project's local token if present):

```bash
uv run ~/.claude/skills/onping-login/scripts/login.py
# or, from a repo root that ships its own login helper:
uv run tools/onping/login.py
```

The bundled path `~/.claude/skills/onping-login/scripts/login.py`, the
equivalent path in a source checkout, and any repo-local
`tools/onping/login.py` are all supported entry points and share the same
token-resolution order.

## Token Sources (checked in order)

1. `ONPING_REFRESH_TOKEN` environment variable
2. Plaintext `refresh_token` next to the project's `pyproject.toml` walked from `cwd`
3. Plaintext `refresh_token` in the source checkout (canonical user location)
4. Plaintext `refresh_token` next to the script's SKILLS_ROOT (legacy fallback)
5. GPG-encrypted `refresh_token.gpg` in the same order as (2)–(4)

Rotated refresh tokens are persisted back to the plaintext file they came
from; GPG-encrypted files are never overwritten in place.

## Output

On success, outputs an OAuth2 access token (JWT) that can be used in subsequent
OnPing API calls via the `Authorization: Bearer` header.

## WARNING

- **Never** call the token endpoint directly (curl, Python requests, etc.) — only use the login script.
- If the login script fails, **do not** attempt the exchange by other means — stop and ask the user to provide a new refresh token.

## Error Handling

- If no refresh token source is found, the script reports which paths were checked
- If OAuth2 metadata discovery fails, the script outputs the error to stderr
- If the token exchange fails, the HTTP error is reported to stderr
