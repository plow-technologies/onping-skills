# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Resolve OnPing location refIds to their driver slug (read-only).

Given one or more location refIds, calls `POST /singlewellextras/lister` once,
reads each location's stored `singleWellExtrasProtocol`, and maps it to the
kebab-case driver slug used by the onping-update-<driver> / onping-add-<driver>
skills. Read-only: makes no mutating call.

Two structural gaps are reported (not hidden):
  - sparkplug-bridge is keyed by Lumberjack serial and is NOT stored in
    single_well_extras, so its locations never appear here.
  - the endpoint only returns locations in a group the token's user OWNS.
A refId absent from the response is therefore reported as "unknown" with both
causes and the sparkplug confirmation hint.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 30

# Stored `singleWellExtrasProtocol` string -> kebab-case driver slug.
# Verified against the OnPing `Protocol` ADT
# (Onping/Types/Handler/Source/Location.hs, strings are `show <ctor>`) and
# the mongo `SingleWellExtrasProtocol ==. "..."` filters in onping-core
# (the SingleWellExtras raw MongoDB request module). sparkplug-bridge has no
# entry by design (not stored in single_well_extras).
PROTOCOL_TO_SLUG: dict[str, str] = {
    "Bristol": "bristol",
    "RocTlp": "roc-tlp",
    "ModbusFlexible": "modbus-flexible",
    "ControlLogix": "control-logix",
    "TotalFlow": "total-flow",
    "Micrologix": "micrologix",
    "MicrologixLocal": "micrologix",
    "ManualProtocol": "singlewell-manual",
    "MQTT_JSON": "mqtt-json",
    "OPC_UA": "opc-ua",
    "WellPilot": "wellpilot",
    "UnicoModbus": "unico",
    "Lufkin": "lufkin",
    "OsiIntegration": "osi-integration",
    "HazardPro": "hazard-pro",
    "LumberjackRemote": "lumberjack-remote",
    "ElynxIntegration": "elynx",
    "Sitepro": "sitepro",
    "TankLogix": "tank-logix",
    "TokuIntegration": "toku",
    "DNP3": "dnp3",
}

_UNKNOWN_NOTE = (
    "not in single_well_extras — likely sparkplug-bridge (keyed by LJSerial, "
    "not stored here) or a location not owned by this token's user. "
    "For sparkplug, confirm via POST /sparkplug/bridge/query."
)


def _fail(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(1)


def _fetch_extras(token: str, ref_ids: list[int]) -> list:
    url = f"{BASE_URL}/singlewellextras/lister"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=ref_ids,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error (/singlewellextras/lister): {e}")

    if resp.history and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    ):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url})"
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        _fail(
            "Expected JSON but received HTML — access token may be expired "
            "or the route returned an error page."
        )
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} from /singlewellextras/lister:\n{resp.text[:500]}")
    try:
        data = resp.json()
    except ValueError:
        _fail(f"Response was not JSON:\n{resp.text[:500]}")

    # Real shape: a bare list of {"key": <mongoId>, "value": {...}}.
    # Tolerate an OnpingResponse-style wrapper defensively.
    if isinstance(data, dict):
        if "error" in data and len(data) == 1:
            _fail(f"Lister failed: {data['error']}")
        data = data.get("resp_payload") or data.get("respPayload") or []
    if not isinstance(data, list):
        _fail(f"Unexpected lister payload type: {type(data).__name__}")
    return data


def _extract(item):
    """Return the SingleWellExtras value object from a list item."""
    if isinstance(item, dict) and "value" in item and isinstance(item["value"], dict):
        return item["value"]
    if isinstance(item, dict):
        return item  # already the extras object
    return None


def resolve(token: str, ref_ids: list[int]) -> dict[int, dict]:
    payload = _fetch_extras(token, ref_ids)

    by_ref: dict[int, dict] = {}
    for item in payload:
        v = _extract(item)
        if not v:
            continue
        loc = v.get("singleWellExtrasLocationId")
        proto = v.get("singleWellExtrasProtocol")
        if loc is None:
            continue
        slug = PROTOCOL_TO_SLUG.get(proto)
        if slug:
            by_ref[loc] = {"driver": slug, "protocol": proto}
        else:
            by_ref[loc] = {
                "driver": None,
                "protocol": proto,
                "note": f"legacy/unmapped protocol: {proto!r}",
            }

    out: dict[int, dict] = {}
    for ref in ref_ids:
        if ref in by_ref:
            out[ref] = by_ref[ref]
        else:
            out[ref] = {"driver": None, "protocol": None, "note": _UNKNOWN_NOTE}
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description="Resolve OnPing location refIds to their driver slug "
        "(read-only; one /singlewellextras/lister call).",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("ref_ids", nargs="+", type=int, help="one or more location refIds")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = p.parse_args()

    result = resolve(args.access_token, args.ref_ids)

    if args.json:
        print(json.dumps({str(k): v for k, v in result.items()}, indent=2))
        return

    width = max(len("refId"), *(len(str(r)) for r in result))
    print(f"{'refId'.ljust(width)}  driver")
    print(f"{'-' * width}  {'-' * 24}")
    for ref, info in result.items():
        if info["driver"]:
            print(f"{str(ref).ljust(width)}  {info['driver']}")
        else:
            note = info.get("note", "unknown")
            print(f"{str(ref).ljust(width)}  unknown — {note}")


if __name__ == "__main__":
    main()
