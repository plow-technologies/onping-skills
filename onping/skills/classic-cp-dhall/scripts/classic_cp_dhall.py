# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Import, export, and modify classic OnPing control parameters in Dhall format."""

import argparse
import json
import re
import sys
from pathlib import Path

import requests

BASE_URL = "https://onping.plowtech.net"


def disable_all(input_path: str, output_path: str) -> None:
    """Read a Dhall CP file and write a copy with all enabled = True changed to False."""
    text = Path(input_path).read_text()
    updated = re.sub(r",\s*enabled\s*=\s*True", ", enabled = False", text)
    Path(output_path).write_text(updated)

    # Count entries
    total = len(re.findall(r",\s*enabled\s*=\s*(True|False)", updated))
    disabled = len(re.findall(r",\s*enabled\s*=\s*False", updated))
    print(json.dumps({"total": total, "disabled": disabled, "output": output_path}))


def import_dhall(access_token: str, input_path: str) -> None:
    """POST a Dhall CP file to /cp/import."""
    dhall_text = Path(input_path).read_text()
    url = f"{BASE_URL}/cp/import"
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
                data=dhall_text.encode("utf-8"),
                headers=headers,
                allow_redirects=False,
                timeout=30,
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
            print(json.dumps(data, indent=2))
            return
        except ValueError as e:
            print(f"Failed to decode JSON response: {e}", file=sys.stderr)
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)


def export_dhall(access_token: str, cpids: list[int], output_path: str | None) -> None:
    """POST CPID list to /cp/export and save Dhall response."""
    url = f"{BASE_URL}/cp/export"
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    tries = 0

    while True:
        try:
            resp = requests.post(
                url,
                json=cpids,
                headers=headers,
                allow_redirects=False,
                timeout=30,
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

        if output_path:
            Path(output_path).write_text(resp.text)
            print(f"Exported {len(cpids)} CPs to {output_path}", file=sys.stderr)
        print(resp.text)
        return


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import, export, and modify classic OnPing control parameters in Dhall format."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # disable-all
    p_disable = subparsers.add_parser(
        "disable-all",
        help="Create a copy of a Dhall CP file with all CPs disabled",
    )
    p_disable.add_argument("--input", required=True, help="Input Dhall file")
    p_disable.add_argument("--output", required=True, help="Output Dhall file")

    # import
    p_import = subparsers.add_parser(
        "import", help="Import a Dhall CP file into OnPing"
    )
    p_import.add_argument("access_token", help="OnPing OAuth2 access token")
    p_import.add_argument("--input", required=True, help="Dhall file to import")

    # export
    p_export = subparsers.add_parser(
        "export", help="Export classic CPs from OnPing by CPID"
    )
    p_export.add_argument("access_token", help="OnPing OAuth2 access token")
    p_export.add_argument(
        "--cpids", nargs="+", type=int, required=True, help="CPID(s) to export"
    )
    p_export.add_argument("--output", help="Output file path (also prints to stdout)")

    args = parser.parse_args()

    if args.command == "disable-all":
        disable_all(args.input, args.output)
    elif args.command == "import":
        import_dhall(args.access_token, args.input)
    elif args.command == "export":
        export_dhall(args.access_token, args.cpids, args.output)


if __name__ == "__main__":
    main()
