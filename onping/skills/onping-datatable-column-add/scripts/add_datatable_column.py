# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Add an empty column to an OnPing Lumberjack data table. MUTATING — requires --yes.

`POST /datatable/<LJ>/source/metadata/update` with the stored TableSource plus
one new column (fresh uuid4, columnHeaderNewOrDuplicate = nil UUID), which the
server turns into ALTER ADD COLUMN. Every row's cell in the new column starts
null; point cells at PIDs with onping-datatable-cell-set.

Without --yes (or with --dry-run) it prints the before/after grid and posts
nothing. With --yes it writes a backup of the pre-edit TableSource, posts,
re-reads the table, and exits non-zero if the header does not match.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes.cli import base_parser, datatable_metadata_flow, fail, selector_arg  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags, new_column_mark  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    p.add_argument("--name", required=True, help="the new column's name (must be unique)")
    p.add_argument("--selector", type=selector_arg, default="ResultTagSelector",
                   help="what each cell shows for its PID: Result (default), Text, Unit, "
                        "Description, LastUpdateDateTime, ...")
    p.add_argument("--at", type=int, metavar="POS",
                   help="stored position for the column; later columns shift up (default: last)")
    add_mutation_flags(p)
    args = p.parse_args()

    try:
        before = dt.find_source(args.access_token, args.lj, args.table_uuid)
    except LJTableError as e:
        die(e)
    try:
        after, cid = dt.add_column(before, args.name, args.selector, args.at)
    except ValueError as e:
        fail(str(e))
    datatable_metadata_flow(args, args.access_token, before, after,
                            title=f"ADD column {args.name!r} ({args.selector})",
                            marks={cid: new_column_mark(args, "new (empty)")})


if __name__ == "__main__":
    main()
