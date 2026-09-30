# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Update an OnPing mqtt-json driver location's config (primarily poll time).

Read-modify-write: fetch the current full config, change only the requested
allowlisted field(s), refuse to touch lumberjack-binding/identity fields, and
POST the whole record back. MUTATES live OnPing state when --yes is given.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _driver_update_routes.routes import ROUTES
from _driver_update_routes.update import update_location

DRIVER = "mqtt-json"


def main() -> None:
    route = ROUTES[DRIVER]
    polls = route["poll_field"] is not None
    p = argparse.ArgumentParser(
        description=f"Update the OnPing {DRIVER} driver location config "
        f"(read-modify-write; lumberjack/identity fields are never changed).",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("ref_id", type=int, help="location refId (LocationIdRef)")
    if polls:
        p.add_argument("--poll-time", type=int, help="new poll time in SECONDS")
    p.add_argument(
        "--serial",
        help="Lumberjack serial (LJSerial)"
        + (" — REQUIRED for this driver" if route.get("fetch_serial") or route["fetch_body"] == "ljserial" else ""),
    )
    p.add_argument("--dry-run", action="store_true", help="fetch + show diff, do not POST")
    p.add_argument("--yes", action="store_true", help="apply the update (POST)")
    args = p.parse_args()

    poll_time = getattr(args, "poll_time", None) if polls else None

    update_location(
        args.access_token,
        route,
        args.ref_id,
        poll_time=poll_time,
        serial=args.serial,
        dry_run=args.dry_run,
        confirm=args.yes,
    )


if __name__ == "__main__":
    main()
