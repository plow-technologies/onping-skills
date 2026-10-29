# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete a column from an OnPing Lumberjack data table, DESTROYING its data. MUTATING — requires --yes.

`POST /datatable/<LJ>/source/metadata/update` with the stored TableSource minus
the column, which the server turns into DROP COLUMN. Every row's cell in that
column is gone. The backup JSON holds the TableSource and every row's pointer
cells; the preview counts the cells that will be lost.

The column is also removed from positions (re-packed), order, hidden, custom
widths, and the frozen column. A stored filter on the column blocks the delete
unless --drop-filters.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes.cli import base_parser, datatable_metadata_flow, fail  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--column", required=True, metavar="POS|UUID|NAME", help="the column to delete")
    p.add_argument("--drop-filters", action="store_true",
                   help="also remove stored filter rules that reference the column")
    add_mutation_flags(p)
    args = p.parse_args()

    try:
        before = dt.find_source(args.access_token, args.lj, args.table_uuid)
        col = dt.resolve_column(before, args.column)
    except LJTableError as e:
        die(e)
    except ValueError as e:
        fail(str(e))
    try:
        after = dt.delete_column(before, col["id"], drop_filters=args.drop_filters)
    except ValueError as e:
        fail(str(e))
    try:
        rows = dt.query_all(args.access_token, before)
    except LJTableError as e:
        die(e)
    filled = [r["rowId"] for r in rows
              if col["index"] is not None and r["pointers"][col["index"]] is not None]
    sample = ", ".join(map(str, filled[:15])) + (" ..." if len(filled) > 15 else "")
    datatable_metadata_flow(
        args, args.access_token, before, after,
        title=f"DELETE column {col['name']!r} at position {col['position']} ({col['id']})",
        warning=(f"DATA LOSS: {len(filled)} of {len(rows)} row(s) have a cell in this column"
                 + (f" (rows {sample})" if filled else "")
                 + ". DROP COLUMN destroys them. The backup holds the TableSource and every "
                   "row's pointer cells, so the column can be re-added and refilled by hand."),
        backup_state={"tableSource": before,
                      "rows": [{"tableRowId": r["rowId"], "pointers": r["pointers"]} for r in rows]})


if __name__ == "__main__":
    main()
