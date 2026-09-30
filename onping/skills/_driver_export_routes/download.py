# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Shared HTTP helper for OnPing driver tag-export skills.

`download_export(token, url, output_path)` issues an authenticated GET against
an OnPing export route, follows redirects (some routes 302 to S3), and streams
the response body to `output_path`. Returns the resolved absolute path on
success; exits non-zero with a stderr diagnostic on failure.

Two fallthrough cases are detected before writing to disk:
  - **Auth-redirect**: the redirect chain ends at a URL containing `/auth/login`
    or ending with `/auth`. Caused by an expiring bearer token; OnPing returns
    `303 → /auth/login` and a 200 + HTML login page follows.
  - **HTML body**: a 2xx response whose body starts with `<!doc` or `<html`
    after `lstrip()`. Catches the auth-redirect case as a fallback and any
    other route-error pages that return HTML in a 2xx envelope.

Both checks SHALL run before opening the output file. No partial file is
written on either failure path.
"""

from __future__ import annotations

import os
import sys

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 60


def download_export(token: str, url: str, output_path: str) -> str:
    """Download an XLSX export to `output_path`. Returns absolute path on success."""
    headers = {"Authorization": f"Bearer {token}"}
    full_url = url if url.startswith("http") else BASE_URL + url

    try:
        with requests.get(
            full_url,
            headers=headers,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
            stream=True,
        ) as resp:
            if not (200 <= resp.status_code < 300):
                print(
                    f"HTTP {resp.status_code} from {full_url}\n{resp.text[:500]}",
                    file=sys.stderr,
                )
                sys.exit(1)

            if resp.history and (
                "/auth/login" in resp.url
                or resp.url.rstrip("/").endswith("/auth")
            ):
                print(
                    f"Access token redirected to auth — token may be expired (final URL: {resp.url})",
                    file=sys.stderr,
                )
                sys.exit(1)

            chunks = resp.iter_content(chunk_size=64 * 1024)
            first = next(chunks, b"")
            if first.lstrip()[:5].lower() in (b"<!doc", b"<html"):
                print(
                    "Expected XLSX body but received HTML — access token may be expired or route returned an error page",
                    file=sys.stderr,
                )
                sys.exit(1)

            try:
                with open(output_path, "wb") as f:
                    if first:
                        f.write(first)
                    for chunk in chunks:
                        if chunk:
                            f.write(chunk)
            except OSError as e:
                print(f"Write error: {e}", file=sys.stderr)
                _cleanup(output_path)
                sys.exit(1)
    except requests.RequestException as e:
        print(f"Request error: {e}", file=sys.stderr)
        _cleanup(output_path)
        sys.exit(1)

    return os.path.abspath(output_path)


def _cleanup(path: str) -> None:
    try:
        if os.path.exists(path) and os.path.getsize(path) == 0:
            os.remove(path)
    except OSError:
        pass
