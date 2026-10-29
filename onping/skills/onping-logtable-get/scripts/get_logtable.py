# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read one OnPing log table's LogTableSource: a schema's column grid, or the raw JSON.

Read-only. There is no get-one route, so this filters
`GET /logtable/<LJ>/source/list` by UUID. The default view is the current
schema's column grid (position, UUID, key, selector, event marker, hidden,
name). `--version N` reads a historical schema. Schemas are selected by
logSchemaVersion, never by list index (the list is newest first).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes.cli import base_parser, dump, fail, print_logtable_grid  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--version", type=int, metavar="N", help="read schema version N (default: current)")
    p.add_argument("--json", action="store_true",
                   help="print the raw LogTableSource (with --version: that schema only)")
    p.add_argument("--output", metavar="PATH", help="write the JSON to PATH")
    args = p.parse_args()

    try:
        src = lt.find_source(args.access_token, args.lj, args.table_uuid)
    except LJTableError as e:
        die(e)
    if (args.json or args.output) and args.version is None:
        dump(src, args.output)
        return
    try:
        sch = lt.schema(src, args.version)
    except ValueError as e:
        if args.version is None and not src.get("logTableSourceSchemas"):
            print(f"Log table {src['logTableSourceName']!r} ({src['logTableSourceId']}) has no "
                  "schema yet (version 0). It records nothing until a version-1 upgrade.")
            return
        fail(str(e))
    if args.json or args.output:
        dump(sch, args.output)
        return

    h = sch["logSchemaHeader"]
    current = src["logTableSourceSchemaVersion"]
    print(f"Log table {src['logTableSourceName']!r}")
    print(f"  uuid:     {src['logTableSourceId']}")
    print(f"  LJ:       {src['logTableSourceLJSerial']}")
    print(f"  group:    {src['logTableSourceGroupId']}")
    print(f"  versions: {lt.versions(src)} (current {current})")
    print(f"  showing:  version {sch['logSchemaVersion']}"
          + ("" if sch["logSchemaVersion"] == current else "  (historical — new rows go to the current version)"))
    print(f"  event:    PID {h.get('schemaHeaderEventSource')} — a row is recorded when it updates")
    if src.get("logTableSourceRequiresRestore"):
        print("  ⚠️  requiresRestore is set")
    errors = lt.validate_schema(sch)
    if errors:
        print("  ⚠️  schema problems: " + "; ".join(errors))
    print()
    print_logtable_grid(sch)
    print(f"\n{len(lt.columns(sch))} column(s); * marks the event (trigger) column.")


if __name__ == "__main__":
    main()
