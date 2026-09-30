# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Recover prior state for ANY audited OnPing model from the audit database.

WHY THIS EXISTS

The audit write path is generic and the read path is not. `auditInsert` folds over
every audited model, so every save lands in `<model>_audit` as a full snapshot. But
`auditGet` dispatches over a hand-maintained `AuditType` case list, and many models
derive `NoIndex` so they never reach Elasticsearch either. For those models
`POST /log/audit2/query` returns nothing at all — not an error, just an empty
result that reads like "no history exists".

A generic writer paired with an enumerated reader drifts. Custom tables were the
instance that prompted this skill; they are not the only one. For the models the
API DOES cover, prefer `onping-audit-pull` — it is a supported route, it is
permission-scoped, and it needs no SSH.

Read-only: SELECT statements only, no `--yes` gate.

WHAT THIS DELIBERATELY DOES NOT DO

It does not decode any model's domain-specific column encodings. Those differ per
model — an S-prefix on some text columns, hex-of-ASCII on id columns, Haskell
`Show`/`Read` on others, plain JSON elsewhere — and a generic decoder would
silently corrupt values rather than fail. Columns come out as stored, and decoding
is the caller's job. `onping-ctable-audit-export` is the worked example of what
that looks like for one model.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _audit_db.audit_db import (
    add_common_args,
    list_audit_tables,
    query_json,
    query_rows,
    resolve_pg,
    table_exists,
)
from _audit_db.ids import parse_mongo_id

# Columns present on every audit table (the AuditModel envelope).
ENVELOPE_COLUMNS = ("id", "original_id", "audit_action", "edited_by", "edited_on")


def die(msg: str, *, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def columns_of(target, table: str) -> list[tuple[str, str]]:
    rows = query_rows(
        target,
        "SELECT column_name<SEP>data_type FROM information_schema.columns "
        f"WHERE table_schema='public' AND table_name='{table}' "
        "ORDER BY ordinal_position",
    )
    return [(r[0], r[1]) for r in rows if len(r) >= 2]


def cmd_list_tables(target) -> None:
    tables = list_audit_tables(target)
    if not tables:
        die("no audit tables found — check the database name")
    print(f"{'table':<52} {'rows':>12}")
    for t in tables:
        rows = query_rows(target, f"SELECT count(*) FROM {t}")
        count = rows[0][0] if rows and rows[0] else "?"
        print(f"{t:<52} {count:>12}")
    print(f"\n{len(tables)} audit table(s)", file=sys.stderr)
    print(
        "  For models POST /log/audit2/query already covers, prefer "
        "onping-audit-pull.",
        file=sys.stderr,
    )


def resolve_table(target, table: str) -> str:
    if table_exists(target, table):
        return table
    candidates = list_audit_tables(target)
    close = difflib.get_close_matches(table, candidates, n=3, cutoff=0.5)
    hint = f"\n  Did you mean: {', '.join(close)}" if close else ""
    die(
        f"table {table!r} is absent from {target.dbname}.{hint}\n"
        "  Run with --list-tables to see every audit table."
    )


def cmd_list_versions(target, table: str, raw_id: str, limit: int, show_all: bool) -> None:
    try:
        audit_id, given_form = parse_mongo_id(raw_id)
    except ValueError as exc:
        die(str(exc), code=2)
    print(f"id {raw_id} read as {given_form}; querying original_id='{audit_id}'", file=sys.stderr)

    cols = columns_of(target, table)
    names = [c for c, _ in cols]
    if "original_id" not in names:
        die(f"{table} has no original_id column — it is not a per-record audit table")

    # Byte lengths for the large columns, since a step change in one of them is the
    # signature of a wholesale overwrite rather than an edit.
    large = [
        c for c, dt in cols
        if dt in ("text", "character varying", "bytea") and c not in ENVELOPE_COLUMNS
    ][:4]

    total_rows = query_rows(target, f"SELECT count(*) FROM {table} WHERE original_id = '{audit_id}'")
    total = int(total_rows[0][0]) if total_rows and total_rows[0] else 0
    if total == 0:
        die(
            f"no audit rows for original_id='{audit_id}' in {table}.\n"
            f"  A wrong id form returns zero rows rather than an error — this query "
            f"used the {given_form} interpretation."
        )

    length_exprs = "".join(f"<SEP>length({c})" for c in large)
    limit_sql = "" if show_all else f" LIMIT {int(limit)}"
    rows = query_rows(
        target,
        "SELECT id<SEP>edited_on<SEP>edited_by<SEP>audit_action" + length_exprs +
        f" FROM {table} WHERE original_id = '{audit_id}' ORDER BY edited_on DESC{limit_sql}",
    )

    header = ["audit_id", "edited_on", "edited_by", "action"] + [f"len({c})" for c in large]
    print("\t".join(header))
    for r in rows:
        print("\t".join(r))
    print(f"\nshowed {len(rows)} of {total} version(s)", file=sys.stderr)
    if not show_all and total > len(rows):
        print(f"  output is TRUNCATED — pass --all for all {total}", file=sys.stderr)
    print(
        "  A Delete row carries recoverable content: the delete path reads the "
        "document before removing it.",
        file=sys.stderr,
    )


def cmd_dump_row(target, table: str, row_id: int, output: str | None, indent: int | None) -> None:
    cols = columns_of(target, table)
    if not cols:
        die(f"could not read the columns of {table}")
    exists = query_rows(target, f"SELECT 1 FROM {table} WHERE id = {row_id}")
    if not exists:
        die(f"no row with id {row_id} in {table}")

    pairs = ", ".join(f"'{c}', \"{c}\"" for c, _ in cols)
    row = query_json(target, f"json_build_object({pairs})", f"FROM {table} WHERE id = {row_id}")
    if row is None:
        die(f"row {row_id} came back empty")

    text = json.dumps(row, indent=indent, separators=None if indent else (",", ":"), sort_keys=True)
    if output:
        Path(output).write_text(text)
        print(f"wrote {output} ({len(text.encode())} bytes)", file=sys.stderr)
    else:
        print(text)
    print(
        "\nNOTE: columns are emitted AS STORED. No domain decoding was applied.\n"
        "  Audit columns use several encodings — an 's' text prefix, hex-of-ASCII "
        "ids, Haskell Show/Read, and plain JSON — and which applies is per model.\n"
        "  Decoding is the caller's job. See onping-ctable-audit-export for a "
        "worked example.",
        file=sys.stderr,
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Recover prior state for any audited OnPing model from the "
        "audit database. Read-only.",
    )
    add_common_args(p)
    p.add_argument("--list-tables", action="store_true", help="enumerate audit tables with row counts")
    p.add_argument("--table", help="the <model>_audit table to work with")
    p.add_argument("--original-id", help="the record's mongo id (o-prefixed or bare 24-hex)")
    p.add_argument("--dump-row", type=int, metavar="AUDIT_ID", help="emit one audit row as JSON")
    p.add_argument("--limit", type=int, default=25, help="versions to show (default 25)")
    p.add_argument("--all", action="store_true", help="show every version")
    p.add_argument("--output", help="write --dump-row output here")
    p.add_argument("--indent", type=int, default=None, help="pretty-print with this indent")
    args = p.parse_args()

    if not (args.list_tables or args.dump_row or (args.table and args.original_id)):
        die(
            "nothing to do. Pass one of:\n"
            "  --list-tables\n"
            "  --table <t> --original-id <id>\n"
            "  --table <t> --dump-row <audit_id>",
            code=2,
        )

    target = resolve_pg(args.audit_host, verbose=not args.quiet_resolve)

    if args.list_tables:
        cmd_list_tables(target)
        return
    if not args.table:
        die("--table is required with --original-id or --dump-row", code=2)
    table = resolve_table(target, args.table)
    if args.dump_row:
        cmd_dump_row(target, table, args.dump_row, args.output, args.indent)
    else:
        cmd_list_versions(target, table, args.original_id, args.limit, args.all)


if __name__ == "__main__":
    main()
