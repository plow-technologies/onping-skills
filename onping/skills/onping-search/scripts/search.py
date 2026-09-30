# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Search OnPing - takes ACCESS_TOKEN, QUERY, and optional pagination args."""

import argparse
import json
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Search OnPing.")
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument("query", help="Search query string")
    parser.add_argument(
        "--size", type=int, default=10, help="Number of results to return (default: 10)"
    )
    parser.add_argument(
        "--from", dest="from_offset", type=int, default=0, help="Result offset for pagination (default: 0)"
    )
    args = parser.parse_args()

    url = "https://onping.plowtech.net/search"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {args.access_token}",
    }
    params = {
        "query": args.query,
        "size": args.size,
        "from": args.from_offset,
    }
    tries = 0

    while True:
        try:
            resp = requests.get(
                url,
                params=params,
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
