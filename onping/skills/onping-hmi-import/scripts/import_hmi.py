# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Import a full OnPing HMI dashboard from an exported Dhall file.

The write-back inverse of `onping-hmi-export`. There is no `/hmi/copy` route, so
this skill reconstructs the two-step the OnPing web UI performs:

  1. POST /hmi/parse/{nil-uuid}  — Dhall HmiDashboard -> canonical JSON. This is
     READ-ONLY (the handler only requires auth; the uuid in the path is ignored)
     and doubles as server-side validation of the whole Dhall file.
  2. POST /hmi/upsert            — the RAW JSON HmiDashboard. Same `dashId`
     OVERWRITES that HMI in place; a different `dashId` CREATES a new one.

By default the import OVERWRITES the HMI whose `dashId` is in the file. Pass
`--new` to generate a fresh `dashId` and create an independent copy instead
(verified: swapping `dashId` alone yields a valid, fully independent HMI — nested
component ids may stay identical).

MUTATION SAFETY: no upsert happens unless `--yes` is passed. The default (and
`--dry-run`) still calls `/hmi/parse` — a read-only validation that also surfaces
the real `dashId` and the overwrite-vs-create decision — but never upserts. This
one read-only network call on dry-run is an intentional divergence from
classic-cp-import (which makes none); it is what lets the preview show the
authoritative target.

CONCURRENCY STAMP (overwrite only): `/hmi/upsert` rejects an overwrite with HTTP 400
and the generic body "Internal Server Error" unless the submitted `dashLastUpdate`
equals the value currently stored for that `dashId`, and `/hmi/parse` does not check
it. So on an overwrite `--yes` this skill reads the stored value immediately before
the upsert and stamps it into the body (`--concurrency-stamp N` overrides,
`--no-concurrency-stamp` opts out). Each successful import bumps the stored value.
A `--new` create has no prior version, so nothing is fetched. A `--new` copy is
panel-less (absent from `GET /hmi/list`); `--record-new PATH` appends its UUID to a file.

Note the Dhall/JSON key split: the Dhall file uses `_dashId`, but the JSON from
parse (and consumed by upsert) uses `dashId`. This skill only ever touches the
JSON `dashId`.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _hmi_routes.hmi_args import parse
from _hmi_routes.hmi_http import _fail, _guard, _url, post_dhall, post_json
from _hmi_routes.routes import ROUTES, TIMEOUT_SECONDS

_NIL_UUID = "00000000-0000-0000-0000-000000000000"


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


def _parse_dhall(token: str, dhall: str) -> dict:
    """POST the Dhall to /hmi/parse; return the canonical JSON HmiDashboard.

    Read-only server-side validation. A non-2xx (e.g. a Dhall type error) or a
    JSON {"error": ...} envelope fails fast — nothing is imported.
    """
    resp = post_dhall(token, ROUTES["parse"]["endpoint"], dhall, uuid=_NIL_UUID)
    if not (200 <= resp.status_code < 300):
        _fail(
            f"HTTP {resp.status_code} parsing the Dhall (the file may be "
            f"malformed):\n{resp.text[:800]}\n\nNothing was imported."
        )
    try:
        parsed = resp.json()
    except ValueError:
        _fail(f"Parse response was not JSON:\n{resp.text[:500]}")
    if isinstance(parsed, dict) and parsed.get("error"):
        _fail(f"Parse failed: {parsed['error']}. Nothing was imported.")
    if not isinstance(parsed, dict) or "dashId" not in parsed:
        _fail(
            "Parse response is not an HmiDashboard object with a 'dashId' "
            f"field:\n{json.dumps(parsed)[:500]}"
        )
    return parsed


# Live-stamp read route (task 1.1): `GET /hmi/{uuid}` returns the JSON HmiDashboard
# (unprefixed keys, incl. dashLastUpdate) and needs only an authenticated user, so it
# is lighter than `GET /hmi/export/{uuid}` (Dhall, needs Write). The export's
# `_dashLastUpdate` is the fallback when the JSON carries no such key.
_DHALL_STAMP = re.compile(r"_dashLastUpdate\s*=\s*\+?(-?\d+)")


def _http_get(token: str, endpoint: str, dash_id: str, accept: str) -> requests.Response:
    url = _url(endpoint, uuid=dash_id)
    headers = {"Authorization": f"Bearer {token}", "Accept": accept}
    try:
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON" if accept == "application/json" else "Dhall")
    return resp


def _fetch_live_stamp(token: str, dash_id: str) -> tuple[str, object]:
    """Read the stored dashLastUpdate of `dash_id`.

    Returns ("found", value), ("absent", None) when the HMI does not exist (the
    upsert would create it), or ("unreadable", None) when neither route yields a value.
    """
    resp = _http_get(token, ROUTES["get"]["endpoint"], dash_id, "application/json")
    if resp.status_code == 404:
        return "absent", None
    if not (200 <= resp.status_code < 300):
        _fail(
            f"HTTP {resp.status_code} reading the live dashLastUpdate of {dash_id}:\n"
            f"{resp.text[:500]}\n\nNothing was imported. Pass --no-concurrency-stamp to skip the read."
        )
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("dashLastUpdate") is not None:
        return "found", body["dashLastUpdate"]
    resp = _http_get(token, ROUTES["export"]["endpoint"], dash_id, "*/*")
    if 200 <= resp.status_code < 300:
        m = _DHALL_STAMP.search(resp.text)
        if m:
            return "found", int(m.group(1))
    return "unreadable", None


def _concurrency_hint(status: int) -> str:
    return (
        f"HTTP {status} on an overwrite is most likely a stale dashLastUpdate (the optimistic-"
        "concurrency stamp): the server answers a rejected stamp with a generic 400 "
        '"Internal Server Error". Every successful import bumps the stored stamp, so an '
        "identical re-import is rejected again."
    )


def _upsert(token: str, dashboard: dict) -> dict:
    """POST the raw HmiDashboard JSON to /hmi/upsert; return a result record."""
    resp = post_json(token, ROUTES["upsert"]["endpoint"], dashboard)
    if not (200 <= resp.status_code < 300):
        return {
            "imported": False,
            "status": resp.status_code,
            "error": f"HTTP {resp.status_code}",
            "response": resp.text[:1000],
        }
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        return {"imported": False, "error": str(parsed["error"])}
    return {"imported": True, "response": parsed if parsed is not None else resp.text[:1000]}


def _stamp_int(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise argparse.ArgumentTypeError("must be digits only (the dashLastUpdate integer)")
    return int(value)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Import a full OnPing HMI dashboard from an exported Dhall "
        "file via POST /hmi/parse then POST /hmi/upsert. Mutating (overwrites the "
        "HMI whose dashId is in the file, or creates a copy with --new); "
        "requires --yes.",
    )
    p.add_argument("--input", help="exported HMI Dhall file (default: stdin)")
    p.add_argument(
        "--new",
        action="store_true",
        help="generate a fresh dashId and CREATE a copy instead of overwriting",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate via /hmi/parse and preview the target; do not upsert (default)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="actually upsert (required to write to OnPing)",
    )
    p.add_argument(
        "--concurrency-stamp",
        type=_stamp_int,
        metavar="N",
        help="overwrite only: submit this dashLastUpdate instead of the live stored value",
    )
    p.add_argument(
        "--no-concurrency-stamp",
        action="store_true",
        help="overwrite only: do not fetch the live stamp; submit the file's own dashLastUpdate",
    )
    p.add_argument(
        "--record-new",
        metavar="PATH",
        help="with --new --yes: append '<uuid><TAB><UTC time>' of the created copy to PATH",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parse(p, argv, reads_stdin=True)

    if args.concurrency_stamp is not None and args.no_concurrency_stamp:
        p.error("--concurrency-stamp and --no-concurrency-stamp are mutually exclusive")
    if args.new and (args.concurrency_stamp is not None or args.no_concurrency_stamp):
        p.error("--concurrency-stamp/--no-concurrency-stamp apply to an overwrite; --new creates and has no stamp")
    if args.record_new and not args.new:
        p.error("--record-new records the UUID of a --new copy; add --new")

    dhall = _read_input(args.input)

    # Step 1: parse (read-only) — validates the Dhall and gives us the JSON + dashId.
    parsed = _parse_dhall(args.access_token, dhall)
    source_id = parsed["dashId"]

    # Step 2 (local): decide the target dashId.
    dashboard = copy.deepcopy(parsed)
    if args.new:
        new_id = str(uuidlib.uuid4())
        dashboard["dashId"] = new_id
        target_id = new_id
        action = "create"
    else:
        target_id = source_id
        action = "overwrite"

    name = dashboard.get("dashName")
    n_components = len(dashboard.get("dashComponents", []))

    # --dry-run wins over --yes; no --yes => preview only.
    preview = args.dry_run or not args.yes
    if preview:
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "input": args.input or "<stdin>",
                        "sourceDashId": source_id,
                        "targetDashId": target_id,
                        "action": action,
                        "dashName": name,
                        "components": n_components,
                    },
                    indent=2,
                )
            )
        else:
            print("DRY RUN — validated via /hmi/parse; no upsert sent. Pass --yes to import.", file=sys.stderr)
            print(f"Source dashId : {source_id}")
            print(f"Target dashId : {target_id}")
            print(f"Name          : {name!r}")
            print(f"Components     : {n_components}")
            if action == "overwrite":
                print(
                    f"\nWould OVERWRITE the existing HMI {target_id} in place "
                    f"(pass --new to create a copy instead).",
                    file=sys.stderr,
                )
                if args.concurrency_stamp is not None:
                    print(f"Would submit dashLastUpdate {args.concurrency_stamp} (--concurrency-stamp).", file=sys.stderr)
                elif args.no_concurrency_stamp:
                    print("Would submit the file's own dashLastUpdate (--no-concurrency-stamp).", file=sys.stderr)
                else:
                    print(
                        "Would read the live dashLastUpdate just before the upsert and stamp it "
                        "(--concurrency-stamp N or --no-concurrency-stamp to change).",
                        file=sys.stderr,
                    )
            else:
                print(
                    f"\nWould CREATE a new HMI {target_id} (a copy of {source_id}); "
                    f"the source is left untouched.",
                    file=sys.stderr,
                )
                print(
                    "The copy is panel-less and will NOT appear in onping-hmi-list; keep its UUID "
                    "(--record-new PATH appends it to a file).",
                    file=sys.stderr,
                )
        sys.exit(0)

    if args.record_new:
        try:
            open(args.record_new, "a", encoding="utf-8").close()
        except OSError as e:
            p.error(f"--record-new {args.record_new} is not writable: {e}; nothing was imported")

    stamp = {"mode": "none", "value": None, "retried": False}
    if action == "overwrite":
        if args.concurrency_stamp is not None:
            dashboard["dashLastUpdate"] = args.concurrency_stamp
            stamp.update(mode="override", value=args.concurrency_stamp)
        elif args.no_concurrency_stamp:
            stamp.update(mode="file", value=dashboard.get("dashLastUpdate"))
        else:
            state, live = _fetch_live_stamp(args.access_token, target_id)
            if state == "found":
                dashboard["dashLastUpdate"] = live
                stamp.update(mode="fetched", value=live)
            elif state == "absent":
                print(
                    f"HMI {target_id} does not exist yet; the upsert will create it (no stamp to match).",
                    file=sys.stderr,
                )
            else:
                print(
                    f"warning: could not read the live dashLastUpdate of {target_id}; submitting the "
                    f"file's own value. A rejected stamp shows as HTTP 400.",
                    file=sys.stderr,
                )
                stamp.update(mode="file", value=dashboard.get("dashLastUpdate"))

    result = _upsert(args.access_token, dashboard)

    if action == "overwrite" and result.get("status") == 400:
        print(_concurrency_hint(400), file=sys.stderr)
        if stamp["mode"] == "fetched":
            state, live = _fetch_live_stamp(args.access_token, target_id)
            if state == "found" and live != stamp["value"]:
                print(f"The stored dashLastUpdate changed ({stamp['value']} -> {live}); retrying once.", file=sys.stderr)
                dashboard["dashLastUpdate"] = live
                stamp.update(value=live, retried=True)
                result = _upsert(args.access_token, dashboard)
            else:
                print("The stored dashLastUpdate is unchanged, so a retry would be rejected again; not retrying.", file=sys.stderr)
        elif stamp["mode"] == "override":
            print("--concurrency-stamp was given explicitly, so it is not replaced and not retried.", file=sys.stderr)
        elif stamp["mode"] == "file":
            print("The file's own dashLastUpdate was submitted; drop --no-concurrency-stamp to stamp the live value.", file=sys.stderr)

    recorded_to = None
    if result.get("imported") and args.record_new:
        stamp_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(args.record_new, "a", encoding="utf-8") as f:
                f.write(f"{target_id}\t{stamp_time}\n")
            recorded_to = args.record_new
        except OSError as e:
            print(f"warning: HMI {target_id} was created but could not be recorded in {args.record_new}: {e}", file=sys.stderr)

    if args.json:
        out = {
            "mode": "import",
            "sourceDashId": source_id,
            "targetDashId": target_id,
            "action": action,
            "result": result,
        }
        if action == "overwrite":
            out["concurrencyStamp"] = stamp
        elif result.get("imported"):
            out["recordedTo"] = recorded_to
        print(json.dumps(out, indent=2))
    else:
        if result.get("imported"):
            verb = "Created" if action == "create" else "Overwrote"
            print(f"{verb} HMI {target_id} ({n_components} component(s), name {name!r}).")
            if action == "create":
                print(f"NEW HMI UUID: {target_id}")
                print(
                    "  This copy is panel-less: onping-hmi-list will not show it. Keep this UUID to "
                    "export or delete it."
                )
                if recorded_to:
                    print(f"  Recorded in {recorded_to}.")
            print(json.dumps(result.get("response"), indent=2))
        else:
            print(f"Import FAILED — {result.get('error', 'unknown')}", file=sys.stderr)
            if result.get("response"):
                print(result["response"], file=sys.stderr)

    if not result.get("imported"):
        sys.exit(1)


if __name__ == "__main__":
    main()
