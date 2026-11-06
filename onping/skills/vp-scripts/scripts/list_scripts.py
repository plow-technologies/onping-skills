# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List all virtual parameter scripts from OnPing - (token from $ONPING_ACCESS_TOKEN or --token-stdin)."""

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _token_input import shapes, token_source  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args = token_source.parse(p, None)
    access_token = args.access_token

    url = "https://onping.plowtech.net/scripts"
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
