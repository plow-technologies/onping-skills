# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Look up classic (legacy, non-Inferno) control parameters by outputPID.

Resolves classic control-parameter outputPIDs to their CPIDs. Given one or more
outputPIDs, calls `POST /cp/by-pid` once per outputPID (the body is the bare
outputPID as a JSON integer), reads `controlParameterID` from each returned
record, and reports the outputPID → CPID mapping.

This is the CLASSIC control-parameter engine (`/cp/*`), the same one that
`classic-cp-dhall` imports/exports and `classic-cp-delete` deletes. It is NOT
the Inferno CP system (`cpInferno/*`, used by cp-list / cp-import-json) — do
not use this for Inferno control parameters.

A classic-CP Dhall file (from `classic-cp-dhall export`) keys every entry by
outputPID (the PID the CP writes to), NOT by CPID. To delete CPs from a Dhall
file, resolve the outputPIDs here first, then feed the CPIDs into
`classic-cp-delete`.
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


def _fetch_one(token: str, output_pid: int) -> dict:
    """POST a single bare-integer outputPID to /cp/by-pid; return a result record.

    Auth-expiry (303 -> /auth/login or an HTML login body) fails fast via
    _fail(); it is never reported as a successful lookup. A `null` (or empty)
    200 body is treated as not-found (no classic CP writes that outputPID).
    Any other non-2xx is a per-outputPID failure with the raw body surfaced.
    """
    url = f"{BASE_URL}/cp/by-pid"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(output_pid).encode("utf-8"),
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return {
            "outputPID": output_pid,
            "cpid": None,
            "error": f"request error: {e}",
        }

    # Auth-expiry fail-fast (redirect to auth or HTML login page).
    if resp.history and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    ):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url}). No outputPID was resolved."
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        _fail(
            "Expected JSON but received HTML — access token may be expired "
            "or the route returned an error page. No outputPID was resolved."
        )

    if not (200 <= resp.status_code < 300):
        return {
            "outputPID": output_pid,
            "cpid": None,
            "error": f"HTTP {resp.status_code}",
            "response": resp.text[:500],
        }

    # 2xx. A null or empty body means no classic CP writes this outputPID.
    body = resp.text.strip()
    if not body or body == "null":
        return {
            "outputPID": output_pid,
            "cpid": None,
            "note": "not found — no classic CP writes this outputPID (may be Inferno-written or already deleted)",
        }

    try:
        parsed = resp.json()
    except ValueError:
        return {
            "outputPID": output_pid,
            "cpid": None,
            "error": "response was not JSON",
            "response": body[:500],
        }

    # The known shape is the bare CP record object; read controlParameterID.
    if not isinstance(parsed, dict):
        return {
            "outputPID": output_pid,
            "cpid": None,
            "error": f"unexpected response type: {type(parsed).__name__}",
            "response": body[:500],
        }

    cpid = parsed.get("controlParameterID")
    if cpid is None:
        return {
            "outputPID": output_pid,
            "cpid": None,
            "note": "response missing controlParameterID",
            "response": body[:500],
        }

    enabled = parsed.get("controlParameterEnabled", None)
    script = parsed.get("controlParameterScript", "")
    output_write = parsed.get("controlParameterOutputWrite")

    # Truncate script to ~50 chars, single line for preview.
    script_preview = script.replace("\n", " ").strip()
    if len(script_preview) > 50:
        script_preview = script_preview[:47] + "..."

    return {
        "outputPID": output_pid,
        "cpid": cpid,
        "enabled": enabled,
        "outputWrite": output_write,
        "script_preview": script_preview,
    }


def _print_table(records: list[dict]) -> None:
    pid_width = max(len("outputPID"), *(len(str(r["outputPID"])) for r in records))
    cpid_width = max(
        len("cpid"),
        *(
            len(str(r.get("cpid", "null")))
            for r in records
            if r.get("cpid") is not None
        ),
        4,  # "null"
    )
    print(
        f"{'outputPID'.ljust(pid_width)}  {'cpid'.ljust(cpid_width)}  enabled  script"
    )
    print(f"{'-' * pid_width}  {'-' * cpid_width}  {'-' * 7}  {'-' * 50}")
    for r in records:
        pid_str = str(r["outputPID"]).ljust(pid_width)
        cpid_val = r.get("cpid")
        if cpid_val is None:
            cpid_str = "null".ljust(cpid_width)
            enabled_str = "—".ljust(7)
            note = r.get("note") or r.get("error", "unknown")
            print(f"{pid_str}  {cpid_str}  {enabled_str}  ({note})")
        else:
            cpid_str = str(cpid_val).ljust(cpid_width)
            enabled = r.get("enabled")
            enabled_str = (
                str(enabled).ljust(7) if enabled is not None else "—".ljust(7)
            )
            script = r.get("script_preview", "")
            print(f"{pid_str}  {cpid_str}  {enabled_str}  {script}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Look up classic (legacy, non-Inferno) OnPing control "
        "parameters by outputPID via POST /cp/by-pid. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument(
        "output_pids", nargs="+", type=int, help="one or more classic-CP outputPIDs"
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    p.add_argument(
        "--cpids-only",
        action="store_true",
        help="print only resolved CPIDs space-separated (skip not-found)",
    )
    args = p.parse_args()

    records = [_fetch_one(args.access_token, pid) for pid in args.output_pids]

    if args.cpids_only:
        cpids = [str(r["cpid"]) for r in records if r.get("cpid") is not None]
        print(" ".join(cpids))
        return

    if args.json:
        out = {}
        for r in records:
            pid_key = str(r["outputPID"])
            if r.get("cpid") is not None:
                out[pid_key] = {
                    "cpid": r["cpid"],
                    "enabled": r.get("enabled"),
                    "outputWrite": r.get("outputWrite"),
                    "script_preview": r.get("script_preview", ""),
                }
            else:
                out[pid_key] = {
                    "cpid": None,
                    "note": r.get("note") or r.get("error", "unknown"),
                }
        print(json.dumps(out, indent=2))
        return

    _print_table(records)


if __name__ == "__main__":
    main()
