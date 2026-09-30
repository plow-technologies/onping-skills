# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Restore a lumberjack from a backup - takes IP, folder, filename, and optional port."""

import argparse
import sys

import requests


def run_restore(ip: str, folder: str, filename: str, port: int) -> str:
    url = f"http://{ip}:{port}/lj/restore/{folder}/{filename}"
    tries = 0

    while True:
        try:
            resp = requests.post(url, allow_redirects=False, timeout=120)
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

        return resp.text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore a lumberjack from a backup file."
    )
    parser.add_argument("ip", help="IP address of the lumberjack device")
    parser.add_argument("folder", help="Lumberjack folder name (e.g. 'lumberJack-1002/')")
    parser.add_argument("filename", help="Backup filename (e.g. 'backupStates-25-07-16.tar.gz')")
    parser.add_argument(
        "--port", type=int, default=13201, help="Port of the restore server (default: 13201)"
    )
    args = parser.parse_args()

    result = run_restore(args.ip, args.folder, args.filename, args.port)
    print(result)


if __name__ == "__main__":
    main()
