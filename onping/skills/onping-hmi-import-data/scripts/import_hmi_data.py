# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Import data-binding mappings into an existing OnPing HMI from a Dhall file.

The write-back inverse of `onping-hmi-export-data`. `POST /hmi/import-data/{uuid}`
takes a Dhall `[DataImport]` body (each `{ from: { onpingKey, description }, to:
Maybe onpingKey }`) and applies those bindings to the HMI identified by `{uuid}`
— re-pointing which OnPing parameters the HMI reads, without changing its layout.

MUTATION SAFETY: nothing is written unless `--yes` is passed. The default (and
`--dry-run`) only previews the target UUID and the input; no network call is
made in preview mode. Requires **Write** permission on the target HMI.

For the FULL dashboard (layout + everything), use `onping-hmi-import` instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _hmi_routes.hmi_http import _fail, post_dhall
from _hmi_routes.routes import ROUTES

# Best-effort count of `from =` records for a friendlier preview (not load-bearing).
_FROM_RE = re.compile(r"\bfrom\s*=")


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


def _import_data(token: str, uuid: str, dhall: str) -> dict:
    resp = post_dhall(token, ROUTES["import-data"]["endpoint"], dhall, uuid=uuid)
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
        description="Import data-binding mappings into an existing OnPing HMI "
        "from a Dhall file via POST /hmi/import-data/{uuid}. Mutating; requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("uuid", help="target HMI dashboard UUID whose data bindings to replace")
    p.add_argument("--input", help="Dhall [DataImport] file (default: stdin)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the target and input; make no request (default)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="actually import (required for any network call)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = p.parse_args()

    dhall = _read_input(args.input)
    n_bindings = len(_FROM_RE.findall(dhall))

    # --dry-run wins over --yes; no --yes => preview only (no network call).
    preview = args.dry_run or not args.yes
    if preview:
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "targetUuid": args.uuid,
                        "input": args.input or "<stdin>",
                        "bindings": n_bindings,
                    },
                    indent=2,
                )
            )
        else:
            print("DRY RUN — no request sent. Pass --yes to import.", file=sys.stderr)
            print(f"Target HMI : {args.uuid}")
            print(f"Bindings    : ~{n_bindings} (from the input file)")
            print(
                f"\nWould replace the data bindings on HMI {args.uuid} with the "
                f"mappings in the input. Layout is unchanged.",
                file=sys.stderr,
            )
        sys.exit(0)

    result = _import_data(args.access_token, args.uuid, dhall)

    if args.json:
        print(
            json.dumps(
                {"mode": "import", "targetUuid": args.uuid, "result": result}, indent=2
            )
        )
    else:
        if result.get("imported"):
            print(f"Imported data bindings into HMI {args.uuid}.")
            print(json.dumps(result.get("response"), indent=2))
        else:
            print(f"Import FAILED — {result.get('error', 'unknown')}", file=sys.stderr)
            if result.get("response"):
                print(result["response"], file=sys.stderr)

    if not result.get("imported"):
        sys.exit(1)


if __name__ == "__main__":
    main()
