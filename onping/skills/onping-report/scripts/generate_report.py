# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Generate an OnPing CSV report via the /tachdb/report endpoint (Bearer auth).

Prints the download URL to stdout on success.
"""

import argparse
import json
import sys

import requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _token_input import shapes, token_source

REPORT_URL = "https://onping.plowtech.net/tachdb/report"


def main():
    parser = argparse.ArgumentParser(
        description="Generate an OnPing CSV report and print the download URL."
    )
    parser.add_argument("start_date", help="ISO 8601 start date (e.g. 2026-02-22T06:00:00Z)", type=shapes.iso_date_arg)
    parser.add_argument("end_date", help="ISO 8601 end date (e.g. 2026-02-25T06:00:00Z)", type=shapes.iso_date_arg)
    parser.add_argument("pids", nargs="+", help="Parameter IDs (integers)", type=shapes.int_arg)
    parser.add_argument("--step", type=int, default=60, help="Step size in seconds (default: 60)")
    parser.add_argument("--resolution", type=int, default=8, help="Resolution exponent (default: 8)")
    parser.add_argument("--title", default="CSV Report", help="Report title (default: 'CSV Report')")
    parser.add_argument("--vpid", action="store_true", help="Treat PIDs as virtual parameter IDs")

    args = token_source.parse(parser, None, is_id=shapes.is_iso_date)

    if args.vpid:
        pid_list = [{"keyType": "VPID", "keyValue": p} for p in args.pids]
    else:
        pid_list = list(args.pids)

    body = {
        "title": args.title,
        "step": args.step,
        "resolution": args.resolution,
        "startDate": args.start_date,
        "endDate": args.end_date,
        "pidList": pid_list,
    }

    headers = {
        "Authorization": f"Bearer {args.access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    tries = 0
    while True:
        try:
            resp = requests.post(
                REPORT_URL, json=body, headers=headers, timeout=120
            )
        except Exception as e:
            print(f"Request error: {e}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(
                    f"Auth/client error after {tries} attempts: HTTP {resp.status_code}\n{resp.text}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"HTTP {resp.status_code}, retrying ({tries}/3)...", file=sys.stderr)
            continue

        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        try:
            report_url = json.loads(resp.text)
        except Exception as e:
            print(f"Failed to decode URL from JSON string: {e}", file=sys.stderr)
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        if not isinstance(report_url, str) or not report_url.startswith("http"):
            print(f"Unexpected decoded result: {report_url}", file=sys.stderr)
            sys.exit(1)

        print(report_url)
        return


if __name__ == "__main__":
    main()
