# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete classic (legacy, non-Inferno) OnPing control parameters by CPID.

Mirrors the OnPing web UI's delete action on the
`/v3/control-parameter?cpid=<CPID>` page: `POST /cp/delete` with the request
body set to the bare CPID as a JSON integer (e.g. `10001`), one request per CPID.

This is the CLASSIC control-parameter engine (`/cp/*`), the same one that
`classic-cp-dhall` imports/exports. It is NOT the Inferno CP system
(`cpInferno/*`, used by cp-list / cp-import-json) — do not use this for
Inferno control parameters.

Deletion is IRREVERSIBLE. As a safety gate this script makes NO network call
unless `--yes` is passed; the default (and `--dry-run`) only previews.
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


def _delete_one(token: str, cpid: int) -> dict:
    """POST a single bare-integer CPID to /cp/delete; return a result record.

    Auth-expiry (303 -> /auth/login or an HTML login body) fails fast via
    _fail(); it is never reported as a successful delete. Any other non-2xx is
    a per-CPID failure with the raw body surfaced.
    """
    url = f"{BASE_URL}/cp/delete"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(cpid).encode("utf-8"),
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return {"cpid": cpid, "deleted": False, "error": f"request error: {e}"}

    # Auth-expiry fail-fast (redirect to auth or HTML login page).
    if resp.history and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    ):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url}). No CPID was deleted."
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        _fail(
            "Expected JSON but received HTML — access token may be expired "
            "or the route returned an error page. No CPID was deleted."
        )

    if not (200 <= resp.status_code < 300):
        return {
            "cpid": cpid,
            "deleted": False,
            "error": f"HTTP {resp.status_code}",
            "response": resp.text[:500],
        }

    # 2xx. Surface the body; treat a JSON {"error": ...} envelope as failure.
    body = resp.text
    parsed = None
    try:
        parsed = resp.json()
    except ValueError:
        pass
    if isinstance(parsed, dict) and parsed.get("error"):
        return {
            "cpid": cpid,
            "deleted": False,
            "error": str(parsed["error"]),
        }
    return {
        "cpid": cpid,
        "deleted": True,
        "response": parsed if parsed is not None else body[:500],
    }


def _print_table(records: list[dict], preview: bool) -> None:
    width = max(len("cpid"), *(len(str(r["cpid"])) for r in records))
    status_col = "would delete" if preview else "result"
    print(f"{'cpid'.ljust(width)}  {status_col}")
    print(f"{'-' * width}  {'-' * 40}")
    for r in records:
        if preview:
            print(f"{str(r['cpid']).ljust(width)}  (dry-run — no request sent)")
        elif r.get("deleted"):
            print(f"{str(r['cpid']).ljust(width)}  deleted")
        else:
            print(f"{str(r['cpid']).ljust(width)}  FAILED — {r.get('error', 'unknown')}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Delete classic (legacy, non-Inferno) OnPing control "
        "parameters by CPID via POST /cp/delete. Irreversible; requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("cpids", nargs="+", type=int, help="one or more classic CPIDs")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the CPIDs that would be deleted; make no request (default)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="actually delete (required for any network call)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = p.parse_args()

    # Safety gate: no network call unless --yes. Default and --dry-run preview.
    preview = not args.yes
    if preview:
        records = [{"cpid": c, "would_delete": True} for c in args.cpids]
        if args.json:
            print(json.dumps({"mode": "dry-run", "cpids": records}, indent=2))
        else:
            print(
                "DRY RUN — no request sent. Pass --yes to delete. "
                "Deletion is IRREVERSIBLE; consider a classic-cp-dhall export backup first.",
                file=sys.stderr,
            )
            _print_table(records, preview=True)
        sys.exit(0)

    records = [_delete_one(args.access_token, c) for c in args.cpids]

    if args.json:
        print(json.dumps({"mode": "delete", "results": records}, indent=2))
    else:
        _print_table(records, preview=False)

    # Exit non-zero if any requested delete failed.
    if any(not r.get("deleted") for r in records):
        sys.exit(1)


if __name__ == "__main__":
    main()
