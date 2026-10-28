# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List OnPing control parameters by Lumberjack ID - takes ACCESS_TOKEN and one or more Lumberjack IDs."""

import argparse
import json
import sys
from collections import Counter
from typing import Any

import requests

READABLE = "ReadableControlParameterInferno"
ORPHANED = "OrphanedControlParameterInferno"
PROHIBITED = "ProhibitedReadControlParameterInferno"
FAILED = "FailedToReadControlParameterInfernoPermissions"
KNOWN_TAGS = (READABLE, ORPHANED, PROHIBITED, FAILED)


def _bare_cpid(value: Any) -> dict | None:
    """The ``{engineHost, perEngineId}`` dict inside any CPID form, or None.

    Accepts the bare form, ``{"CPID": {...}}`` / ``{"ACPID": {...}}`` and the
    tagged ``{"tag": "CPID" | "ACPID", "contents": {...}}`` form.
    """
    if not isinstance(value, dict):
        return None
    if "engineHost" in value and "perEngineId" in value:
        return value
    for key in ("CPID", "ACPID"):
        inner = value.get(key)
        if isinstance(inner, dict) and "engineHost" in inner and "perEngineId" in inner:
            return inner
    if value.get("tag") in ("CPID", "ACPID"):
        inner = value.get("contents")
        if isinstance(inner, dict) and "engineHost" in inner and "perEngineId" in inner:
            return inner
    return None


def friendly_cpid(value: Any) -> str:
    """Render a CPID as ``host-uuid``; ``<unparsed>`` when absent, JSON when unrecognised."""
    if value is None:
        return "<unparsed>"
    if isinstance(value, str):
        return value
    bare = _bare_cpid(value)
    if bare is not None:
        return f"{bare['engineHost']}-{bare['perEngineId']}"
    return json.dumps(value)


def non_readable_notice(elements: Any, lumberjack_id: int | str) -> list[str]:
    """Describe every /cpInferno/list element that is not a readable CP.

    Returns the stderr lines to print, or an empty list when every element is
    ``ReadableControlParameterInferno`` (or the response is not a list). The
    list elements are a tagged union (onping #16220):

    - ``ReadableControlParameterInferno``: ``contents`` is ``{cpId, cpData}``
    - ``OrphanedControlParameterInferno``: ``contents`` is ``[{cpId, cpData}, [missing PID, ...]]``
    - ``ProhibitedReadControlParameterInferno``: ``contents`` is the CPID
    - ``FailedToReadControlParameterInfernoPermissions``: ``contents`` is the CPID
    """
    if not isinstance(elements, list):
        return []

    counts: Counter[str] = Counter()
    detail: list[str] = []
    for index, element in enumerate(elements):
        tag = element.get("tag") if isinstance(element, dict) else None
        label = tag if isinstance(tag, str) else "<untagged>"
        counts[label] += 1
        if label == READABLE:
            continue
        contents = element.get("contents") if isinstance(element, dict) else None
        if label == ORPHANED:
            cp: Any = None
            missing: Any = None
            if isinstance(contents, list) and len(contents) == 2:
                cp, missing = contents
            cp_id = friendly_cpid(cp.get("cpId")) if isinstance(cp, dict) else "<unparsed>"
            name = ""
            if isinstance(cp, dict) and isinstance(cp.get("cpData"), dict):
                name = cp["cpData"].get("name", "")
            detail.append(
                f"  [{index}] orphaned: {cp_id} {json.dumps(name)} "
                f"missing output PIDs {json.dumps(missing)}"
            )
        elif label == PROHIBITED:
            detail.append(f"  [{index}] prohibited (no read permission): {friendly_cpid(contents)}")
        elif label == FAILED:
            detail.append(
                f"  [{index}] failed permission lookup: {friendly_cpid(contents)}"
            )
        else:
            detail.append(f"  [{index}] unknown tag: {label}")

    if not detail:
        return []

    summary = ", ".join(f"{tag}={count}" for tag, count in counts.items())
    return [
        f"cp-list: Lumberjack {lumberjack_id}: {len(elements)} element(s), "
        f"{len(detail)} not readable as a normal CP ({summary}):",
        *detail,
    ]


def print_notice(elements: Any, lumberjack_id: int | str) -> None:
    for line in non_readable_notice(elements, lumberjack_id):
        print(line, file=sys.stderr)


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
        print_notice(data, args.lumberjack_ids[0])
        return

    results = {}
    for lumberjack_id in args.lumberjack_ids:
        results[str(lumberjack_id)] = fetch_control_parameters(
            args.access_token, lumberjack_id
        )

    print(json.dumps(results, indent=2))
    for lumberjack_id, data in results.items():
        print_notice(data, lumberjack_id)


if __name__ == "__main__":
    main()
