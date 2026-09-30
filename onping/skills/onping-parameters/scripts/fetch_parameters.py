# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch OnPing parameters for given locations - takes ACCESS_TOKEN, one or more location IDs, and optional VP flags."""

import argparse
import json
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch OnPing parameters for given locations."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument(
        "location_ids",
        nargs="+",
        help="One or more location IDs (refId from onping-locations)",
    )
    parser.add_argument(
        "--vp", action="store_true", help="Include virtual parameters"
    )
    parser.add_argument(
        "--vp-calc",
        action="store_true",
        help="Include virtual parameters with calculated results",
    )
    parser.add_argument(
        "--exclude-pid", action="store_true", help="Exclude PID parameters"
    )
    args = parser.parse_args()

    try:
        location_ids = [int(lid) for lid in args.location_ids]
    except ValueError as e:
        print(f"Location IDs must be integers: {e}", file=sys.stderr)
        sys.exit(1)

    url = "https://onping.plowtech.net/v2/json/listers/parameters"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {args.access_token}"}
    body = {
        "preq_query": {
            "tag": "ParameterRequestLookupId",
            "contents": {
                "getLocationLookupList": location_ids,
                "getCompanyLookupList": [],
                "getSiteLookupList": [],
            },
        },
        "preq_optionVP": args.vp,
        "preq_optionVPCalculateResult": args.vp_calc,
        "preq_optionExcludePID": args.exclude_pid,
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

        print(json.dumps(data, indent=2))
        return


if __name__ == "__main__":
    main()
