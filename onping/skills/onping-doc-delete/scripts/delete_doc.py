# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Move documents to the trash on the OnPing documentation site. MUTATING — requires --yes.

The target is a LIVE CUSTOMER-FACING documentation site. The server offers only a
SOFT delete over MCP: `moveToTrash` sets `deletedAt`, which hides the page from the
site and from search. A human restores it from the Payload admin panel. A permanent
delete is owner-only and admin-UI-only; no MCP tool can do it, and no MCP tool can
restore a trashed page either. Back a document up with `onping-doc-get --json` first.

`moveToTrash` takes ONE id. There is no `where` on the server side, so a `--where`
run here resolves the filter with `findDocs` and then trashes each resolved id in
turn. That still makes `--where` the sharp edge — one broad filter trashes many
customer-facing pages — so it needs TWO independent confirmations:

    --yes                    the caller intends a mutation
    --confirm-count <n>      the caller knows HOW MANY documents match

`--yes` alone is not sufficient. `--yes` asserts intent to mutate; it does not
assert that the caller knows the filter matches nine documents rather than one.
Requiring the count turns a silent mass trash into a failed precondition. This is
stricter than the rest of the onping skill catalog, deliberately.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.docs_http import call_tool, extract_json_blocks, prose_total, refuse_if_truncated
from _docs_routes.routes import resolve_key


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Move documents to the trash on the OnPing documentation site (MUTATING).",
    )
    p.add_argument("--id", help="Document id to move to the trash")
    p.add_argument(
        "--where",
        help="JSON filter string. Requires --confirm-count as well as --yes.",
    )
    p.add_argument(
        "--confirm-count",
        type=int,
        help="The number of documents the --where filter is expected to match",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Actually move to the trash. Without this, print what would be trashed.",
    )
    return p.parse_args()


FIND_LIMIT = 100  # the server's per-call maximum


def find_by_where(key: str, where: str) -> list[dict]:
    """Resolve the filter to the concrete ids that will be trashed.

    Refuses when the filter matches more than one page: the per-id loop would
    trash only the resolved page and leave the rest live.
    """
    text = call_tool(
        key, "findDocs", {"where": where, "limit": FIND_LIMIT, "depth": 0}
    )
    docs: list[dict] = []
    for block in extract_json_blocks(text):
        if isinstance(block.get("docs"), list):
            docs.extend(d for d in block["docs"] if isinstance(d, dict))
        elif "id" in block:
            docs.append(block)
    refuse_if_truncated(len(docs), prose_total(text), FIND_LIMIT, "document(s)")
    return docs


def find_by_id(key: str, doc_id: str) -> dict:
    text = call_tool(key, "findDocs", {"id": doc_id, "depth": 0})
    for block in extract_json_blocks(text):
        if "id" in block or "title" in block:
            return block
    print(f"Could not resolve document {doc_id}.", file=sys.stderr)
    sys.exit(1)


def describe(doc: dict) -> str:
    return (
        f"  id={doc.get('id')}  status={doc.get('_status')}  "
        f"slug={doc.get('slug')!r}  title={doc.get('title')!r}"
    )


def move_to_trash(key: str, doc_id) -> None:
    """Trash one document. `call_tool` exits non-zero if the server refuses."""
    print(call_tool(key, "moveToTrash", {"collection": "docs", "id": doc_id}).rstrip())


RESTORE_NOTE = (
    "A human restores a trashed page from the admin panel; no MCP tool can.\n"
    "Back it up first with onping-doc-get --json."
)


def main() -> int:
    args = parse_args()

    if not args.id and not args.where:
        print(
            "Refusing to run: pass --id or --where.\n"
            "A delete with no selector is never what you meant.",
            file=sys.stderr,
        )
        return 1
    if args.id and args.where:
        print("Pass --id or --where, not both.", file=sys.stderr)
        return 1

    key = resolve_key()

    # ── single-id path ──
    if args.id:
        doc = find_by_id(key, args.id)
        print("Target document:")
        print(describe(doc))
        if not args.yes:
            print(
                "\nDRY RUN — nothing was trashed. Re-run with --yes.\n"
                f"{RESTORE_NOTE}\n"
                f"  onping-doc-get --id {args.id} --json > backup-{args.id}.json"
            )
            return 0
        move_to_trash(key, args.id)
        print(f"\nMoved document {args.id} to the trash.")
        return 0

    # ── where path: resolve, print, and require a matching count ──
    matches = find_by_where(key, args.where)
    print(f"Filter: {args.where}")
    print(f"Matches {len(matches)} document(s):")
    for doc in matches:
        print(describe(doc))

    if not matches:
        print("\nNothing matches this filter. Nothing to trash.")
        return 0

    if args.confirm_count is None:
        print(
            f"\nRefusing to run: a --where delete needs --confirm-count.\n"
            f"This filter matches {len(matches)} document(s). If that is what you "
            f"intend, re-run with:\n"
            f"  --confirm-count {len(matches)} --yes\n"
            "--yes alone says you meant to mutate; it does not say you know how "
            "many documents match.",
            file=sys.stderr,
        )
        return 1

    if args.confirm_count != len(matches):
        print(
            f"\nRefusing to run: count mismatch.\n"
            f"  --confirm-count says: {args.confirm_count}\n"
            f"  the filter matches:   {len(matches)}\n"
            "Nothing was trashed. Re-check the filter.",
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        print(
            f"\nDRY RUN — nothing was trashed. Count confirmed "
            f"({len(matches)}). Re-run with --yes to move them to the trash.\n"
            f"{RESTORE_NOTE}"
        )
        return 0

    # One call per id. If one fails, call_tool exits non-zero and the ids printed
    # above it are already in the trash; the rest are untouched.
    for i, doc in enumerate(matches, 1):
        print(f"[{i}/{len(matches)}] ", end="")
        move_to_trash(key, doc.get("id"))
    print(f"\nMoved {len(matches)} document(s) to the trash.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
