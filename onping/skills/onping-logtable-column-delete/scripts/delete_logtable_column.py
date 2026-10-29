# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Remove a column from an OnPing log table as a new schema version. MUTATING — requires --yes.

Choose the column with --column (position, UUID, or name) or by the PID/VPID
it records. The event (trigger) column cannot be removed. A stored filter on
the column blocks the delete unless --drop-filters. The edit goes through
`POST /logtable/<LJ>/source/schema/upgrade` as version v+1, which starts a new,
EMPTY table; the column's past values stay in the older versions' rows.
Without --yes nothing is posted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes.cli import (base_parser, fail, logtable_upgrade_flow, pointer_args,  # noqa: E402
                                  pointer_from)
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--column", metavar="POS|UUID|NAME", help="the column to remove")
    pointer_args(p, what="or the column keyed by")
    p.add_argument("--drop-filters", action="store_true",
                   help="also remove stored filter rules that reference the column")
    add_mutation_flags(p)
    args = p.parse_args()
    ptr = pointer_from(args)
    if (args.column is None) == (ptr is None):
        p.error("give exactly one of --column, --pid, --vpid")

    try:
        stored = lt.find_source(args.access_token, args.lj, args.table_uuid)
        col = lt.resolve_column(lt.schema(stored), args.column, ptr)
    except LJTableError as e:
        die(e)
    except ValueError as e:
        fail(str(e))
    logtable_upgrade_flow(
        args, args.access_token, stored,
        lambda sch: lt.delete_column(sch, col["id"], drop_filters=args.drop_filters),
        title=f"DELETE column {col['name']!r} at position {col['position']} ({col['key']}, {col['id']})")


if __name__ == "__main__":
    main()
