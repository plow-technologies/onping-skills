# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read an OnPing log table's recorded rows, newest first, and say whether it is recording.

Read-only. `POST /logtable/<LJ>/source/content/query/v2` with one schema
version, ordered by the event column descending. Prints the row count and the
newest event time (UTC), which answers "is it still recording?".

--since / --until filter on the event column, inclusive, at minute precision
(the server compares strftime('%Y-%m-%d %H:%M', ...)). Each schema version has
its own rows: after a column edit, read older rows with --version.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes.cli import base_parser, dump, fail  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402


def _age(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        t = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return ""
    secs = int((_dt.datetime.now(_dt.timezone.utc) - t).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f" ({secs // size}{unit} ago)"
    return f" ({secs}s ago)"


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--limit", type=int, default=10, help="rows to return (default 10)")
    p.add_argument("--offset", type=int, default=0, help="skip this many newest rows")
    p.add_argument("--since", metavar="UTC", help="only rows at or after YYYY-MM-DD[ HH:MM]")
    p.add_argument("--until", metavar="UTC", help="only rows at or before YYYY-MM-DD[ HH:MM]")
    p.add_argument("--version", type=int, metavar="N", help="read schema version N (default: current)")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args()

    try:
        src = lt.find_source(args.access_token, args.lj, args.table_uuid)
        rows, count, cols = lt.query_rows(args.access_token, src, version=args.version,
                                          limit=args.limit, offset=args.offset,
                                          since=args.since, until=args.until)
    except LJTableError as e:
        die(e)
    except ValueError as e:
        fail(str(e))

    version = args.version if args.version is not None else src["logTableSourceSchemaVersion"]
    ev = next(c for c in cols if c["event"])
    ev_label = next(iter(rows[0]["values"])) if rows else ev["name"]
    newest = rows[0]["values"].get(ev_label) if rows and args.offset == 0 else None
    if args.json:
        dump({"lj": src["logTableSourceLJSerial"], "table": src["logTableSourceId"],
              "version": version, "count": count, "newestEvent": newest,
              "columns": [{"position": c["position"], "id": c["id"], "name": c["name"],
                           "key": str(c["key"]), "selector": c["selector"], "event": c["event"]}
                          for c in cols],
              "rows": rows})
        return
    print(f"Log table {src['logTableSourceName']!r} (LJ {src['logTableSourceLJSerial']}), "
          f"schema version {version}")
    print(f"  rows matching: {count}")
    if args.offset == 0:
        print(f"  newest event:  {newest or '— none recorded —'}{_age(newest)} UTC")
    if version != src["logTableSourceSchemaVersion"]:
        print("  (historical version: new rows go to version "
              f"{src['logTableSourceSchemaVersion']})")
    print()
    for r in rows:
        print(f"row {r['rowId']}: " + "; ".join(f"{k}: {v!r}" for k, v in r["values"].items()))
    if not rows:
        print("No rows. A new schema version starts empty; older rows are under --version.")


if __name__ == "__main__":
    main()
