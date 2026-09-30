# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch alarm call order information from OnPing."""

import argparse
import json
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="List alarm call orders from OnPing.")
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument("--site", dest="site_ids", nargs="+", help="Site MongoKeys to filter by")
    parser.add_argument("--location", dest="location_ids", nargs="+", help="Location MongoKeys to filter by")
    parser.add_argument("--company", dest="company_ids", nargs="+", help="Company MongoKeys to filter by")
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
            resp = requests.post(url, json=body, headers=headers, allow_redirects=False, timeout=15)
        except requests.RequestException as e:
            print(f"Request error: {e}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(f"Authentication failed too many times (status {resp.status_code}).", file=sys.stderr)
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        try:
            data = resp.json()
        except ValueError as e:
            print(f"Failed to decode JSON response: {e}", file=sys.stderr)
            sys.exit(1)

        # Unwrap Right values from Either response
        alarms = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and "Right" in item:
                alarms.append(item["Right"])

        # Group alarms by call order
        call_orders: dict[str, dict] = {}
        for alarm in alarms:
            co_id = alarm.get("callOrderId", "unknown")
            co_cfg = alarm.get("callOrderConfig", {})
            if co_id not in call_orders:
                call_orders[co_id] = {
                    "orderName": co_cfg.get("orderName", ""),
                    "userNames": co_cfg.get("userNames", []),
                    "repeatCounts": co_cfg.get("repeatCounts", []),
                    "alarms": [],
                }
            call_orders[co_id]["alarms"].append({
                "alarmName": alarm.get("alarmName"),
                "alarmActive": alarm.get("alarmActive"),
                "alarmMixId": alarm.get("alarmMixId"),
            })

        result = {
            "callOrders": call_orders,
            "totalAlarms": len(alarms),
        }

        print(json.dumps(result, indent=2))
        return


if __name__ == "__main__":
    main()
