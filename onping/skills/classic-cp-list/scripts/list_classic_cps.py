# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List classic (legacy, non-Inferno) OnPing control parameters by Lumberjack serial.

Mirrors the OnPing web UI's list action on the `/v3/control-parameter` page:
`POST /cp/list/by-lj-ident-key` with a tagged identity-key body
`{"tag":"IdentityKeySerialNum","contents":<serial:int>}`, one request per serial.

This is the CLASSIC control-parameter engine (`/cp/*`), the same one that
`classic-cp-dhall` imports/exports and `classic-cp-delete` removes. It is NOT
the Inferno CP system (`cpInferno/*`, used by cp-list / cp-import-json) — do
not use this for Inferno control parameters.

The request contract differs from the Inferno `cp-list`: this endpoint takes a
tagged identity key (Lumberjack serial number), not a bare Lumberjack ID. The
serial this endpoint expects may differ from the numeric Lumberjack ID used by
cp-list / lj-profile. v1 supports serial-number input only; other identity-key
variants are unverified and documented as TODO.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 30


def _fail(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(1)


def _list_one(token: str, serial: int) -> dict:
    """POST a tagged serial identity key to /cp/list/by-lj-ident-key; return result.

    Auth-expiry (303 -> /auth/login or an HTML login body) fails fast via
    _fail(). Any other non-2xx is surfaced as an error. An empty list is a
    valid success (serial with no classic CPs).
    """
    url = f"{BASE_URL}/cp/list/by-lj-ident-key"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"tag": "IdentityKeySerialNum", "contents": serial}
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=body,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return {
            "serial": serial,
            "error": f"request error: {e}",
            "cps": [],
        }

    # Auth-expiry fail-fast (redirect to auth or HTML login page).
    if resp.history and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    ):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url}). No CPs were listed."
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        _fail(
            "Expected JSON but received HTML — access token may be expired "
            "or the route returned an error page. No CPs were listed."
        )

    if not (200 <= resp.status_code < 300):
        return {
            "serial": serial,
            "error": f"HTTP {resp.status_code}",
            "response": resp.text[:500],
            "cps": [],
        }

    # 2xx. Parse the top-level list.
    try:
        data = resp.json()
    except ValueError:
        return {
            "serial": serial,
            "error": "response was not JSON",
            "response": resp.text[:500],
            "cps": [],
        }

    if not isinstance(data, list):
        return {
            "serial": serial,
            "error": f"expected a list, got {type(data).__name__}",
            "response": str(data)[:500],
            "cps": [],
        }

    # Parse each element. The list can mix element tags:
    #   {"tag":"ReadableControlParameter","contents":{...full record...}}
    #   {"tag":"ProhibitedReadControlParameter","contents":<cpid int>}
    #       — a CP the token's user is not permitted to read; only its CPID is
    #         returned (no record). Surfaced separately so the count is honest.
    # Any other tag is captured under `other` rather than dropped.
    cps = []
    prohibited = []  # CPIDs the user cannot read
    other = []  # unrecognized element shapes, kept verbatim for visibility
    for elem in data:
        if isinstance(elem, dict):
            tag = elem.get("tag")
            if tag == "ReadableControlParameter" and isinstance(elem.get("contents"), dict):
                cps.append(elem["contents"])
            elif tag == "ProhibitedReadControlParameter":
                prohibited.append(elem.get("contents"))
            elif "controlParameterID" in elem:
                # Defensive: already a bare CP record
                cps.append(elem)
            else:
                other.append(elem)
        else:
            other.append(elem)
    return {"serial": serial, "cps": cps, "prohibited": prohibited, "other": other}


def _format_schedule(schedule: dict | None) -> str:
    """Compact schedule representation: tag + contents."""
    if not schedule or not isinstance(schedule, dict):
        return "—"
    tag = schedule.get("tag", "")
    contents = schedule.get("contents")
    if contents:
        return f"{tag} {contents}"
    return tag


def _print_prohibited(serial: int, prohibited: list, other: list) -> None:
    """Report unreadable / unrecognized elements to stderr so counts stay honest."""
    if prohibited:
        ids = ", ".join(str(c) for c in prohibited)
        print(
            f"Serial {serial}: {len(prohibited)} classic CP(s) not readable by "
            f"this token (no read access): {ids}",
            file=sys.stderr,
        )
    if other:
        print(
            f"Serial {serial}: {len(other)} unrecognized element(s) skipped "
            f"(use --json to inspect)",
            file=sys.stderr,
        )


def _print_table(serial: int, cps: list[dict]) -> None:
    if not cps:
        print(f"Serial {serial}: 0 readable classic CPs", file=sys.stderr)
        return

    print(f"\nSerial {serial}:", file=sys.stderr)
    # Column widths
    cpid_w = max(len("cpid"), *(len(str(cp.get("controlParameterID", ""))) for cp in cps))
    out_w = max(len("outputPID"), *(len(str(cp.get("controlParameterOutputWrite", ""))) for cp in cps))
    en_w = len("enabled")
    sched_w = max(len("schedule"), *(len(_format_schedule(cp.get("controlParameterSchedule"))) for cp in cps))

    # Header
    print(f"{'cpid'.ljust(cpid_w)}  {'outputPID'.ljust(out_w)}  {'enabled'.ljust(en_w)}  {'schedule'.ljust(sched_w)}  script")
    print(f"{'-' * cpid_w}  {'-' * out_w}  {'-' * en_w}  {'-' * sched_w}  {'-' * 40}")

    for cp in cps:
        cpid = str(cp.get("controlParameterID", ""))
        out_pid = str(cp.get("controlParameterOutputWrite", ""))
        enabled = "true" if cp.get("controlParameterEnabled") else "false"
        schedule = _format_schedule(cp.get("controlParameterSchedule"))
        script = cp.get("controlParameterScript", "")
        # Truncate script to ~40 chars, single line
        script_preview = script.replace("\n", " ")[:40]
        if len(script) > 40:
            script_preview += "…"

        print(f"{cpid.ljust(cpid_w)}  {out_pid.ljust(out_w)}  {enabled.ljust(en_w)}  {schedule.ljust(sched_w)}  {script_preview}")

    print(f"{len(cps)} readable classic CPs on serial {serial}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(
        description="List classic (legacy, non-Inferno) OnPing control parameters "
        "by Lumberjack serial via POST /cp/list/by-lj-ident-key. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serials", nargs="+", type=int, help="one or more Lumberjack serial numbers")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    p.add_argument(
        "--cpids-only",
        action="store_true",
        help="print only the CPIDs (space-separated, for piping into classic-cp-delete)",
    )
    p.add_argument(
        "--enabled-only",
        action="store_true",
        help="filter to enabled CPs only",
    )
    args = p.parse_args()

    results = [_list_one(args.access_token, s) for s in args.serials]

    # Check for errors
    errors = [r for r in results if "error" in r]
    if errors:
        for err in errors:
            print(
                f"Serial {err['serial']}: {err['error']}",
                file=sys.stderr,
            )
        sys.exit(1)

    # Apply --enabled-only filter
    if args.enabled_only:
        for r in results:
            r["cps"] = [cp for cp in r["cps"] if cp.get("controlParameterEnabled")]

    if args.cpids_only:
        cpids = []
        for r in results:
            cpids.extend(str(cp.get("controlParameterID", "")) for cp in r["cps"])
        print(" ".join(cpids))
        return

    if args.json:
        # Include prohibited/other so the machine consumer sees the full picture,
        # not just readable CPs. Omit empty prohibited/other for cleanliness.
        def _entry(r: dict) -> dict:
            e: dict = {"cps": r["cps"]}
            if r.get("prohibited"):
                e["prohibited"] = r["prohibited"]
            if r.get("other"):
                e["other"] = r["other"]
            return e

        if len(results) == 1:
            print(json.dumps(_entry(results[0]), indent=2))
        else:
            out = {str(r["serial"]): _entry(r) for r in results}
            print(json.dumps(out, indent=2))
        return

    # Default: table per serial, then any not-readable / unrecognized elements.
    for r in results:
        _print_table(r["serial"], r["cps"])
        _print_prohibited(r["serial"], r.get("prohibited", []), r.get("other", []))


if __name__ == "__main__":
    main()
