# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Pull one custom-table audit row and decode it into a postable widget.

Reads a row from `custom_table_widget_audit` and converts it to the exact JSON
shape `POST /content/ctable/json` accepts. Read-only: SELECT statements only, no
`--yes` gate.

The decode is the whole job. Four encodings differ between the audit table and the
API, each documented in `_ctable_routes/decode.py` with its source location, and
each found by getting it wrong against real data:

  1. The `s` prefix covers `headers` and each cell's `desc` — and NOT `title` or
     `type`, which are stored raw.
  2. `dashboard` is hex-of-ASCII with the leading `o` stripped.
  3. Six `cellData` display toggles cannot round-trip and come back null.
  4. Sorting is forced to null, or the import handler renumbers every row.

Output is the BARE WIDGET by default, not the `{ctable, cid}` envelope, so it
cannot be posted by accident. Pass `--as-envelope <id>` when you actually mean to
prepare a write.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _audit_db.audit_db import (
    add_common_args,
    query_json,
    query_rows,
    resolve_pg,
    table_exists,
)
from _ctable_routes.decode import (
    DecodeError,
    compare_key_sets,
    decode_audit_row,
    widget_summary,
)
from _ctable_routes.routes import MAX_BODY_BYTES, normalize_ctable_id

TABLE = "custom_table_widget_audit"

# json_build_object keeps the quoted camelCase column names intact; postgres would
# otherwise fold them to lowercase and the keys would not match.
SELECT_EXPR = """json_build_object(
  'id', id, 'edited_on', edited_on, 'edited_by', edited_by,
  'audit_action', audit_action, 'title', title, 'headers', headers,
  'cells', cells, 'type', type, 'zoom', zoom, 'dashboard', dashboard,
  'sortingInformation', "sortingInformation",
  'preferredSortingInformation', "preferredSortingInformation")"""


def main() -> None:
    p = argparse.ArgumentParser(
        description="Pull one custom_table_widget_audit row and decode it into a "
        "postable CustomTableWidget. Read-only.",
    )
    add_common_args(p)
    p.add_argument("audit_row_id", help="the audit table's own row id (from onping-ctable-audit-history)")
    p.add_argument("--output", help="write the decoded JSON here (otherwise stdout)")
    p.add_argument(
        "--as-envelope", metavar="CTABLE_ID",
        help="wrap as {ctable, cid} for onping-ctable-import; off by default so "
             "the output cannot be posted by accident",
    )
    p.add_argument(
        "--compare-live", metavar="PATH",
        help="assert key-set parity against a live onping-ctable-export file",
    )
    p.add_argument("--indent", type=int, default=None, help="pretty-print with this indent")
    args = p.parse_args()

    try:
        row_id = int(args.audit_row_id)
    except ValueError:
        print(f"audit_row_id must be an integer, got {args.audit_row_id!r}", file=sys.stderr)
        sys.exit(2)

    envelope_id = None
    if args.as_envelope:
        try:
            envelope_id = normalize_ctable_id(args.as_envelope)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)

    target = resolve_pg(args.audit_host, verbose=not args.quiet_resolve)
    if not table_exists(target, TABLE):
        print(f"table {TABLE} is absent from {target.dbname}.", file=sys.stderr)
        sys.exit(1)

    exists = query_rows(target, f"SELECT 1 FROM {TABLE} WHERE id = {row_id}")
    if not exists:
        print(
            f"no audit row with id {row_id} in {TABLE}. "
            "Use onping-ctable-audit-history to list valid row ids.",
            file=sys.stderr,
        )
        sys.exit(1)

    # base64 transfer: `psql -tA` line-wraps and COPY tab-escapes, and both
    # corrupt a 655 KB cells column. Observed, not theoretical.
    row = query_json(target, SELECT_EXPR, f"FROM {TABLE} WHERE id = {row_id}")
    if row is None:
        print(f"audit row {row_id} came back empty.", file=sys.stderr)
        sys.exit(1)

    try:
        widget = decode_audit_row(row)
    except DecodeError as exc:
        print(f"decode failed: {exc}", file=sys.stderr)
        sys.exit(1)

    s = widget_summary(widget)
    print(f"audit row  : {row.get('id')}", file=sys.stderr)
    print(f"edited_on  : {row.get('edited_on')}", file=sys.stderr)
    print(f"edited_by  : {row.get('edited_by')}", file=sys.stderr)
    print(f"action     : {row.get('audit_action')}", file=sys.stderr)
    print(
        f"decoded    : {s['rows']} rows x {s['columns']} columns, {s['cells']} cells",
        file=sys.stderr,
    )
    print(f"dashboard  : {s['dashboard']}", file=sys.stderr)
    print(f"type       : {s['type']}", file=sys.stderr)
    if s["row_gaps"]:
        print(
            f"note       : {len(s['row_gaps'])} gap(s) in the row index, first at "
            f"row {s['row_gaps'][0]}",
            file=sys.stderr,
        )

    if args.compare_live:
        try:
            live = json.loads(Path(args.compare_live).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"could not read --compare-live file: {exc}", file=sys.stderr)
            sys.exit(2)
        problems = compare_key_sets(widget, live)
        if problems:
            print("KEY-SET PARITY FAILED against the live widget:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            sys.exit(1)
        print("parity     : key sets match the live widget exactly", file=sys.stderr)

    out = {"ctable": widget, "cid": {"cTableId": envelope_id}} if envelope_id else widget
    text = json.dumps(
        out, indent=args.indent, separators=None if args.indent else (",", ":"), sort_keys=True
    )
    size = len(text.encode())
    print(
        f"size       : {size} bytes ({size / MAX_BODY_BYTES:.0%} of the 8 MiB cap)",
        file=sys.stderr,
    )
    if envelope_id:
        print(f"envelope   : ready to post to {envelope_id}", file=sys.stderr)
    else:
        print(
            "form       : bare widget (pass --as-envelope <id> to make it postable)",
            file=sys.stderr,
        )

    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote      : {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
