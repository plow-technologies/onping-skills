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

Note the Dhall/JSON key split: the Dhall file uses `_dashId`, but the JSON from
parse (and consumed by upsert) uses `dashId`. This skill only ever touches the
JSON `dashId`.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid as uuidlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _hmi_routes.hmi_http import _fail, post_dhall, post_json
from _hmi_routes.routes import ROUTES

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


def _upsert(token: str, dashboard: dict) -> dict:
    """POST the raw HmiDashboard JSON to /hmi/upsert; return a result record."""
    resp = post_json(token, ROUTES["upsert"]["endpoint"], dashboard)
    if not (200 <= resp.status_code < 300):
        return {
            "imported": False,
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


def main() -> None:
    p = argparse.ArgumentParser(
        description="Import a full OnPing HMI dashboard from an exported Dhall "
        "file via POST /hmi/parse then POST /hmi/upsert. Mutating (overwrites the "
        "HMI whose dashId is in the file, or creates a copy with --new); "
        "requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
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
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = p.parse_args()

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
            else:
                print(
                    f"\nWould CREATE a new HMI {target_id} (a copy of {source_id}); "
                    f"the source is left untouched.",
                    file=sys.stderr,
                )
        sys.exit(0)

    result = _upsert(args.access_token, dashboard)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "import",
                    "sourceDashId": source_id,
                    "targetDashId": target_id,
                    "action": action,
                    "result": result,
                },
                indent=2,
            )
        )
    else:
        if result.get("imported"):
            verb = "Created" if action == "create" else "Overwrote"
            print(f"{verb} HMI {target_id} ({n_components} component(s), name {name!r}).")
            print(json.dumps(result.get("response"), indent=2))
        else:
            print(f"Import FAILED — {result.get('error', 'unknown')}", file=sys.stderr)
            if result.get("response"):
                print(result["response"], file=sys.stderr)

    if not result.get("imported"):
        sys.exit(1)


if __name__ == "__main__":
    main()
