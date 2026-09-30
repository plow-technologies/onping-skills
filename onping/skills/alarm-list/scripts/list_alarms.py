# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List alarm configurations from OnPing - takes ACCESS_TOKEN and optional site/location/company filters."""

import argparse
import json
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List alarm configurations from OnPing."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument(
        "--site",
        action="append",
        dest="site_ids",
        help="Site MongoKey to filter by (can be repeated)",
    )
    parser.add_argument(
        "--location",
        action="append",
        dest="location_ids",
        help="Location MongoKey to filter by (can be repeated)",
    )
    parser.add_argument(
        "--company",
        action="append",
        dest="company_ids",
        help="Company MongoKey to filter by (can be repeated)",
    )
    args = parser.parse_args()

    url = "https://onping.plowtech.net/alarmmix/lister"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {args.access_token}"}
    body = {
        "getAlarmGroups": None,
        "getCallOrderLookups": None,
        "getCompanyLookups": args.company_ids if args.company_ids else None,
        "getLocationLookups": args.location_ids if args.location_ids else None,
        "getSiteLookups": args.site_ids if args.site_ids else None,
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

        # Filter to only Right values (successful alarm lookups), unwrapping them
        alarms = []
        for item in data:
            if isinstance(item, dict) and "Right" in item:
                alarms.append(item["Right"])
            elif not isinstance(item, dict):
                # Plain alarm object (not wrapped in Either)
                alarms.append(item)

        print(json.dumps(alarms, indent=2))
        return


if __name__ == "__main__":
    main()
