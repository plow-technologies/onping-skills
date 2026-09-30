# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Exchange a stored refresh token for an OAuth2 access token."""

import os
import subprocess
import sys
from pathlib import Path

import requests

BASE_URL = "https://onping.plowtech.net"

# SKILLS_ROOT is what parent.parent.parent.parent walks to when this script
# lives under {root}/skills/onping-login/scripts/login.py. Historically this
# was the ONLY source. Left in the search list for backwards compatibility,
# but it moves LAST because the nix-bundled copy at ~/.claude/skills/... walks
# up to ~/.claude — where a stale refresh_token.gpg can silently poison the
# lookup (bug observed 2026-07-28: nix-bundled path served a revoked token
# from ~/.claude/refresh_token.gpg dated 2026-07-06 while the source path
# served a fresh token from the source checkout).
SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _project_root_from_cwd() -> Path | None:
    """Walk up from cwd looking for pyproject.toml. Returns None if not found."""
    try:
        current = Path.cwd().resolve()
    except (OSError, RuntimeError):
        return None
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return None


def _candidate_roots() -> list[Path]:
    """Ordered list of directories to search for refresh_token / refresh_token.gpg.

    Ordering rationale:
      1. Project root walked from cwd — a subagent running inside a repo picks
         up that repo's token first (the token freshness is usually tracked
         alongside the code).
      2. Canonical user skills tree — the maintained token location on this
         machine. Always fresh when the user rotates.
      3. SKILLS_ROOT — legacy behavior. Matches original semantics for anyone
         invoking via the source checkout
         path, but comes AFTER the canonical location so the nix-bundled
         bundled `onping-login` path never falls back to a stale
         `~/.claude/refresh_token[.gpg]`.
    """
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            resolved = p.resolve()
        except (OSError, RuntimeError):
            return
        if resolved in seen:
            return
        seen.add(resolved)
        roots.append(resolved)

    add(_project_root_from_cwd())
    add(Path.home() / "skills" / "onping")
    add(SKILLS_ROOT)
    return roots


def _try_plaintext(root: Path) -> str | None:
    p = root / "refresh_token"
    if not p.exists():
        return None
    token = p.read_text().strip()
    return token or None


def _try_gpg(root: Path) -> str | None:
    p = root / "refresh_token.gpg"
    if not p.exists():
        return None
    try:
        result = subprocess.run(
            ["gpg", "-d", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        print("gpg not found; cannot decrypt refresh_token.gpg", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"GPG decryption timed out on {p}", file=sys.stderr)
        return None
    if result.returncode == 0:
        token = result.stdout.strip()
        return token or None
    print(f"GPG decryption failed for {p}: {result.stderr}", file=sys.stderr)
    return None


def read_refresh_token() -> tuple[str, Path | None]:
    """Read refresh token from env var or the first candidate root that has one.

    Returns (token, plaintext_path_or_None). The plaintext path is where a
    rotated refresh token should be persisted back; it is None when the token
    came from the env var (no file to write) or from a GPG-only source (the
    caller must not overwrite a GPG-encrypted file with plaintext).
    """
    # 1. Environment variable
    token = os.environ.get("ONPING_REFRESH_TOKEN", "").strip()
    if token:
        return token, None

    roots = _candidate_roots()

    # 2. Plaintext files, in preference order across roots
    for root in roots:
        token = _try_plaintext(root)
        if token:
            return token, root / "refresh_token"

    # 3. GPG-encrypted files, in the same preference order
    for root in roots:
        token = _try_gpg(root)
        if token:
            return token, None  # do not clobber the encrypted file

    checked = "\n".join(
        f"  - {root}/refresh_token(.gpg)" for root in roots
    )
    print(
        "No refresh token found. Set ONPING_REFRESH_TOKEN, or place a "
        "refresh_token / refresh_token.gpg file in one of:\n" + checked,
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    refresh_token, persist_path = read_refresh_token()

    # Discover token endpoint
    try:
        metadata_resp = requests.get(
            f"{BASE_URL}/.well-known/oauth-authorization-server", timeout=10
        )
        metadata_resp.raise_for_status()
        token_endpoint = metadata_resp.json()["token_endpoint"]
    except requests.RequestException as e:
        print(f"Failed to fetch OAuth2 metadata: {e}", file=sys.stderr)
        sys.exit(1)
    except (KeyError, ValueError) as e:
        print(f"Invalid OAuth2 metadata response: {e}", file=sys.stderr)
        sys.exit(1)

    # Exchange refresh token for access token
    try:
        token_resp = requests.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except requests.RequestException as e:
        print(f"Token exchange failed: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Invalid token response: {e}", file=sys.stderr)
        sys.exit(1)

    access_token = token_data.get("access_token")
    if not access_token:
        print("No access_token in token response", file=sys.stderr)
        sys.exit(1)

    # If a rotated refresh token was returned, persist it back to the same
    # plaintext file we read from (only when we read from a plaintext file —
    # we never overwrite a GPG-encrypted file, and env-var sources have no
    # persistent home).
    new_refresh_token = token_data.get("refresh_token")
    if new_refresh_token and new_refresh_token != refresh_token and persist_path is not None:
        try:
            persist_path.write_text(new_refresh_token)
        except OSError as e:
            print(f"Warning: failed to save rotated refresh token: {e}", file=sys.stderr)

    print(access_token)


if __name__ == "__main__":
    main()
