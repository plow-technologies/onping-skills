# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""List the save history of an OnPing custom-table widget from the audit database.

OnPing writes a FULL SNAPSHOT of a custom table on every save into
`custom_table_widget_audit`. `POST /log/audit2/query` cannot read any of them —
`CustomTableWidget` derives `NoIndex` so it never reaches Elasticsearch, and
`auditGet` has no branch for it. Postgres is the only path, so this skill goes
over SSH rather than over HTTP.

Read-only: SELECT statements only, no `--yes` gate.

The column that matters most is `length(cells)`. A save that replaces a table
rather than editing it shows up as a step change in that number, and that is
exactly how the 2026-08-25 incident was identified: 655,787 bytes became 2,462,311
in one save. Rows whose cells length moves by more than 2x are flagged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _audit_db.audit_db import (
    add_common_args,
    query_rows,
    resolve_pg,
    table_exists,
)
from _audit_db.ids import parse_mongo_id

TABLE = "custom_table_widget_audit"
OVERWRITE_FACTOR = 2.0


def main() -> None:
    p = argparse.ArgumentParser(
        description="List a custom-table widget's saves from the OnPing audit "
        "database. Read-only.",
    )
    add_common_args(p)
    p.add_argument("ctable_id", help="custom table id (o-prefixed, or bare 24-hex)")
    p.add_argument("--limit", type=int, default=25, help="rows to show (default 25)")
    p.add_argument("--all", action="store_true", help="show every version")
    p.add_argument("--tsv", action="store_true", help="tab-separated output")
    args = p.parse_args()

    try:
        audit_id, given_form = parse_mongo_id(args.ctable_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    target = resolve_pg(args.audit_host, verbose=not args.quiet_resolve)
    if not args.quiet_resolve:
        print(
            f"id {args.ctable_id} read as {given_form}; querying original_id="
            f"'{audit_id}'",
            file=sys.stderr,
        )

    if not table_exists(target, TABLE):
        print(f"table {TABLE} is absent from {target.dbname}.", file=sys.stderr)
        sys.exit(1)

    total_rows = query_rows(
        target,
        f"SELECT count(*) FROM {TABLE} WHERE original_id = '{audit_id}'",
    )
    total = int(total_rows[0][0]) if total_rows and total_rows[0] else 0
    if total == 0:
        print(
            f"No audit rows for original_id='{audit_id}'.\n"
            "  A wrong id form returns zero rows rather than an error — this "
            f"query used the {given_form} interpretation.",
            file=sys.stderr,
        )
        sys.exit(1)

    limit_sql = "" if args.all else f" LIMIT {int(args.limit)}"
    rows = query_rows(
        target,
        "SELECT id<SEP>edited_on<SEP>edited_by<SEP>audit_action<SEP>"
        "length(cells)<SEP>length(headers) "
        # length(), not array_length(): `headers` is character varying, not an
        # array, and array_length() errors out on it.
        f"FROM {TABLE} WHERE original_id = '{audit_id}' "
        f"ORDER BY edited_on DESC{limit_sql}",
    )

    header = ("audit_id", "edited_on", "edited_by", "action", "cells_len", "hdrs_len")
    if args.tsv:
        print("\t".join(header))
    else:
        print(
            f"{'audit_id':>8}  {'edited_on':<32} {'edited_by':<34} "
            f"{'action':<8} {'cells_len':>10} {'hdrs':>6}"
        )

    # Rows arrive newest-first; a step change is judged against the NEXT row,
    # which is the older one.
    flagged = []
    for i, r in enumerate(rows):
        if len(r) < 6:
            continue
        audit_row_id, edited_on, edited_by, action, cells_len, hdrs_len = r[:6]
        mark = ""
        if i + 1 < len(rows) and len(rows[i + 1]) >= 5:
            try:
                now_len, prev_len = int(cells_len), int(rows[i + 1][4])
                if prev_len > 0 and (
                    now_len / prev_len >= OVERWRITE_FACTOR
                    or prev_len / max(now_len, 1) >= OVERWRITE_FACTOR
                ):
                    mark = "  <== SIZE STEP"
                    flagged.append((audit_row_id, prev_len, now_len))
            except (TypeError, ValueError):
                pass
        if args.tsv:
            print("\t".join([audit_row_id, edited_on, edited_by, action, cells_len, hdrs_len]))
        else:
            print(
                f"{audit_row_id:>8}  {edited_on:<32} {edited_by:<34} "
                f"{action:<8} {cells_len:>10} {hdrs_len:>6}{mark}"
            )

    print("", file=sys.stderr)
    print(f"showed {len(rows)} of {total} version(s)", file=sys.stderr)
    if not args.all and total > len(rows):
        print(
            f"  output is TRUNCATED — pass --all to see all {total} versions",
            file=sys.stderr,
        )
    for audit_row_id, prev_len, now_len in flagged:
        print(
            f"  advisory: audit row {audit_row_id} changed cells from {prev_len} to "
            f"{now_len} bytes. A step of this size is the signature of a wholesale "
            "overwrite rather than an edit.",
            file=sys.stderr,
        )
    if flagged:
        print(
            "  advisory only — exit code is unaffected. Inspect a candidate with "
            "onping-ctable-audit-export.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
