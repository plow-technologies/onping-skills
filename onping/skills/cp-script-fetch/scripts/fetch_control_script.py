# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch a control parameter script by ID from OnPing - takes ACCESS_TOKEN and SCRIPT_ID.

The script id is a base64-encoded SHA-256 digest and commonly ends in `=`, so it
is percent-encoded before it goes in the URL path. Set ONPING_BASE_URL to target
a non-production environment.

For an ML inference script's model selections, use `ml-script-models` instead:
this route returns the full VCMeta, but extracting and enriching the model map
belongs there. Note that GET /script/id/ mints an LSP session UUID server-side,
so `POST /scripts/by-hash` is preferable for bulk or programmatic reads.
"""

import json
import os
import sys
from urllib.parse import quote

import requests

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net").rstrip("/")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: fetch_control_script.py ACCESS_TOKEN SCRIPT_ID", file=sys.stderr)
        sys.exit(1)

    access_token = sys.argv[1]
    script_id = sys.argv[2]

    # Script hashes are base64 and commonly end in '='. Without encoding, the
    # trailing '=' (and any '+') is mis-routed.
    url = f"{BASE_URL}/script/id/{quote(script_id, safe='')}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}

    try:
        resp = requests.get(url, headers=headers, allow_redirects=False, timeout=15)
    except requests.RequestException as e:
        print(f"Request error: {e}", file=sys.stderr)
        sys.exit(1)

    body = resp.text.strip()

    # An auth failure is not transient: report it once instead of re-issuing the
    # identical unauthenticated request.
    location = resp.headers.get("Location", "")
    looks_like_login = "/auth/login" in location or "<html" in body[:200].lower()
    if 300 <= resp.status_code < 400 or resp.status_code == 401 or looks_like_login:
        print(
            f"Authentication failed (HTTP {resp.status_code}). "
            "Get a fresh token with the onping-login skill.",
            file=sys.stderr,
        )
        if location:
            print(f"Redirect location: {location}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 404:
        # A mis-encoded hash and an absent script are otherwise identical.
        print(f"No such script: {script_id}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        print(f"HTTP {resp.status_code}:\n{body or '<empty response>'}", file=sys.stderr)
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError as e:
        print(f"Failed to decode JSON response: {e}", file=sys.stderr)
        print(f"Raw response:\n{resp.text}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
