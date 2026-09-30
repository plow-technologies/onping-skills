# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Write a CustomTableWidget back to OnPing, preserving its ObjectId.

`POST /content/ctable/json` is a FULL-DOCUMENT MONGO REPSERT. The chain is
`repsertCustomTableWidget` -> `repsertAndAudit` -> `DB.repsert` ->
`DB.save collection (keyDoc ++ valueDoc)`, and the `_id` comes from the caller. So
the write replaces every field and every cell at that exact id, and creates the
widget when it is absent. **There is no merge step.** Posting 12 cells to a
9,568-cell table leaves 12 cells.

That property is what makes it a faithful restore and what makes a careless post
destructive. Hence `--yes`, and hence the pre-flight refusals below, each of which
corresponds to a way this route can quietly ruin a widget:

  - a null `customTableWidgetDashboard` makes the widget PERMANENTLY unwritable
    through the API, because permission is read from the parent dashboard
  - a differing dashboard silently moves who can edit the widget, so it needs
    `--force`
  - a non-null sorting value makes the handler renumber every cell row index
  - an oversize body is rejected after the upload, so it is measured locally first

And one trap on the way back: **a refusal arrives as HTTP 200** with the bare JSON
string `"insufficient permissions"`. A client that trusts the status code reports a
restore that never happened.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _ctable_routes.ctable_http import check_write_response, get_json, post_json
from _ctable_routes.decode import cell_tuples, widget_summary
from _ctable_routes.routes import (
    MAX_BODY_BYTES,
    REQUIRED_WIDGET_KEYS,
    ROUTES,
    normalize_ctable_id,
)

SCALAR_FIELDS = (
    "customTableWidgetTitle",
    "customTableWidgetHeaders",
    "customTableWidgetType",
    "customTableWidgetZoomLevel",
    "customTableWidgetDashboard",
    "customTableSortingInformation",
    "customTablePreferredSortingInformation",
)


def die(msg: str, *, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def load_widget(path: str) -> dict:
    """Accept either a bare widget or a {ctable, cid} envelope."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        die(f"could not read {path}: {exc}", code=2)
    if isinstance(data, dict) and "ctable" in data and "cid" in data:
        return data["ctable"]
    if not isinstance(data, dict):
        die(f"{path} is not a JSON object", code=2)
    return data


def preflight(widget: dict, target_id: str, current: dict | None, *, force: bool) -> int:
    """Run every local guard. Returns the payload size in bytes, or exits."""
    missing = [k for k in REQUIRED_WIDGET_KEYS if k not in widget]
    if missing:
        die(
            "payload is missing required key(s): " + ", ".join(missing) + "\n"
            "  These are parsed with `.:` rather than `.:?`, so the server rejects "
            "the body without them."
        )

    dashboard = widget.get("customTableWidgetDashboard")
    if not dashboard:
        die(
            "REFUSING TO POST: customTableWidgetDashboard is null or absent.\n"
            "  Permission is read from the parent dashboard, so a widget naming no "
            "dashboard yields CustomTableUserPermissions False False and becomes\n"
            "  permanently unwritable through the API. Set the correct dashboard id "
            "and retry."
        )

    if widget.get("customTableSortingInformation") is not None:
        die(
            "REFUSING TO POST: customTableSortingInformation is not null.\n"
            "  A value carrying both a column and a type makes the handler re-sort "
            "the table and rewrite every cell row index before saving. Set it to "
            "null."
        )

    cells = widget.get("customTableWidgetCells")
    if not isinstance(cells, list):
        die("payload's customTableWidgetCells is not a list")
    for i, c in enumerate(cells):
        for key in ("cellDataRow", "cellDataCol"):
            v = c.get(key)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                die(f"cells[{i}].{key} must be a non-negative integer, got {v!r}")

    if current is not None:
        current_dash = current.get("customTableWidgetDashboard")
        if current_dash and current_dash != dashboard and not force:
            die(
                "REFUSING TO POST: the payload names a different parent dashboard "
                "than the target widget currently names.\n"
                f"  current : {current_dash}\n"
                f"  payload : {dashboard}\n"
                "  Changing it moves who can edit this widget. Pass --force if that "
                "is genuinely intended."
            )

    envelope = {"ctable": widget, "cid": {"cTableId": target_id}}
    size = len(json.dumps(envelope, separators=(",", ":")).encode())
    if size > MAX_BODY_BYTES:
        die(
            f"REFUSING TO POST: the envelope is {size} bytes, over the "
            f"{MAX_BODY_BYTES} byte (8 MiB) cap on this route.\n"
            "  Measured locally rather than paying for the upload to be rejected."
        )
    return size


def main() -> None:
    p = argparse.ArgumentParser(
        description="Write a CustomTableWidget to OnPing via "
        "POST /content/ctable/json. MUTATING — full-document repsert.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("ctable_id", help="target custom table id (o-prefixed or bare 24-hex)")
    p.add_argument("widget_json", help="bare widget or {ctable, cid} envelope")
    p.add_argument("--yes", action="store_true", help="actually perform the write")
    p.add_argument("--dry-run", action="store_true", help="validate and preview only; wins over --yes")
    p.add_argument("--force", action="store_true", help="allow a parent-dashboard change")
    p.add_argument(
        "--verify-live", action="store_true",
        help="after the write, report how many parameters resolve to live values",
    )
    args = p.parse_args()

    try:
        target_id = normalize_ctable_id(args.ctable_id)
    except ValueError as exc:
        die(str(exc), code=2)

    widget = load_widget(args.widget_json)

    current = get_json(
        args.access_token, ROUTES["get_json"]["endpoint"], params={"cTableId": target_id}
    )
    current = current if isinstance(current, dict) else None

    size = preflight(widget, target_id, current, force=args.force)
    new = widget_summary(widget)

    print(f"target      : {target_id}", file=sys.stderr)
    if current is None:
        print("current     : no widget at this id — this write CREATES it", file=sys.stderr)
    else:
        old = widget_summary(current)
        print(
            f"current     : {old['rows']} rows x {old['columns']} columns, "
            f"{old['cells']} cells  (dashboard {old['dashboard']})",
            file=sys.stderr,
        )
    print(
        f"payload     : {new['rows']} rows x {new['columns']} columns, "
        f"{new['cells']} cells  (dashboard {new['dashboard']})",
        file=sys.stderr,
    )
    print(
        f"size        : {size} bytes ({size / MAX_BODY_BYTES:.0%} of the 8 MiB cap)",
        file=sys.stderr,
    )
    if new["row_gaps"]:
        print(
            f"WARNING     : {len(new['row_gaps'])} gap(s) in the row index, first at "
            f"row {new['row_gaps'][0]}. Row indices are positional, so a gap renders "
            "as a blank row.",
            file=sys.stderr,
        )
    if current is not None:
        print(
            "note        : this is a whole-document replace. Back up first with "
            "onping-ctable-export.",
            file=sys.stderr,
        )

    if args.dry_run or not args.yes:
        why = "--dry-run" if args.dry_run else "no --yes"
        print(f"\nNO WRITE PERFORMED ({why}).", file=sys.stderr)
        return

    envelope = {"ctable": widget, "cid": {"cTableId": target_id}}
    resp = post_json(args.access_token, ROUTES["post_json"]["endpoint"], envelope)
    check_write_response(resp)  # the 200-is-not-success guard
    print("\nwrite accepted; verifying by readback...", file=sys.stderr)

    readback = get_json(
        args.access_token, ROUTES["get_json"]["endpoint"], params={"cTableId": target_id}
    )
    if not isinstance(readback, dict):
        die("readback did not return a widget — the write cannot be confirmed")

    problems = [f for f in SCALAR_FIELDS if readback.get(f) != widget.get(f)]
    sent_cells, got_cells = cell_tuples(widget), cell_tuples(readback)
    cells_match = sent_cells == got_cells

    for f in problems:
        print(f"  MISMATCH {f}: sent {widget.get(f)!r}, got {readback.get(f)!r}", file=sys.stderr)
    if cells_match:
        print(f"  cells    : MATCH — all {len(sent_cells)} identical", file=sys.stderr)
    else:
        print(
            f"  MISMATCH cells: sent {len(sent_cells)}, got {len(got_cells)}",
            file=sys.stderr,
        )
        for a, b in zip(sent_cells, got_cells):
            if a != b:
                print(f"    first differing cell: sent {a}, got {b}", file=sys.stderr)
                break

    if problems or not cells_match:
        die(
            "\nREADBACK DIFFERS FROM WHAT WAS SENT. A partial write is worse than a "
            "reported failure — investigate before retrying."
        )
    print(
        f"  scalars  : MATCH — all {len(SCALAR_FIELDS)} fields identical", file=sys.stderr
    )

    if args.verify_live:
        data = get_json(
            args.access_token, ROUTES["table_data"]["endpoint"], params={"cTableId": target_id}
        )
        params = (data or {}).get("parameters") or []
        live = [
            q for q in params
            if isinstance(q.get("tagInfo"), dict) and q["tagInfo"].get("result") is not None
        ]
        print(
            f"  liveness : {len(live)} of {len(params)} parameters resolved to a "
            "current value",
            file=sys.stderr,
        )

    print("\nRESTORE VERIFIED.", file=sys.stderr)


if __name__ == "__main__":
    main()
