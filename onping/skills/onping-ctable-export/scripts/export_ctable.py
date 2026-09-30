# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export an OnPing custom-table widget as JSON.

`GET /content/ctable/json?cTableId=<id>` returns the complete `CustomTableWidget`
— title, headers, every cell, type, zoom, and the parent dashboard. Read-only, no
`--yes` gate. The JSON this emits is posted back by `onping-ctable-import`, so it
is the backup half of that round trip and the first step of any restore.

Two things worth knowing before you rely on it:

  - `cTableId` is a QUERY parameter. Putting the id in the path returns
    `400 "No table id found"`, which looks like a missing widget and is not.
  - A widget that does not exist returns the JSON literal `null` with HTTP 200,
    not a 404. This script treats that as a failure rather than writing `null` to
    a file someone later trusts as a backup.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _ctable_routes.ctable_http import get_json
from _ctable_routes.decode import widget_summary
from _ctable_routes.routes import (
    CAP_WARN_FRACTION,
    MAX_BODY_BYTES,
    ROUTES,
    normalize_ctable_id,
)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export an OnPing custom-table widget as JSON via "
        "GET /content/ctable/json. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("ctable_id", help="custom table id (o-prefixed, or bare 24-hex)")
    p.add_argument("--output", help="write the JSON here (otherwise stdout)")
    p.add_argument(
        "--indent", type=int, default=None,
        help="pretty-print with this indent; default is the compact form that "
             "round-trips byte-identically",
    )
    args = p.parse_args()

    try:
        table_id = normalize_ctable_id(args.ctable_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    widget = get_json(
        args.access_token,
        ROUTES["get_json"]["endpoint"],
        params={"cTableId": table_id},
    )

    # A missing widget is `null` with HTTP 200. Never write that to a backup file.
    if widget is None:
        print(
            f"No custom table widget exists at {table_id}. Nothing was written.\n"
            "  (GET /does/content/ctable/json/exist answers this more cheaply.)",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(widget, dict):
        print(
            f"Unexpected response for {table_id}: expected an object, got "
            f"{type(widget).__name__}. Nothing was written.",
            file=sys.stderr,
        )
        sys.exit(1)

    text = json.dumps(
        widget,
        indent=args.indent,
        separators=None if args.indent else (",", ":"),
        sort_keys=True,
    )
    payload_bytes = len(text.encode())

    s = widget_summary(widget)
    print(
        f"{table_id}: {s['rows']} rows x {s['columns']} columns, {s['cells']} cells",
        file=sys.stderr,
    )
    print(f"  dashboard : {s['dashboard']}", file=sys.stderr)
    print(
        f"  size      : {payload_bytes} bytes "
        f"({payload_bytes / MAX_BODY_BYTES:.0%} of the 8 MiB import cap)",
        file=sys.stderr,
    )
    if s["row_gaps"]:
        print(
            f"  note      : {len(s['row_gaps'])} gap(s) in the row index, first at "
            f"row {s['row_gaps'][0]}",
            file=sys.stderr,
        )
    if payload_bytes > MAX_BODY_BYTES * CAP_WARN_FRACTION:
        print(
            "  WARNING   : this widget is close to the 8 MiB cap on "
            "POST /content/ctable/json. A later re-import can be rejected for size.",
            file=sys.stderr,
        )

    # Write only after a confirmed non-null object, so a failure never clobbers an
    # existing backup.
    if args.output:
        Path(args.output).write_text(text)
        print(f"  wrote     : {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
