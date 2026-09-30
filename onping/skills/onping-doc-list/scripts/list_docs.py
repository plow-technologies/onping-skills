# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List documents on the OnPing documentation site. Read-only.

Wraps two MCP tools that answer the same question in different shapes:

  - `findDocs`          — full query surface (where/sort/select/page). Returns a
                          prose string with the documents embedded as JSON in a
                          fenced block.
  - `getDocsByCategory` — filter by category. Returns prose `Document ID:` lines
                          and NO JSON at all.

Two behaviors exist because the server gets them wrong:

1. `getDocsByCategory` advertises `["string","number"]` for `category` and its
   description claims it takes a "slug or ID", but the slug branch is BROKEN — a
   slug reaches an integer column unparsed and the server answers
   `Failed query: ... params: NaN`. This script resolves a non-numeric
   `--category` to its id through `findCategories` and passes the id.

2. The collection holds structurally empty drafts (documents 17 and 9 carry
   `title: null`, `slug: null`, `content: null`). Presenting those as real
   documentation pages is misleading, so they are hidden by default and the
   omitted count is always reported. `--include-empty` shows them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.docs_http import call_tool, extract_json_blocks
from _docs_routes.routes import resolve_key

_DOC_ID_RE = re.compile(r"^Document ID:\s*(\d+)\s*$", re.MULTILINE)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="List documents on the OnPing documentation site (read-only).",
    )
    p.add_argument(
        "--category",
        help="Filter by category. Accepts a numeric id or a slug; a slug is "
        "resolved to an id first, because the server's slug branch is broken.",
    )
    p.add_argument("--where", help="JSON filter string passed to findDocs")
    p.add_argument("--limit", type=int, default=10, help="Page size (server max 100)")
    p.add_argument("--page", type=int, default=1, help="Page number")
    p.add_argument("--sort", help='Sort field, e.g. "-updatedAt"')
    p.add_argument("--depth", type=int, default=0, help="Relationship population depth")
    p.add_argument("--select", help="JSON string selecting which fields to return")
    p.add_argument(
        "--draft",
        action="store_true",
        help="Query the versions table instead of the published collection",
    )
    p.add_argument(
        "--include-empty",
        action="store_true",
        help="Include structurally empty documents (null title)",
    )
    p.add_argument(
        "--trash",
        action="store_true",
        help="Show ONLY trash-marked documents (slug prefixed trash/)",
    )
    p.add_argument(
        "--no-trash",
        action="store_true",
        help="Hide trash-marked documents",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    return p.parse_args()


def resolve_category(key: str, value: str) -> int:
    """Resolve a category slug to its numeric id.

    Passing a slug straight through produces
    `Failed query: ... where "docs"."category_id" = $1  params: NaN`, so this
    lookup is mandatory rather than a convenience.
    """
    if str(value).isdigit():
        return int(value)

    text = call_tool(
        key,
        "findCategories",
        {"where": json.dumps({"slug": {"equals": value}}), "limit": 5, "depth": 0},
    )
    for block in extract_json_blocks(text):
        if block.get("slug") == value and isinstance(block.get("id"), int):
            return block["id"]
        for doc in block.get("docs", []) or []:
            if doc.get("slug") == value and isinstance(doc.get("id"), int):
                return doc["id"]

    print(
        f"Could not resolve category slug {value!r} to an id.\n"
        "The server's getDocsByCategory slug branch is broken, so a slug cannot "
        "be forwarded as a fallback. List the categories with "
        "onping-doc-category --list to find the right id.",
        file=sys.stderr,
    )
    sys.exit(1)


def is_empty(doc: dict) -> bool:
    """A structurally empty draft: no title, so nothing to show a reader."""
    return not doc.get("title")


# TRASH CONVENTION.
#
# This server has no trash folder and no way to reach one. `updateDocWithMarkdown`
# sets only title, slug, description, and content — NOT `category` — so a document
# cannot be moved to a "Trash" category through the API. And nothing can actually
# delete a document: the MCP plugin acts as the API key's related user, who holds
# role `admin`, and Docs.ts permits an admin to delete only when `data.deletedAt`
# is truthy. No field defines `deletedAt` and `trash: true` is never enabled, so
# that branch is unreachable and the delete control is hidden in the admin UI for
# every admin. A known server-side bug; an owner-role account can still delete.
#
# So discarded documents are marked instead of moved, by a convention that lives
# in the two fields we CAN set:
#
#   slug   -> prefixed `trash-`
#   title  -> prefixed `TRASH`
#
# The slug marker is `trash-` and NOT `trash/`. A slash in a slug makes the
# nested-docs plugin treat the first segment as a parent document, and a later
# update then fails with `The following field is invalid: Breadcrumbs 1 > Doc`.
# Field-verified 2026-08-26: `trash/zz-table-probe` broke the next write to that
# document, and `trash-zz-table-probe` does not.
#
# Both are visible in the admin UI's default columns (title, category, slug, ...),
# so a human can sort or eyeball them, and both are filterable here.
TRASH_SLUG_PREFIX = "trash-"
TRASH_TITLE_PREFIX = "TRASH"


def is_trash(doc: dict) -> bool:
    """True when a document carries the trash marker on its slug or title."""
    slug = doc.get("slug") or ""
    title = doc.get("title") or ""
    return slug.startswith(TRASH_SLUG_PREFIX) or title.startswith(TRASH_TITLE_PREFIX)


def main() -> int:
    args = parse_args()
    key = resolve_key()

    if args.category is not None:
        category_id = resolve_category(key, args.category)
        payload = {"category": category_id, "limit": args.limit, "page": args.page}
        if args.depth:
            payload["depth"] = args.depth
        text = call_tool(key, "getDocsByCategory", payload)

        # getDocsByCategory returns prose with no JSON, so the ids are parsed out
        # of `Document ID:` lines. There is no `title: null` filtering to do here:
        # the tool only reports documents that carry a category.
        ids = [int(m) for m in _DOC_ID_RE.findall(text)]
        if args.json:
            print(json.dumps({"source": "getDocsByCategory", "ids": ids, "text": text}, indent=2))
        else:
            print(text.rstrip())
            print(f"\n{len(ids)} document id(s) in category {category_id}: {ids}")
        return 0

    payload: dict = {"limit": args.limit, "page": args.page, "depth": args.depth}
    if args.where:
        payload["where"] = args.where
    if args.sort:
        payload["sort"] = args.sort
    if args.select:
        payload["select"] = args.select
    if args.draft:
        payload["draft"] = True

    text = call_tool(key, "findDocs", payload)
    blocks = extract_json_blocks(text)

    docs: list[dict] = []
    for block in blocks:
        if isinstance(block.get("docs"), list):
            docs.extend(d for d in block["docs"] if isinstance(d, dict))
        elif "id" in block:
            docs.append(block)

    if not docs:
        # No JSON to filter — show the server's own words rather than inventing a
        # summary, and say so.
        print(text.rstrip())
        print("\n(no JSON documents parsed from the response)", file=sys.stderr)
        return 0

    kept = docs if args.include_empty else [d for d in docs if not is_empty(d)]
    omitted = len(docs) - len(kept)

    trash_hidden = 0
    if args.trash:
        kept = [d for d in kept if is_trash(d)]
    elif args.no_trash:
        before = len(kept)
        kept = [d for d in kept if not is_trash(d)]
        trash_hidden = before - len(kept)

    if args.json:
        print(
            json.dumps(
                {
                    "docs": kept,
                    "omitted_empty": omitted,
                    "trash_hidden": trash_hidden,
                    "returned": len(docs),
                },
                indent=2,
            )
        )
    else:
        for d in kept:
            status = d.get("_status", "?")
            slug = d.get("slug") or "-"
            cat = d.get("category")
            cat_txt = cat if not isinstance(cat, dict) else cat.get("id")
            print(
                f"{d.get('id'):>4}  {status:<9} {slug:<48} "
                f"cat={cat_txt}  {d.get('title')!r}"
            )
        print(f"\n{len(kept)} document(s) shown.")
        if omitted:
            print(
                f"{omitted} structurally empty document(s) omitted "
                "(null title). Pass --include-empty to see them."
            )
        if trash_hidden:
            print(
                f"{trash_hidden} trash-marked document(s) hidden. "
                "Pass --trash to list only those."
            )
        if args.trash and not kept:
            print("No trash-marked documents. Nothing is waiting for deletion.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
