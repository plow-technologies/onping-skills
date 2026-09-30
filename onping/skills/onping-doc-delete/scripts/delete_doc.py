# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete documents from the OnPing documentation site. MUTATING — requires --yes.

The target is a LIVE CUSTOMER-FACING documentation site and THERE IS NO UNDO.
Back a document up with `onping-doc-get --json` first.

THE SHARP EDGE IS `--where`. `deleteDocs` accepts `id` OR `where`, and `where` is
an arbitrary Payload filter string. The tool offers no dry run of its own, so one
malformed filter can delete the whole collection.

This script therefore requires TWO independent confirmations for a `where` delete:

    --yes                    the caller intends a mutation
    --confirm-count <n>      the caller knows HOW MANY documents match

`--yes` alone is not sufficient. `--yes` asserts intent to mutate; it does not
assert that the caller knows the filter matches nine documents rather than one.
Requiring the count turns a silent mass delete into a failed precondition. This is
stricter than the rest of the onping skill catalog, deliberately.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.docs_http import call_tool, extract_json_blocks
from _docs_routes.routes import resolve_key


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Delete documents from the OnPing documentation site (MUTATING).",
    )
    p.add_argument("--id", help="Document id to delete")
    p.add_argument(
        "--where",
        help="JSON filter string. Requires --confirm-count as well as --yes.",
    )
    p.add_argument(
        "--confirm-count",
        type=int,
        help="The number of documents the --where filter is expected to match",
    )
    p.add_argument("--depth", type=int, help="Population depth in the response")
    p.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without this, print what would be removed.",
    )
    return p.parse_args()


def find_by_where(key: str, where: str) -> list[dict]:
    """Resolve the SAME filter the delete will use, so the count is meaningful."""
    text = call_tool(
        key, "findDocs", {"where": where, "limit": 100, "depth": 0}
    )
    docs: list[dict] = []
    for block in extract_json_blocks(text):
        if isinstance(block.get("docs"), list):
            docs.extend(d for d in block["docs"] if isinstance(d, dict))
        elif "id" in block:
            docs.append(block)
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
                "\nDRY RUN — nothing was deleted. Re-run with --yes.\n"
                "There is no undo. Back it up first with:\n"
                f"  onping-doc-get --id {args.id} --json > backup-{args.id}.json"
            )
            return 0
        payload: dict = {"id": args.id}
        if args.depth is not None:
            payload["depth"] = args.depth
        print(call_tool(key, "deleteDocs", payload).rstrip())
        print(f"\nDeleted document {args.id}.")
        return 0

    # ── where path: resolve, print, and require a matching count ──
    matches = find_by_where(key, args.where)
    print(f"Filter: {args.where}")
    print(f"Matches {len(matches)} document(s):")
    for doc in matches:
        print(describe(doc))

    if not matches:
        print("\nNothing matches this filter. Nothing to delete.")
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
            "Nothing was deleted. Re-check the filter.",
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        print(
            f"\nDRY RUN — nothing was deleted. Count confirmed "
            f"({len(matches)}). Re-run with --yes to delete.\n"
            "There is no undo. Back each document up with onping-doc-get --json."
        )
        return 0

    payload = {"where": args.where}
    if args.depth is not None:
        payload["depth"] = args.depth
    print(call_tool(key, "deleteDocs", payload).rstrip())
    print(f"\nDeleted {len(matches)} document(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
