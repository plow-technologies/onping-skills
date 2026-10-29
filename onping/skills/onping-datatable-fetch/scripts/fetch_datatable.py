# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read an OnPing Lumberjack data table's rows, with each cell's value and PID pointer.

Read-only. `POST /datatable/<LJ>/source/content/query/v3` with the stored
TableSource, its filters and order cleared so every row is seen. Content and
pointers are joined on tableRowId (the server does not order the pointers).

  - default: the row count and the first --limit rows
  - --row ID: one row as a unit, a cell per column with its pointer and value
  - --pid N / --vpid N: every cell pointing at that PID or VPID
  - --json: machine-readable output to compose with the log-table skills
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes.cli import base_parser, dump, pointer_args, pointer_from  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402


def _cell_text(cell: dict) -> str:
    if cell["text"] is not None or cell["selector"] == "TextTagSelector":
        return repr(cell["text"]) if cell["text"] is not None else "—"
    if cell["pointer"] is None:
        return "—"
    return f"{cell['pointer']} = {cell['value']!r}"


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--row", type=int, metavar="ID", help="print one row (tableRowId) as a unit")
    pointer_args(p, what="find every cell pointing at")
    p.add_argument("--limit", type=int, default=20, help="rows to print by default (default 20)")
    p.add_argument("--offset", type=int, default=0, help="first row to print by default")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args()
    target = pointer_from(args)
    if args.row is not None and target is not None:
        p.error("give --row or --pid/--vpid, not both")

    try:
        src = dt.find_source(args.access_token, args.lj, args.table_uuid)
        if args.row is None and target is None:
            rows, count = dt.query(args.access_token, src, limit=args.limit, offset=args.offset)
            rows.sort(key=lambda r: r["rowId"])
        else:
            rows = dt.query_all(args.access_token, src)
            count = len(rows)
    except LJTableError as e:
        die(e)

    if args.row is not None:
        row = next((r for r in rows if r["rowId"] == args.row), None)
        if row is None:
            ids = [r["rowId"] for r in rows]
            print(f"No row {args.row}; row ids run {min(ids, default='-')}..{max(ids, default='-')} "
                  f"({count} rows).", file=sys.stderr)
            sys.exit(1)
        cells = dt.row_cells(src, row)
        if args.json:
            dump({"lj": src["tableLJSerial"], "table": src["tableId"], "tableName": src["tableName"],
                  "rowId": row["rowId"], "cells": cells})
            return
        print(f"Row {row['rowId']} of {src['tableName']!r} (LJ {src['tableLJSerial']})\n")
        print(f"{'pos':>4}  {'selector':18}  {'name':30}  pointer = value")
        for c in cells:
            print(f"{c['position']:>4}  {str(c['selector']).removesuffix('TagSelector'):18}  "
                  f"{str(c['name'])[:30]:30}  {_cell_text(c)}")
        return

    if target is not None:
        hits = dt.cells_pointing_at(src, rows, target)
        if args.json:
            dump({"pointer": str(target), "rowsScanned": count, "cells": hits})
            return
        print(f"{len(hits)} cell(s) point at {target} ({count} rows scanned)")
        for h in hits:
            print(f"  row {h['rowId']:>5}  pos {h['position']:>3}  {h['name']!r}  value {h['value']!r}")
        return

    if args.json:
        dump({"count": count, "rows": [{"rowId": r["rowId"], "cells": dt.row_cells(src, r)} for r in rows]})
        return
    print(f"{count} row(s) in {src['tableName']!r}; showing {len(rows)} from offset {args.offset}.")
    print("Each cell prints pointer = value; use --row ID for one row in full.\n")
    for r in rows:
        shown = "; ".join(f"{c['name']}: {_cell_text(c)}" for c in dt.row_cells(src, r))
        print(f"row {r['rowId']}: {shown}")


if __name__ == "__main__":
    main()
