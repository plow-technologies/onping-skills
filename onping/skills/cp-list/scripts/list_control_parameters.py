# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List OnPing control parameters by Lumberjack ID - takes ACCESS_TOKEN and one or more Lumberjack IDs."""

import argparse
import json
import sys
from typing import Any

import requests


def fetch_control_parameters(access_token: str, lumberjack_id: int) -> Any:
    url = "https://onping.plowtech.net/cpInferno/list"
    headers = {
        "Accept": "application/json",
        "Content-Type": "text/plain;charset=UTF-8",
        "Authorization": f"Bearer {access_token}",
    }
    tries = 0

    while True:
        try:
            resp = requests.post(
                url,
                data=str(lumberjack_id),
                headers=headers,
                allow_redirects=False,
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"Request error for Lumberjack {lumberjack_id}: {e}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(
                    "Authentication failed too many times "
                    f"for Lumberjack {lumberjack_id} (status {resp.status_code}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(
                f"HTTP {resp.status_code} for Lumberjack {lumberjack_id}:\n{resp.text}",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            return resp.json()
        except ValueError as e:
            print(
                f"Failed to decode JSON response for Lumberjack {lumberjack_id}: {e}",
                file=sys.stderr,
            )
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List OnPing control parameters for one or more Lumberjack IDs."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument(
        "lumberjack_ids",
        nargs="+",
        type=int,
        help="One or more numeric Lumberjack IDs",
    )
    args = parser.parse_args()

    if len(args.lumberjack_ids) == 1:
        data = fetch_control_parameters(args.access_token, args.lumberjack_ids[0])
        print(json.dumps(data, indent=2))
        return

    results = {}
    for lumberjack_id in args.lumberjack_ids:
        results[str(lumberjack_id)] = fetch_control_parameters(
            args.access_token, lumberjack_id
        )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
