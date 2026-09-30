# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export classic (legacy, non-Inferno) OnPing control parameters by CPID.

Mirrors the OnPing web UI's export action on the `/v3/control-parameter` page:
`POST /cp/export` with the request body set to a JSON array of CPID integers
(e.g. `[10001,10002]`), returning a Dhall control-parameter file in a single request.

This is the CLASSIC control-parameter engine (`/cp/*`), the same one that
`classic-cp-dhall` imports/exports. It is NOT the Inferno CP system
(`cpInferno/*`, used by cp-list / cp-import-json) — do not use this for
Inferno control parameters.

The exported Dhall entries are keyed by `outputPID` (the PID each CP writes to),
not by the CPIDs given in the request. Use `classic-cp-by-pid` to map outputPIDs
back to CPIDs when composing an export with a delete.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 30


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _export_classic_cps(token: str, cpids: list[int]) -> str:
    """POST the JSON CPID-array to /cp/export; return the Dhall text response.

    Auth-expiry (303 -> /auth/login or an HTML body) fails fast via _fail().
    Non-200 responses surface the raw body and exit non-zero without writing
    any output file.
    """
    url = f"{BASE_URL}/cp/export"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    try:
        resp = requests.post(
            url,
            json=cpids,
            headers=headers,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error: {e}")

    # Auth-expiry fail-fast (redirect to auth or HTML login page).
    if resp.history and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    ):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url}). No file was written."
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        _fail(
            "Expected Dhall but received HTML — access token may be expired "
            "or the route returned an error page. No file was written."
        )

    if not (200 <= resp.status_code < 300):
        _fail(
            f"HTTP {resp.status_code}:\n{resp.text}\n\n"
            f"Export failed. No file was written."
        )

    # Success: return the Dhall text verbatim
    return resp.text


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export classic (legacy, non-Inferno) OnPing control "
        "parameters by CPID via POST /cp/export. Returns a Dhall control-parameter file.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument(
        "--cpids",
        nargs="+",
        type=int,
        required=True,
        help="one or more classic CPIDs to export",
    )
    p.add_argument(
        "--output",
        help="output file path (also prints to stdout)",
    )
    args = p.parse_args()

    # Export the CPs in a single request
    dhall_text = _export_classic_cps(args.access_token, args.cpids)

    # Write to output file if specified (only after confirmed success)
    if args.output:
        Path(args.output).write_text(dhall_text)
        print(f"Exported {len(args.cpids)} CPs to {args.output}", file=sys.stderr)

    # Always print to stdout
    print(dhall_text)


if __name__ == "__main__":
    main()
