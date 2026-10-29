# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete an OnPing log table (soft delete). MUTATING — requires --yes.

`POST /logtable/<LJ>/source/delete` with the UUID as a JSON string. The
server sets logTableSourceDeleted, so the table leaves source/list and stops
recording; there is no undelete route. The backup JSON holds the full
LogTableSource (every schema version), enough to re-create it with
onping-logtable-create plus column edits. Without --yes nothing is posted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes.cli import base_parser, fail, print_logtable_grid  # noqa: E402
from _lj_table_routes.lj_http import LJTableError, die, post_json  # noqa: E402
from _lj_table_routes.mutate import add_mutation_flags, should_post, write_backup  # noqa: E402


def main() -> None:
    p = base_parser(__doc__.splitlines()[0])
    add_mutation_flags(p)
    args = p.parse_args()
    token = args.access_token

    try:
        src = lt.find_source(token, args.lj, args.table_uuid)
        rows, count, _ = lt.query_rows(token, src, limit=1) if src.get("logTableSourceSchemas") else ([], 0, [])
    except LJTableError as e:
        die(e)
    except ValueError as e:
        fail(str(e))
    print(f"DELETE log table {src['logTableSourceName']!r} ({src['logTableSourceId']}) "
          f"on LJ {src['logTableSourceLJSerial']}")
    print(f"  versions: {lt.versions(src)}; current version holds {count} row(s)")
    if src.get("logTableSourceSchemas"):
        print()
        print_logtable_grid(lt.schema(src))
    print("\nThe table stops recording and leaves the list. There is no undelete route.")
    if not should_post(args):
        return
    write_backup(args, "logtable", src["logTableSourceLJSerial"], src["logTableSourceId"], src)
    try:
        post_json(token, "logtable_delete", src["logTableSourceId"], lj=src["logTableSourceLJSerial"])
        print("POST source/delete: OK")
        remaining = lt.list_sources(token, src["logTableSourceLJSerial"])
    except LJTableError as e:
        die(e)
    if any(str(s.get("logTableSourceId")).lower() == src["logTableSourceId"].lower() for s in remaining):
        fail("the table is still listed after the delete")
    print("Verified: the table no longer appears in source/list.")


if __name__ == "__main__":
    main()
