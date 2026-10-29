# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List OnPing log tables on one LJ or on every LJ you can see.

Read-only. `GET /logtable/<LJ>/source/list` (any version) or
`GET /logtable/router/source/all` (version > 0 only, so a just-created source
with no schema is missing from --all). `--references-pid N` keeps the tables
whose current schema has a column keyed by PID N, read from the listing
itself, with no extra requests.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes.cli import base_parser, dump, pointer_args, pointer_from  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0], needs_table=False)
    p.add_argument("lj", type=int, nargs="?", help="Lumberjack serial (or use --all)")
    p.add_argument("--all", action="store_true", help="every LJ you can see (version > 0 only)")
    p.add_argument("--name", action="append", default=[], metavar="TEXT",
                   help="keep tables whose name contains TEXT (case-insensitive; repeatable)")
    pointer_args(p, prefix="references-", what="keep tables with a column keyed by")
    p.add_argument("--json", action="store_true", help="print JSON records")
    args = p.parse_args()
    if (args.lj is None) == (not args.all):
        p.error("give an LJ serial or --all (not both)")

    try:
        sources = lt.list_sources(args.access_token, None if args.all else args.lj)
    except LJTableError as e:
        die(e)
    if args.name:
        sources = [s for s in sources
                   if any(n.lower() in str(s.get("logTableSourceName", "")).lower() for n in args.name)]
    sources.sort(key=lambda s: (s.get("logTableSourceLJSerial"), str(s.get("logTableSourceName"))))
    target = pointer_from(args, "references-")

    records = []
    for s in sources:
        rec = {"lj": s.get("logTableSourceLJSerial"), "uuid": s.get("logTableSourceId"),
               "name": s.get("logTableSourceName"), "version": s.get("logTableSourceSchemaVersion"),
               "group": s.get("logTableSourceGroupId"), "columns": 0, "eventPid": None}
        try:
            sch = lt.schema(s)
            cols = lt.columns(sch)
            rec["columns"] = len(cols)
            rec["eventPid"] = sch["logSchemaHeader"].get("schemaHeaderEventSource")
        except ValueError:
            cols = []
        if target is not None:
            hits = [c for c in cols if c["key"] == target]
            if not hits:
                continue
            rec["status"] = "REFERENCED"
            rec["cells"] = [{"position": c["position"], "column": c["name"], "event": c["event"]}
                            for c in hits]
        records.append(rec)

    if args.json:
        dump(records)
        return
    print(f"{'LJ':>6}  {'uuid':36}  {'ver':>3}  {'cols':>4}  {'event PID':>9}  name")
    for r in records:
        ev = "-" if r["eventPid"] is None else r["eventPid"]
        print(f"{r['lj']:>6}  {r['uuid']:36}  {r['version']:>3}  {r['columns']:>4}  {ev:>9}  {r['name']}")
        if r.get("status"):
            print("        REFERENCED " + str(target) + ": " +
                  ", ".join(f"pos {c['position']} {c['column']!r}" + (" (event)" if c["event"] else "")
                            for c in r["cells"]))
    print(f"\n{len(records)} table(s)" + (f" referencing {target}" if target else ""))
    if args.all:
        print("(--all lists only sources with a schema; a version-0 source shows on its LJ's list.)")


if __name__ == "__main__":
    main()
