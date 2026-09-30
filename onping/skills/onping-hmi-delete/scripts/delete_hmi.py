# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete an OnPing HMI dashboard by UUID.

`DELETE /hmi/delete/{uuid}` removes an HMI. This is a SOFT delete: OnPing sets
`dashDeleted = true` on the dashboard; `GET /hmi/{uuid}` still returns the
(flagged) record afterward. Requires **Delete** permission on the HMI UUID.

MUTATION SAFETY: nothing is deleted unless `--yes` is passed. The default (and
`--dry-run`) probe the HMI via `GET /hmi/{uuid}` to show what would be deleted,
but do not delete. Back up first with `onping-hmi-export`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _hmi_routes.hmi_http import _fail, delete, get_json
from _hmi_routes.routes import ROUTES


def main() -> None:
    p = argparse.ArgumentParser(
        description="Delete an OnPing HMI dashboard via DELETE /hmi/delete/{uuid}. "
        "Soft delete (sets dashDeleted=true); mutating; requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("uuid", help="HMI dashboard UUID to delete")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="probe the HMI and preview; do not delete (default)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="actually delete (required for the DELETE call)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = p.parse_args()

    # --dry-run wins over --yes; no --yes => preview only.
    preview = args.dry_run or not args.yes
    if preview:
        # Read-only existence probe so the preview shows the real target.
        dash = get_json(args.access_token, ROUTES["get"]["endpoint"], uuid=args.uuid)
        name = dash.get("dashName") if isinstance(dash, dict) else None
        already = dash.get("dashDeleted") if isinstance(dash, dict) else None
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "uuid": args.uuid,
                        "dashName": name,
                        "alreadyDeleted": already,
                    },
                    indent=2,
                )
            )
        else:
            print("DRY RUN — no delete sent. Pass --yes to delete.", file=sys.stderr)
            print(f"HMI        : {args.uuid}")
            print(f"Name       : {name!r}")
            if already:
                print("Note        : this HMI is already flagged deleted (dashDeleted=true).", file=sys.stderr)
            print(
                f"\nWould soft-delete HMI {args.uuid} (sets dashDeleted=true). "
                f"Back up first with onping-hmi-export.",
                file=sys.stderr,
            )
        sys.exit(0)

    resp = delete(args.access_token, ROUTES["delete"]["endpoint"], uuid=args.uuid)
    ok = 200 <= resp.status_code < 300
    if args.json:
        print(
            json.dumps(
                {
                    "mode": "delete",
                    "uuid": args.uuid,
                    "deleted": ok,
                    "status": resp.status_code,
                    "response": resp.text[:500],
                },
                indent=2,
            )
        )
    else:
        if ok:
            print(f"Deleted HMI {args.uuid} (soft delete; dashDeleted=true).")
        else:
            print(f"Delete FAILED — HTTP {resp.status_code}", file=sys.stderr)
            print(resp.text[:500], file=sys.stderr)

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
