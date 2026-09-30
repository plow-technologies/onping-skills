# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List available backup files for a lumberjack - takes IP, lumberjack ID, and optional port."""

import argparse
import json
import sys

import requests


def fetch_backups(ip: str, lj_id: str, port: int) -> list:
    url = f"http://{ip}:{port}/lj/restore/backup/{lj_id}"
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
                    f"Request failed too many times for lumberjack {lj_id} "
                    f"(status {resp.status_code}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(
                f"HTTP {resp.status_code} for lumberjack {lj_id}:\n{resp.text}",
                file=sys.stderr,
            )
            sys.exit(1)

        lines = resp.text.strip().split("\n")
        return [line for line in lines if line]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List available backup files for a lumberjack."
    )
    parser.add_argument("ip", help="IP address of the lumberjack device")
    parser.add_argument("lj_id", help="Lumberjack ID (e.g. '1001' or '1111')")
    parser.add_argument(
        "--port", type=int, default=13201, help="Port of the restore server (default: 13201)"
    )
    args = parser.parse_args()

    data = fetch_backups(args.ip, args.lj_id, args.port)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
