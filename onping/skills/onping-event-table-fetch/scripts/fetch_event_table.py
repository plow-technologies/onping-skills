# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch the rows an OnPing event table renders at a given time.

`POST /event/table/fetch` with `{"fetchEventTableUUID": {"unEventTableUUID": …},
"fetchTime": "<ISO-8601 UTC>"}` returns the rendered rows. Read-only — no
`--yes` gate.

If any column reads a key with no TagInfo — a deleted PID, for example — OnPing
fails the WHOLE table with HTTP 500 `failed to lookup TagInfo for key: KeyPID N`
(verified live 2026-10-02). This script names that key as the likely cause and
points at `onping-pid-locate`. OnPing reports only the first dead key it meets,
so the script also says to check every bound key.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _event_table_routes.event_table_http import EventTableError, die, error_text, post_json
from _event_table_routes.routes import ROUTES

_DEAD_KEY = re.compile(r"failed to lookup TagInfo for key:?\s*(.*)", re.IGNORECASE)
_KEY_PARTS = re.compile(r"(VPID|PID)\D*?(\d+)", re.IGNORECASE)


def parse_time(text: str) -> str:
    when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise argparse.ArgumentTypeError("--at needs a timezone, for example 2026-10-01T12:00:00Z")
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Fetch an OnPing event table's rendered rows via POST /event/table/fetch. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("uuid", help="event-table UUID (from onping-event-table-list)")
    p.add_argument("--at", type=parse_time, help="fetch time, ISO-8601 with zone (default: now, UTC)")
    p.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    args = p.parse_args()

    fetch_time = args.at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {"fetchEventTableUUID": {"unEventTableUUID": args.uuid}, "fetchTime": fetch_time}
    try:
        rows = post_json(args.access_token, ROUTES["fetch"]["endpoint"], body)
    except EventTableError as err:
        m = _DEAD_KEY.search(error_text(err.body)) if err.body else None
        if m:
            key = _KEY_PARTS.search(m.group(1))
            named = f"{key.group(1).upper()} {key.group(2)}" if key else m.group(1).strip()
            print(f"TABLE DOES NOT RENDER: OnPing could not look up {named}.", file=sys.stderr)
            print(f"Likely cause: {named} no longer exists, or you cannot read it.", file=sys.stderr)
            print("OnPing stops at the FIRST key it cannot look up, so more keys can be dead.",
                  file=sys.stderr)
            print("Next step: list every bound key with onping-event-table-get --bindings, "
                  "then check them all with onping-pid-locate.", file=sys.stderr)
        die(err)

    print(f"{len(rows)} row(s) at {fetch_time}", file=sys.stderr)
    print(json.dumps(rows, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
