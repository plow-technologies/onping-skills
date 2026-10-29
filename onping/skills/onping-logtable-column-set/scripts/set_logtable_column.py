# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Repoint, re-select, or rename an OnPing log-table column as a new schema version. MUTATING — requires --yes.

Choose the column with --column (position, UUID, or name), --column-pid, or
--column-vpid. Then give any of --pid/--vpid (the PID it records), --selector,
and --name. The column UUID is kept. Repointing the event (trigger) column
moves the trigger too; the trigger must be a PID.

The edit goes through `POST /logtable/<LJ>/source/schema/upgrade` as version
v+1, which starts a new, EMPTY table. (The OnPing UI renames through
metadata/update without a new version; this skill always versions so every
edit is one verified path.) Without --yes nothing is posted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes.cli import (base_parser, fail, logtable_upgrade_flow, pointer_args,  # noqa: E402
                                  pointer_from, selector_arg)
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--column", metavar="POS|UUID|NAME", help="the column to change")
    pointer_args(p, prefix="column-", what="or the column keyed by")
    pointer_args(p, what="record")
    p.add_argument("--selector", type=selector_arg, help="new selector")
    p.add_argument("--name", help="new header")
    add_mutation_flags(p)
    args = p.parse_args()
    which = pointer_from(args, "column-")
    if (args.column is None) == (which is None):
        p.error("give exactly one of --column, --column-pid, --column-vpid")
    new_ptr = pointer_from(args)
    if new_ptr is None and args.selector is None and args.name is None:
        p.error("nothing to change: give --pid/--vpid, --selector, and/or --name")

    try:
        stored = lt.find_source(args.access_token, args.lj, args.table_uuid)
        col = lt.resolve_column(lt.schema(stored), args.column, which)
    except LJTableError as e:
        die(e)
    except ValueError as e:
        fail(str(e))
    changes = [f"key {col['key']} -> {new_ptr}" if new_ptr else None,
               f"selector -> {args.selector}" if args.selector else None,
               f"name -> {args.name!r}" if args.name is not None else None]
    logtable_upgrade_flow(
        args, args.access_token, stored,
        lambda sch: lt.set_column(sch, col["id"], pointer=new_ptr, selector=args.selector, name=args.name),
        title=f"SET column {col['name']!r} at position {col['position']}: "
              + ", ".join(c for c in changes if c),
        marks_for=lambda _notes: {col["id"]: "   <-- changed"})


if __name__ == "__main__":
    main()
