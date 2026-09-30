# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List lumberjack backup folders on a device - takes IP and optional port."""

import argparse
import json
import sys

import requests


def fetch_lumberjacks(ip: str, port: int) -> list:
    url = f"http://{ip}:{port}/lj/restore/list"
    tries = 0

    while True:
        try:
            resp = requests.get(url, allow_redirects=False, timeout=15)
        except requests.RequestException as e:
            print(f"Request error ({url}): {e}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(
                    f"Request failed too many times (status {resp.status_code}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        try:
            return resp.json()
        except ValueError as e:
            print(f"Failed to decode JSON response: {e}", file=sys.stderr)
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List lumberjack backup folders on a device."
    )
    parser.add_argument("ip", help="IP address of the lumberjack device")
    parser.add_argument(
        "--port", type=int, default=13201, help="Port of the restore server (default: 13201)"
    )
    args = parser.parse_args()

    data = fetch_lumberjacks(args.ip, args.port)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
