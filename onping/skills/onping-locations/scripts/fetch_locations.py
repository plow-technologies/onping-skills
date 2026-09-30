# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch OnPing locations for given sites - takes ACCESS_TOKEN and one or more site IDs as CLI args."""

import json
import sys

import requests


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: fetch_locations.py ACCESS_TOKEN SITE_ID1 [SITE_ID2 ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    access_token = sys.argv[1]
    try:
        site_ids = [int(arg) for arg in sys.argv[2:]]
    except ValueError as e:
        print(f"Site IDs must be integers: {e}", file=sys.stderr)
        sys.exit(1)

    url = "https://onping.plowtech.net/json/listers/locationLister"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    body = {
        "getLocationLookupId": None,
        "getCompanyLookupList": [],
        "getSiteLookupList": site_ids,
    }
    tries = 0

    while True:
        try:
            resp = requests.post(
                url,
                json=body,
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

        if not isinstance(data, list):
            print(
                f"Unexpected decoded result (expected a list): {type(data).__name__}",
                file=sys.stderr,
            )
            sys.exit(1)

        print(json.dumps(data, indent=2))
        return


if __name__ == "__main__":
    main()
