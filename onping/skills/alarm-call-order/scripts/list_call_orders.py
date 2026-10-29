# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List alarm call orders from OnPing (read-only).

POST /alarmmix/lister answers OnpingResponse [Either AlarmMixError AlarmConfigMix]:
a bare JSON list of {"Right": AlarmConfigMix} / {"Left": AlarmMixError}, or
{"error": msg} on failure. Each AlarmConfigMix carries callOrderConfig, whose
call order is the orderEntries list (onping #16132, 2026-09-16).

The server is https://onping.plowtech.net unless ONPING_BASE_URL is set.

Exit codes: 0 ok; 1 HTTP, auth, permission, network or server error; 2 bad
arguments; 3 unrecognised response shape (nothing is printed on stdout); 4 the
listing was printed, but alarms on one call order carry different copies of it
(each conflict is a CallOrderConflict in `errors`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net").rstrip("/")
URL = f"{BASE_URL}/alarmmix/lister"
AUTH_MESSAGE = "token expired or invalid; run onping-login"
# postAlarmMixListerR answers a failed checkAlarmLookupPermission with 403 and a
# body that is only the error-log upload status (ErrorLogStatus, a JSON string).
# The token was accepted, so onping-login does not help.
PERMISSION_BODIES = ("ErrorLogCompleted", "ErrorLogFailed")
PERMISSION_MESSAGE = (
    "the account lacks permission for a requested site, location or company "
    "(the token was accepted; onping-login will not help). Check the IDs and the "
    "account's groups"
)
NOT_JSON_HINT = (
    "an HTML page here is usually the login page, meaning the token was not accepted; "
    "run onping-login"
)
FLAG_KEYS = (
    "notificationFlagCall",
    "notificationFlagEmail",
    "notificationFlagText",
    "notificationFlagTextBroadcast",
)
ENTRY_FIELDS = ("userId", "userName", "repeatCount", "notificationFlags")
CONFLICT_TAG = "CallOrderConflict"
BODY_LIMIT = 500

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_SHAPE = 3
EXIT_CONFLICT = 4


class FetchError(Exception):
    """HTTP, auth, permission, network or server-reported failure (exit 1)."""


class ShapeError(Exception):
    """The response does not have the shape this skill knows (exit 3)."""


def _alarm_id(value: Any) -> str:
    """Name an alarmMixId, keeping its tag so regular and VP alarms stay distinct."""
    if isinstance(value, dict) and isinstance(value.get("contents"), str):
        tag = value.get("tag")
        return f"{tag}:{value['contents']}" if isinstance(tag, str) else value["contents"]
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _keys(value: Any) -> str:
    return json.dumps(sorted(value)) if isinstance(value, dict) else type(value).__name__


def _truncate(text: str, limit: int = BODY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [{len(text) - limit} more characters not shown]"


def build_body(site_ids=None, location_ids=None, company_ids=None) -> dict:
    return {
        "getAlarmGroups": None,
        "getCallOrderLookups": None,
        "getCompanyLookups": company_ids or None,
        "getLocationLookups": location_ids or None,
        "getSiteLookups": site_ids or None,
    }


def _json_or_none(resp) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def fetch(access_token: str, body: dict, post=None) -> Any:
    """Make exactly one request and return the decoded JSON body."""
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    try:
        resp = (post or requests.post)(URL, json=body, headers=headers, allow_redirects=False, timeout=15)
    except requests.RequestException as e:
        raise FetchError(f"Request error: {e}") from e

    status = resp.status_code
    if status == 403 and _json_or_none(resp) in PERMISSION_BODIES:
        raise FetchError(f"HTTP 403: {PERMISSION_MESSAGE}")
    if status in (401, 403) or 300 <= status < 400:
        raise FetchError(f"HTTP {status}: {AUTH_MESSAGE}")
    if status != 200:
        parsed = _json_or_none(resp)
        detail = str(parsed["error"]) if isinstance(parsed, dict) and "error" in parsed else resp.text
        raise FetchError(f"HTTP {status}: {_truncate(detail)}")
    try:
        return resp.json()
    except ValueError as e:
        raise ShapeError(
            f"HTTP 200 body is not JSON ({e}); {NOT_JSON_HINT}. Body: {_truncate(resp.text)}"
        ) from e


def _flags(raw: Any, where: str) -> Any:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), bool) for k in FLAG_KEYS):
        raise ShapeError(
            f"{where}: entryConfigNotificationFlags must be null or an object with boolean "
            f"{', '.join(FLAG_KEYS)}; keys found: {_keys(raw)}"
        )
    return raw


def _entry(raw: Any, where: str) -> dict:
    if not isinstance(raw, dict):
        raise ShapeError(f"{where}: the element is not an object; keys found: {_keys(raw)}")
    user_id = raw.get("entryConfigUserId")
    name = raw.get("entryConfigUserName")
    count = raw.get("entryConfigRepeatCount")
    if (
        not isinstance(user_id, str)
        or not isinstance(name, str)
        or not isinstance(count, int)
        or isinstance(count, bool)
    ):
        raise ShapeError(
            f"{where}: the element needs a string entryConfigUserId, a string "
            f"entryConfigUserName and an integer entryConfigRepeatCount; keys found: {_keys(raw)}"
        )
    return {
        "userId": user_id,
        "userName": name,
        "repeatCount": count,
        "notificationFlags": _flags(raw.get("entryConfigNotificationFlags"), where),
    }


def _call_order(alarm: dict, where: str) -> dict:
    cfg = alarm.get("callOrderConfig")
    if not isinstance(cfg, dict):
        state = "missing" if "callOrderConfig" not in alarm else f"a {type(cfg).__name__}"
        raise ShapeError(
            f"{where}: callOrderConfig is {state}, not an object; alarm keys found: {_keys(alarm)}"
        )
    entries = cfg.get("orderEntries")
    if not isinstance(entries, list):
        if "orderEntries" not in cfg and "userNames" in cfg:
            raise ShapeError(
                f"{where}: callOrderConfig has the legacy userNames/repeatCounts shape and no "
                f"orderEntries; keys found: {_keys(cfg)}. The server predates onping #16132 "
                "(onping before 2026-09-16)"
            )
        state = "missing" if "orderEntries" not in cfg else f"a {type(entries).__name__}"
        raise ShapeError(
            f"{where}: callOrderConfig.orderEntries is {state}, not a list; keys found: {_keys(cfg)}"
        )
    name = cfg.get("orderName")
    if not isinstance(name, str):
        raise ShapeError(f"{where}: callOrderConfig.orderName is missing or not a string; keys found: {_keys(cfg)}")
    parsed = [_entry(e, f"{where}, orderEntries[{i}]") for i, e in enumerate(entries)]
    return {
        "orderName": name,
        "entries": parsed,
        "userNames": [e["userName"] for e in parsed],
        "repeatCounts": [e["repeatCount"] for e in parsed],
    }


def _differences(kept: dict, other: dict) -> list[dict]:
    """The fields in which two copies of one call order differ."""
    diffs = []
    if kept["orderName"] != other["orderName"]:
        diffs.append({"field": "orderName", "kept": kept["orderName"], "other": other["orderName"]})
    for i, (a, b) in enumerate(zip(kept["entries"], other["entries"])):
        for field in ENTRY_FIELDS:
            if a[field] != b[field]:
                diffs.append({"field": f"entries[{i}].{field}", "kept": a[field], "other": b[field]})
    if len(kept["entries"]) != len(other["entries"]):
        diffs.append({"field": "entries.length", "kept": len(kept["entries"]), "other": len(other["entries"])})
    return diffs


def _describe(diff: dict) -> str:
    return f"{diff['field']} {json.dumps(diff['kept'])} vs {json.dumps(diff['other'])}"


def _left(value: Any, index: int) -> dict:
    # Every AlarmMixError constructor has fields, so aeson always sends {tag, contents}.
    if not (isinstance(value, dict) and set(value) == {"tag", "contents"} and isinstance(value["tag"], str)):
        raise ShapeError(
            f"element {index}: the Left value is not an AlarmMixError {{tag, contents}}; "
            f"keys found: {_keys(value)}"
        )
    return value


def summarize(data: Any) -> dict:
    """Turn a /alarmmix/lister body into the skill's output. Pure; raises on bad input."""
    if isinstance(data, dict) and "error" in data:
        raise FetchError(f"Server error: {_truncate(str(data['error']))}")
    if not isinstance(data, list):
        raise ShapeError(f"response body is a {type(data).__name__}, not a list; keys found: {_keys(data)}")

    call_orders: dict[str, dict] = {}
    errors: list = []
    total = 0
    for index, item in enumerate(data):
        if isinstance(item, dict) and len(item) == 1 and "Left" in item:
            errors.append(_left(item["Left"], index))
            continue
        if not (isinstance(item, dict) and len(item) == 1 and "Right" in item and isinstance(item["Right"], dict)):
            raise ShapeError(
                f"element {index} is neither {{\"Right\": <alarm>}} nor {{\"Left\": <error>}}; "
                f"keys found: {_keys(item)}"
            )
        alarm = item["Right"]
        alarm_id = _alarm_id(alarm.get("alarmMixId"))
        co_id = alarm.get("callOrderId")
        if not isinstance(co_id, str):
            raise ShapeError(
                f"element {index} (alarm {alarm_id}): callOrderId is {json.dumps(co_id)}, not a string; "
                f"keys found: {_keys(alarm)}"
            )
        co = _call_order(alarm, f"element {index} (alarm {alarm_id}, call order {co_id})")
        record = {
            "alarmName": alarm.get("alarmName"),
            "alarmActive": alarm.get("alarmActive"),
            "alarmMixId": alarm.get("alarmMixId"),
        }
        stored = call_orders.get(co_id)
        if stored is None:
            stored = call_orders[co_id] = {**co, "alarms": []}
        else:
            differs = _differences(stored, co)
            if differs:
                record["configConflict"] = True
                errors.append({
                    "tag": CONFLICT_TAG,
                    "contents": {
                        "callOrderId": co_id,
                        "keptAlarmMixId": _alarm_id(stored["alarms"][0]["alarmMixId"]),
                        "alarmMixId": alarm_id,
                        "differences": differs,
                    },
                })
        stored["alarms"].append(record)
        total += 1

    return {"callOrders": call_orders, "totalAlarms": total, "errors": errors}


def main(argv: list[str] | None = None, post=None) -> int:
    parser = argparse.ArgumentParser(description="List alarm call orders from OnPing (read-only).")
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument("--site", dest="site_ids", nargs="+", help="Site MongoKeys to filter by")
    parser.add_argument("--location", dest="location_ids", nargs="+", help="Location MongoKeys to filter by")
    parser.add_argument("--company", dest="company_ids", nargs="+", help="Company MongoKeys to filter by")
    args = parser.parse_args(argv)

    body = build_body(args.site_ids, args.location_ids, args.company_ids)
    try:
        result = summarize(fetch(args.access_token, body, post=post))
    except FetchError as e:
        print(str(e), file=sys.stderr)
        return EXIT_ERROR
    except ShapeError as e:
        print(f"Unrecognised /alarmmix/lister response: {e}", file=sys.stderr)
        return EXIT_SHAPE

    for co_id, co in result["callOrders"].items():
        if not co["entries"]:
            print(f"call order {co_id} ({co['orderName']!r}) has no entries", file=sys.stderr)
    conflicts = [e for e in result["errors"] if e["tag"] == CONFLICT_TAG]
    for c in conflicts:
        info = c["contents"]
        print(
            f"call order {info['callOrderId']}: alarm {info['alarmMixId']} carries a callOrderConfig that "
            f"differs from alarm {info['keptAlarmMixId']}'s (the copy shown): "
            f"{'; '.join(_describe(d) for d in info['differences'])}",
            file=sys.stderr,
        )
    lefts = len(result["errors"]) - len(conflicts)
    print(
        f"{lefts} alarm error(s) (Left elements) and {len(conflicts)} call order conflict(s) in `errors`",
        file=sys.stderr,
    )
    print(json.dumps(result, indent=2))
    return EXIT_CONFLICT if conflicts else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
