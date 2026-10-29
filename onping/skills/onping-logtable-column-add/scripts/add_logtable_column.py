# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Add a column to an OnPing log table as a new schema version. MUTATING — requires --yes.

A log-table column is keyed by the PID (or VPID) it records, with a selector
(Result by default). The edit goes through
`POST /logtable/<LJ>/source/schema/upgrade` as version v+1, which starts a new,
EMPTY table; rows under older versions stay readable with
onping-logtable-fetch --version. Without --yes nothing is posted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes.cli import (base_parser, fail, logtable_upgrade_flow, pointer_args,  # noqa: E402
                                  pointer_from, selector_arg)
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags, new_column_mark  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    pointer_args(p, what="record")
    p.add_argument("--name", required=True, help="the new column's header")
    p.add_argument("--selector", type=selector_arg, default="ResultTagSelector",
                   help="what to record from the PID (default Result)")
    p.add_argument("--at", type=int, metavar="POS", help="insert at position POS (default: last)")
    add_mutation_flags(p)
    args = p.parse_args()
    ptr = pointer_from(args)
    if ptr is None:
        p.error("give --pid N or --vpid N")

    try:
        stored = lt.find_source(args.access_token, args.lj, args.table_uuid)
    except LJTableError as e:
        die(e)
    except ValueError as e:
        fail(str(e))
    logtable_upgrade_flow(
        args, args.access_token, stored,
        lambda sch: lt.add_column(sch, ptr, args.name, args.selector, args.at),
        title=f"ADD column {args.name!r} ({ptr}, {args.selector})",
        marks_for=lambda cid: {cid: new_column_mark(args)})


if __name__ == "__main__":
    main()
