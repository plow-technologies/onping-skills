# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch a VP script by ID from OnPing - takes ACCESS_TOKEN and SCRIPT_ID as CLI args."""

import json
import sys

import requests


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: fetch_script.py ACCESS_TOKEN SCRIPT_ID", file=sys.stderr)
        sys.exit(1)

    access_token = sys.argv[1]
    script_id = sys.argv[2]

    url = f"https://onping.plowtech.net/script/id/{script_id}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    tries = 0

    while True:
        try:
            resp = requests.get(
                url,
                headers=headers,
                allow_redirects=False,
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"Request error: {e}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(
                    f"Authentication failed too many times (status {resp.status_code}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        try:
            data = resp.json()
        except ValueError as e:
            print(f"Failed to decode JSON response: {e}", file=sys.stderr)
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        print(json.dumps(data, indent=2))
        return


if __name__ == "__main__":
    main()
