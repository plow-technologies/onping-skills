# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "openpyxl"]
# ///
"""Create an OnPing log table with its columns in one step. MUTATING — requires --yes.

Two requests: `POST /logtable/<LJ>/source/create` makes a version-0 source
(it records nothing yet), then `POST /logtable/<LJ>/source/schema/upgrade`
adds schema version 1. Version 1 holds the LastUpdateDateTime event column
keyed by the trigger PID, plus every column declared with --column or read
from --from. A row is recorded each time the trigger PID updates.

  --column "NAME=SOURCE[:TAG]"   (repeatable) SOURCE is <n> (a PID) or
                                 "<n> VPID"; TAG defaults to result.
  --from FILE.xlsx               the four header rows onping-logtable-export
                                 writes; the event column comes from the file.

Columns are parsed and the schema is validated before any request. If the
upgrade fails after the create succeeded, the version-0 source is left
behind; this prints its UUID so onping-logtable-delete can remove it.
Without --yes nothing is posted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes import logtable_template as tpl  # noqa: E402
from _lj_table_routes.cli import base_parser, fail, print_logtable_grid  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die, post_json  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags, new_column_mark, should_post  # noqa: E402

DEFAULT_EVENT_NAME = "eventDateTime"


def build_parser():
    p = base_parser(__doc__.splitlines()[0], needs_table=False)
    p.add_argument("lj", type=int, help="Lumberjack serial to create the table on")
    p.add_argument("--name", required=True, help="the log table's name")
    p.add_argument("--group", help="owning group id (an owned group of yours; omit to see hints)")
    p.add_argument("--event-pid", type=int, metavar="N",
                   help="the trigger PID: a row is recorded each time it updates "
                        "(required unless --from)")
    p.add_argument("--event-name",
                   help=f"the event column's header (default {DEFAULT_EVENT_NAME}; not with --from)")
    p.add_argument("--column", action="append", default=[], metavar="NAME=SOURCE[:TAG]",
                   help="add a column (repeatable): SOURCE is <n> for a PID or '<n> VPID'; "
                        "TAG is result (default), unit, description, pid, dateTime, date, time, "
                        "writeable, company, companyId, site, siteId, location or locationId")
    p.add_argument("--from", dest="from_file", metavar="FILE.xlsx",
                   help="take the columns, event column included, from an onping-logtable-export "
                        "file; --column adds more after them")
    add_mutation_flags(p)
    return p


def plan_columns(args) -> tuple[list[tpl.ColumnSpec], list[str]]:
    """The declared columns in order, event column included, and notes for the preview."""
    notes: list[str] = []
    if args.from_file:
        header = tpl.read_header(args.from_file)
        cols = list(header.columns)
        notes += [f"--from {args.from_file}: {len(cols)} column(s)"] + header.notes
    else:
        cols = [tpl.event_spec(args.event_pid, args.event_name or DEFAULT_EVENT_NAME)]
    cols += [tpl.parse_column_spec(text) for text in args.column]
    return cols, notes


def main() -> None:
    p = build_parser()
    args = p.parse_args()
    if args.from_file and (args.event_pid is not None or args.event_name is not None):
        p.error("--from takes the event column from the file; drop --event-pid and --event-name")
    if not args.from_file and args.event_pid is None:
        p.error("--event-pid is required (or give --from FILE.xlsx)")
    token = args.access_token

    try:
        cols, notes = plan_columns(args)
        sch, cids = tpl.build_schema(cols)
    except ValueError as e:
        fail(str(e))
    event = next(c for c in cols if c.event)

    try:
        existing = lt.list_sources(token, args.lj)
    except LJTableError as e:
        die(e)
    if args.group is None:
        groups = sorted({s.get("logTableSourceGroupId") for s in existing} - {None})
        print("ERROR: --group is required.", file=sys.stderr)
        if groups:
            print(f"Groups used by log tables already on LJ {args.lj}: " + ", ".join(groups),
                  file=sys.stderr)
        else:
            print(f"No log tables on LJ {args.lj} yet; use the LJ's owning group id.", file=sys.stderr)
        sys.exit(2)
    if any(s.get("logTableSourceName") == args.name for s in existing):
        fail(f"LJ {args.lj} already has a log table named {args.name!r}")

    print(f"CREATE log table {args.name!r} on LJ {args.lj} (group {args.group})\n")
    for note in notes:
        print(f"Note: {note}")
    if notes:
        print()
    print(f"Schema version 1 ({len(cids)} column(s)):")
    mark = new_column_mark(args)
    print_logtable_grid(sch, {cid: mark for cid in cids})
    print(f"\nA row is recorded each time PID {event.pointer.value} updates.")
    if not should_post(args):
        return

    try:
        new_id = post_json(token, "logtable_create", lt.create_body(args.lj, args.name, args.group),
                           lj=args.lj)
    except LJTableError as e:
        die(e)
    if not isinstance(new_id, str):
        fail(f"source/create answered {new_id!r}, not a UUID string")
    print(f"POST source/create: OK -> {new_id} (version 0)")
    try:
        created = lt.find_source(token, args.lj, new_id)
        body = lt.first_version_body(created, sch)
        lt.post_upgrade(token, body)
        print(f"POST schema/upgrade: OK (version 1, {len(cids)} column(s))")
        readback = lt.find_source(token, args.lj, new_id)
    except (LJTableError, ValueError) as e:
        print(f"ERROR: the version-0 source {new_id} was created but version 1 was not: {e}",
              file=sys.stderr)
        print(f"Remove it with onping-logtable-delete {args.lj} {new_id}, or retry the upgrade.",
              file=sys.stderr)
        sys.exit(1)
    problems = lt.upgrade_mismatches(body, readback)
    if problems:
        fail("read-back does not match what was sent:\n  - " + "\n  - ".join(problems))
    print(f"Read-back matches ({len(cids)} column(s) at version 1). "
          f"New log table: LJ {args.lj} {new_id}")


if __name__ == "__main__":
    main()
