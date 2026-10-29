# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read one OnPing Lumberjack data table's TableSource: its column grid, or the raw JSON.

Read-only. There is no get-one route, so this filters
`GET /datatable/<LJ>/source/list` by UUID. The default view is the column grid
(position, UUID, selector, hidden, name) plus the stored filters, order, and
pagination. `--json` prints the raw TableSource, which the column-edit skills
send back.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes import filters  # noqa: E402
from _lj_table_routes.cli import base_parser, dump, print_datatable_grid  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--json", action="store_true", help="print the raw TableSource JSON")
    p.add_argument("--output", metavar="PATH", help="write the raw JSON to PATH")
    args = p.parse_args()

    try:
        src = dt.find_source(args.access_token, args.lj, args.table_uuid)
    except LJTableError as e:
        die(e)
    if args.json or args.output:
        dump(src, args.output)
        return

    h = src.get("tableHeader") or {}
    names = {c["id"].lower(): c["name"] for c in dt.columns(src)}
    print(f"Data table {src['tableName']!r}")
    print(f"  uuid:  {src['tableId']}")
    print(f"  LJ:    {src['tableLJSerial']}")
    print(f"  group: {src['tableGroupId']}")
    pag = src.get("tablePagination")
    print(f"  pagination: {pag['tablePaginationLimit']} rows/page" if pag else "  pagination: none")
    order = h.get("tableHeaderColumnsOrder") or {}
    if order:
        print("  order: " + ", ".join(f"{names.get(k.lower(), k)} {v.removeprefix('ColumnOrder')}"
                                      for k, v in order.items()))
    rules = h.get("tableHeaderFilters") or []
    if rules:
        refs = sorted(names.get(r, r) for r in filters.column_refs(rules))
        print(f"  filters: {len(rules)} rule(s) on {refs} — the UI hides rows they exclude")
    print()
    print_datatable_grid(src)
    print(f"\n{len(dt.columns(src))} column(s). A column holds only a selector; the PID is in "
          "each row's cell (see onping-datatable-fetch).")


if __name__ == "__main__":
    main()
