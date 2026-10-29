# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List OnPing Lumberjack data tables on one LJ or on every LJ you can see.

Read-only. `GET /datatable/<LJ>/source/list` or `GET /datatable/router/source/all`.
`--references-pid N` also reads each table's rows (`content/query/v3`) and
keeps the tables with a cell pointing at PID N — no OnPing route offers that
reverse lookup. A table whose rows cannot be read is reported UNCHECKED and
makes the script exit 1, so it is never mistaken for a non-match.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes.cli import base_parser, dump, pointer_args, pointer_from  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0], needs_table=False)
    p.add_argument("lj", type=int, nargs="?", help="Lumberjack serial (or use --all)")
    p.add_argument("--all", action="store_true", help="every LJ you can see")
    p.add_argument("--name", action="append", default=[], metavar="TEXT",
                   help="keep tables whose name contains TEXT (case-insensitive; repeatable)")
    pointer_args(p, prefix="references-", what="keep tables with a cell pointing at")
    p.add_argument("--json", action="store_true", help="print JSON records")
    args = p.parse_args()
    if (args.lj is None) == (not args.all):
        p.error("give an LJ serial or --all (not both)")

    try:
        sources = dt.list_sources(args.access_token, None if args.all else args.lj)
    except LJTableError as e:
        die(e)
    if args.name:
        sources = [s for s in sources
                   if any(n.lower() in str(s.get("tableName", "")).lower() for n in args.name)]
    sources.sort(key=lambda s: (s.get("tableLJSerial"), str(s.get("tableName"))))

    target = pointer_from(args, "references-")
    records, unchecked = [], 0
    for s in sources:
        rec = {"lj": s.get("tableLJSerial"), "uuid": s.get("tableId"), "name": s.get("tableName"),
               "columns": len(dt.columns(s)), "group": s.get("tableGroupId")}
        if target is not None:
            try:
                hits = dt.cells_pointing_at(s, dt.query_all(args.access_token, s), target)
            except LJTableError as e:
                rec["status"], rec["error"] = "UNCHECKED", str(e)
                unchecked += 1
                records.append(rec)
                continue
            if not hits:
                continue
            rec["status"] = "REFERENCED"
            rec["cells"] = [{"rowId": h["rowId"], "position": h["position"], "column": h["name"]}
                            for h in hits]
        records.append(rec)

    if args.json:
        dump(records)
    else:
        print(f"{'LJ':>6}  {'uuid':36}  {'cols':>4}  {'group':25}  name")
        for r in records:
            print(f"{r['lj']:>6}  {r['uuid']:36}  {r['columns']:>4}  {r['group']:25}  {r['name']}")
            if r.get("status") == "REFERENCED":
                cells = ", ".join(f"row {c['rowId']} / {c['column']!r}" for c in r["cells"][:20])
                more = f" (+{len(r['cells']) - 20} more)" if len(r["cells"]) > 20 else ""
                print(f"        REFERENCED {target}: {cells}{more}")
            elif r.get("status") == "UNCHECKED":
                print(f"        UNCHECKED: {r['error']}")
        print(f"\n{len(records)} table(s)" + (f" referencing {target}" if target else ""))
    if unchecked:
        print(f"{unchecked} table(s) UNCHECKED — the answer is incomplete.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
