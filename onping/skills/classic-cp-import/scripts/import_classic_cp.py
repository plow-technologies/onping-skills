# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Import classic (legacy, non-Inferno) OnPing control parameters from a Dhall file.

Mirrors the OnPing web UI's import action on the `/v3/control-parameter` page:
`POST /cp/import` with the Dhall CP file as the body (`Content-Type:
text/plain;charset=UTF-8`). This is the write-back inverse of `classic-cp-export`.

This is the CLASSIC control-parameter engine (`/cp/*`), the same one that
`classic-cp-export` / `classic-cp-delete` use. It is NOT the Inferno CP system
(`cpInferno/*`, used by cp-list / cp-import-json).

`/cp/import` is **addOrUpdate keyed by `outputPID`**: an entry whose outputPID
matches an existing classic CP OVERWRITES it; a new outputPID creates one. So
this is a MUTATION — no network call happens unless `--yes` is passed; the
default and `--dry-run` only preview the affected outputPIDs.

Hazard: output PIDs can be reused across lumberjacks (e.g. 400001 is written by
different CPs on serial 1001 and serial 1002), so an import can overwrite a CP on
a different lumberjack than the file came from. Confirm with classic-cp-by-pid /
classic-cp-list, and back up first with classic-cp-export.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 30

_OUTPUT_PID_RE = re.compile(r"outputPID\s*=\s*(\d+)")


def _fail(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(1)


def _read_input(path: str | None) -> str:
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            _fail(f"Could not read --input {path}: {e}")
    data = sys.stdin.read()
    if not data.strip():
        _fail("No Dhall provided — pass --input PATH or pipe the file on stdin.")
    return data


def _extract_output_pids(dhall: str) -> list[int]:
    return [int(m) for m in _OUTPUT_PID_RE.findall(dhall)]


def _import(token: str, dhall: str) -> dict:
    """POST the Dhall body to /cp/import; return a result record.

    Auth-expiry (303 -> /auth/login or an HTML login body) fails fast via
    _fail(); never reported as imported. A non-2xx is a failure with the raw
    body surfaced. A JSON {"error":...} on a 2xx is also a failure.
    """
    url = f"{BASE_URL}/cp/import"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=dhall.encode("utf-8"),
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return {"imported": False, "error": f"request error: {e}"}

    # Auth-expiry fail-fast (redirect to auth or HTML login page).
    if resp.history and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    ):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url}). Nothing was imported."
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        _fail(
            "Expected JSON but received HTML — access token may be expired "
            "or the route returned an error page. Nothing was imported."
        )

    if not (200 <= resp.status_code < 300):
        return {
            "imported": False,
            "error": f"HTTP {resp.status_code}",
            "response": resp.text[:1000],
        }

    # 2xx. Surface the body; a JSON {"error": ...} envelope is a failure.
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        return {"imported": False, "error": str(parsed["error"])}
    return {"imported": True, "response": parsed if parsed is not None else resp.text[:1000]}


_OVERWRITE_WARNING = (
    "Import is addOrUpdate keyed by outputPID: any existing classic CP with a "
    "matching outputPID above will be OVERWRITTEN (script, inputs, schedule, "
    "stepSize, enabled). Output PIDs can be reused across lumberjacks, so this "
    "may overwrite a CP on a different lumberjack — confirm with classic-cp-by-pid "
    "/ classic-cp-list, and back up the current state with classic-cp-export first."
)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Import classic (legacy, non-Inferno) OnPing control parameters "
        "from a Dhall file via POST /cp/import. Mutating (addOrUpdate by outputPID); "
        "requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("--input", help="Dhall CP file to import (default: stdin)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the affected outputPIDs; make no request (default)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="actually import (required for any network call)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = p.parse_args()

    dhall = _read_input(args.input)
    output_pids = _extract_output_pids(dhall)

    # In-file duplicate outputPID detection (the server rejects these).
    dupes = sorted({pid for pid in output_pids if output_pids.count(pid) > 1})

    # Safety gate: no network call unless --yes.
    preview = not args.yes
    if preview:
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "input": args.input or "<stdin>",
                        "outputPIDs": output_pids,
                        "duplicateOutputPIDs": dupes,
                    },
                    indent=2,
                )
            )
        else:
            print("DRY RUN — no request sent. Pass --yes to import.", file=sys.stderr)
            if output_pids:
                print(f"Would create/overwrite {len(output_pids)} classic CP(s) by outputPID:")
                print("  " + ", ".join(str(p) for p in output_pids))
            else:
                print(
                    "Could not enumerate any outputPID in the input (preview only; "
                    "the server still type-checks on --yes).",
                    file=sys.stderr,
                )
            if dupes:
                print(
                    f"WARNING: duplicate outputPID(s) in the file will be rejected: {dupes}",
                    file=sys.stderr,
                )
            print("\n" + _OVERWRITE_WARNING, file=sys.stderr)
        sys.exit(0)

    if dupes:
        _fail(f"Refusing to import: duplicate outputPID(s) in the file: {dupes}")

    result = _import(args.access_token, dhall)

    if args.json:
        print(json.dumps({"mode": "import", "outputPIDs": output_pids, "result": result}, indent=2))
    else:
        if result.get("imported"):
            n = len(output_pids) if output_pids else "?"
            print(f"Imported {n} classic CP(s) (outputPIDs: {output_pids}).")
            print(json.dumps(result.get("response"), indent=2))
        else:
            print(f"Import FAILED — {result.get('error', 'unknown')}", file=sys.stderr)
            if result.get("response"):
                print(result["response"], file=sys.stderr)

    if not result.get("imported"):
        sys.exit(1)


if __name__ == "__main__":
    main()
