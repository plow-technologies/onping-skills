# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Adjust the PIDs in an OnPing Lumberjack data table's cells. MUTATING — requires --yes.

A data-table column holds only a selector; each row's cell holds the PID as
text ("1234" or "4321 VPID"). This rewrites cells through
`POST /datatable/<LJ>/source/content/update`, which needs each changed row's
FULL value list in position order. Two modes:

  --row ID --column REF  (--pid N | --vpid N | --text T | --clear)
      set one cell;
  --replace-pid OLD NEW | --replace-vpid OLD NEW  [--column REF]
      rewrite every cell pointing at OLD (optionally in one column only).

A pointer is refused in a Text column, and text in a pointer column. Without
--yes nothing is posted. With --yes the pre-edit rows are backed up, the
update is posted, and the rows are re-read and compared.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes.cli import base_parser, fail  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags, should_post, write_backup  # noqa: E402
from _lj_table_routes.pointers import TEXT_SELECTOR, Pointer, render_cell  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--row", type=int, metavar="ID", help="tableRowId of the cell to set")
    p.add_argument("--column", metavar="POS|UUID|NAME",
                   help="the cell's column (with --row), or limit a --replace-* to one column")
    value = p.add_mutually_exclusive_group()
    value.add_argument("--pid", type=int, metavar="N", help="point the cell at PID N")
    value.add_argument("--vpid", type=int, metavar="N", help="point the cell at VPID N")
    value.add_argument("--text", metavar="T", help="literal text (Text columns only)")
    value.add_argument("--clear", action="store_true", help="empty the cell (null)")
    value.add_argument("--replace-pid", type=int, nargs=2, metavar=("OLD", "NEW"),
                       help="rewrite every cell pointing at PID OLD to PID NEW")
    value.add_argument("--replace-vpid", type=int, nargs=2, metavar=("OLD", "NEW"),
                       help="rewrite every cell pointing at VPID OLD to VPID NEW")
    add_mutation_flags(p)
    args = p.parse_args()

    replacing = args.replace_pid or args.replace_vpid
    single = any(v is not None and v is not False for v in (args.pid, args.vpid, args.text)) or args.clear
    if not replacing and not single:
        p.error("give a value (--pid/--vpid/--text/--clear) or --replace-pid/--replace-vpid")
    if single and (args.row is None or args.column is None):
        p.error("setting one cell needs --row ID and --column REF")
    if replacing and args.row is not None:
        p.error("--replace-* rewrites every matching row; drop --row")

    token = args.access_token
    try:
        src = dt.find_source(token, args.lj, args.table_uuid)
        col = dt.resolve_column(src, args.column) if args.column else None
        rows = dt.query_all(token, src)
    except LJTableError as e:
        die(e)
    except ValueError as e:
        fail(str(e))

    if replacing:
        kind = "PID" if args.replace_pid else "VPID"
        old, new = (Pointer(kind, n) for n in replacing)
        edits = dt.replace_pointer_edits(src, rows, old, new, col["id"] if col else None)
        if not edits:
            fail(f"no cell points at {old}" + (f" in column {col['name']!r}" if col else ""))
        title = f"REPLACE {old} -> {new} in {len(edits)} cell(s)"
    else:
        if args.pid is not None or args.vpid is not None:
            if col["selector"] == TEXT_SELECTOR:
                fail(f"column {col['name']!r} is a Text column: it stores literal text and never "
                     "resolves a PID. Use --text, or pick a pointer column.")
            new_value = render_cell(Pointer("PID", args.pid) if args.pid is not None
                                    else Pointer("VPID", args.vpid))
        elif args.text is not None:
            if col["selector"] != TEXT_SELECTOR:
                fail(f"column {col['name']!r} is a {col['selector']} column: its cells hold a "
                     "PID pointer. Use --pid or --vpid.")
            new_value = args.text
        else:
            new_value = None
        edits = [(args.row, col["id"], new_value)]
        title = f"SET row {args.row} / {col['name']!r}"

    try:
        updates = dt.set_cells(src, rows, edits)
    except ValueError as e:
        fail(str(e))

    by_id = {r["rowId"]: r for r in rows}
    cols = dt.columns(src)
    print(f"{title}\nData table {src['tableName']!r} ({src['tableId']}) on LJ {src['tableLJSerial']}\n")
    for row_id, column_id, value in edits:
        c = next(x for x in cols if x["id"] == column_id)
        before = by_id[row_id]["pointers"][c["index"]]
        print(f"  row {row_id:>5}  pos {c['position']:>3}  {c['name']!r}: {before!r} -> {value!r}")
    if not updates:
        print("\nNothing to change: every cell already holds that value.")
        return
    print(f"\n{len(updates)} row(s) will be sent, each with all {len(cols)} values. The table "
          "regenerates after the write; a write during a regeneration answers 503.")
    if not should_post(args):
        return
    write_backup(args, "datatable-cells", src["tableLJSerial"], src["tableId"],
                 {"tableSource": src,
                  "rows": [{"tableRowId": u["tableRowId"], "tableRowValues": by_id[u["tableRowId"]]["pointers"]}
                           for u in updates]})
    try:
        dt.post_content(token, src, updates)
        print("POST content/update: OK")
        readback = dt.query_all(token, src)
    except LJTableError as e:
        die(e)
    problems = dt.cell_mismatches(updates, readback)
    if problems:
        fail("read-back does not match what was sent:\n  - " + "\n  - ".join(problems[:20]))
    print(f"Read-back matches for all {len(updates)} row(s).")


if __name__ == "__main__":
    main()
