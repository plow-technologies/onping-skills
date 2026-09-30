# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Look up Lumberjack profiles by OnPing location ID - takes ACCESS_TOKEN and one or more location IDs."""

import json
import sys

import requests

BASE = "https://onping.plowtech.net"


def fetch_json(method: str, path: str, headers: dict, body=None) -> object:
    """Make an authenticated request with retry logic. Returns parsed JSON."""
    url = f"{BASE}{path}"
    tries = 0
    while True:
        try:
            if method == "GET":
                resp = requests.get(
                    url, headers=headers, allow_redirects=False, timeout=15
                )
            else:
                resp = requests.post(
                    url, json=body, headers=headers, allow_redirects=False, timeout=15
                )
        except requests.RequestException as e:
            print(f"Request error ({path}): {e}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(
                    f"Authentication failed too many times (status {resp.status_code}, path {path}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(f"HTTP {resp.status_code} ({path}):\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        try:
            return resp.json()
        except ValueError as e:
            print(f"Failed to decode JSON response ({path}): {e}", file=sys.stderr)
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)


def fetch_location(headers: dict, location_id: int) -> dict | None:
    """Fetch a single location by ID using the locationLister endpoint."""
    body = {
        "getLocationLookupId": location_id,
        "getCompanyLookupList": [],
        "getSiteLookupList": [],
    }
    data = fetch_json("POST", "/json/listers/locationLister", headers, body)
    if isinstance(data, list) and len(data) > 0:
        entry = data[0]
        return entry.get("value", entry) if isinstance(entry, dict) else entry
    return None


def fetch_profiles(headers: dict) -> list:
    """Fetch all Lumberjack profiles."""
    data = fetch_json("GET", "/las/api/v1/lumberjack/profiles", headers)
    if not isinstance(data, list):
        print(
            f"Unexpected profiles response (expected list): {type(data).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)
    return data


def match_profile(profiles: list, ip: str) -> dict | None:
    """Find the profile matching the given IP via lumberjackUrl.

    Each profile is a [lumberjack_id, profile_object] pair.
    Returns {"lumberjackId": id, ...profile_fields} on match.
    """
    for entry in profiles:
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        lj_id, profile = entry
        if not isinstance(profile, dict):
            continue
        if profile.get("lumberjackUrl") == ip:
            return {"lumberjackId": lj_id, **profile}
    return None


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: lj_profile.py ACCESS_TOKEN LOCATION_ID [LOCATION_ID ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    access_token = sys.argv[1]
    try:
        location_ids = [int(arg) for arg in sys.argv[2:]]
    except ValueError as e:
        print(f"Location IDs must be integers: {e}", file=sys.stderr)
        sys.exit(1)

    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}

    # Fetch all profiles once
    profiles = fetch_profiles(headers)

    results = {}
    for loc_id in location_ids:
        location = fetch_location(headers, loc_id)
        if location is None:
            print(f"Warning: location {loc_id} not found", file=sys.stderr)
            results[str(loc_id)] = None
            continue

        ip = location.get("url")
        if not ip:
            print(
                f"Warning: location {loc_id} has no url field",
                file=sys.stderr,
            )
            results[str(loc_id)] = None
            continue

        matched = match_profile(profiles, ip)
        if matched is None:
            print(
                f"Warning: no profile matched IP {ip} for location {loc_id}",
                file=sys.stderr,
            )
        results[str(loc_id)] = matched

    # Single location: output the matched profile directly
    # Multiple locations: output object keyed by location ID
    if len(location_ids) == 1:
        print(json.dumps(results[str(location_ids[0])], indent=2))
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
