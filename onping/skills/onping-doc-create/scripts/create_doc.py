# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Create a document on the OnPing documentation site. MUTATING — requires --yes.

The target is a LIVE CUSTOMER-FACING documentation site. An operator sees a bad
setpoint; a customer reads a bad page.

`createDocs` requires `title`, `slug`, `category`, and `order`. All four are
checked locally before any request, so a missing field costs no round trip.

A created document has NO BODY — it is one of the null-content records that
`onping-doc-list` hides by default. Creating is therefore normally followed by
`onping-doc-write` to publish markdown into it, and the new id is printed so that
follow-up is possible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.docs_http import call_tool, extract_json_blocks
from _docs_routes.routes import resolve_key

REQUIRED = ("title", "slug", "category", "order")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create a document on the OnPing documentation site (MUTATING).",
    )
    p.add_argument("--title", help="The page title (required)")
    p.add_argument("--slug", help="URL-friendly identifier (required)")
    p.add_argument(
        "--category",
        help="Sidebar category: numeric id or slug (required)",
    )
    p.add_argument(
        "--order",
        type=int,
        help="Order within the category or parent (required)",
    )
    p.add_argument("--description", help="Brief description or excerpt")
    p.add_argument("--parent", type=int, help="Parent document id for nesting")
    p.add_argument(
        "--status",
        choices=("draft", "published"),
        help="Initial _status value",
    )
    p.add_argument("--draft", action="store_true", help="Create as a draft")
    p.add_argument("--depth", type=int, help="Population depth in the response")
    p.add_argument(
        "--yes",
        action="store_true",
        help="Actually create. Without this, print the call and exit.",
    )
    return p.parse_args()


def require_fields(args: argparse.Namespace) -> None:
    missing = [
        name
        for name in REQUIRED
        if getattr(args, name) is None or getattr(args, name) == ""
    ]
    if missing:
        print(
            "Missing required field(s): "
            + ", ".join(missing)
            + f"\ncreateDocs requires all of: {', '.join(REQUIRED)}.",
            file=sys.stderr,
        )
        sys.exit(1)


def resolve_category(key: str, value: str) -> int:
    """Resolve a category slug to its id, consistent with onping-doc-list."""
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
        f"Could not resolve category slug {value!r} to an id. "
        "List categories with onping-doc-category --list.",
        file=sys.stderr,
    )
    sys.exit(1)


def warn_on_slug_collision(key: str, slug: str) -> None:
    """The slug is the site's URL path, so a collision matters to a reader."""
    text = call_tool(
        key,
        "findDocs",
        {"where": json.dumps({"slug": {"equals": slug}}), "limit": 5, "depth": 0},
    )
    existing: list[dict] = []
    for block in extract_json_blocks(text):
        if isinstance(block.get("docs"), list):
            existing.extend(d for d in block["docs"] if isinstance(d, dict))
        elif block.get("slug") == slug:
            existing.append(block)

    for doc in existing:
        if doc.get("slug") == slug:
            print(
                f"WARNING: slug {slug!r} already belongs to document "
                f"{doc.get('id')} ({doc.get('title')!r}). The slug is the site's "
                "URL path.",
                file=sys.stderr,
            )
            return


def main() -> int:
    args = parse_args()
    require_fields(args)
    key = resolve_key()

    category_id = resolve_category(key, args.category)

    payload: dict = {
        "title": args.title,
        "slug": args.slug,
        "category": category_id,
        "order": args.order,
    }
    if args.description is not None:
        payload["description"] = args.description
    if args.parent is not None:
        payload["parent"] = args.parent
    if args.status:
        payload["_status"] = args.status
    if args.draft:
        payload["draft"] = True
    if args.depth is not None:
        payload["depth"] = args.depth

    warn_on_slug_collision(key, args.slug)

    if not args.yes:
        print("DRY RUN — no document was created. Would call:")
        print(f"  tool: createDocs")
        print(f"  args: {json.dumps(payload, indent=2)}")
        print("\nRe-run with --yes to create. Target is a LIVE customer-facing site.")
        return 0

    text = call_tool(key, "createDocs", payload)
    print(text.rstrip())

    new_id = None
    for block in extract_json_blocks(text):
        if isinstance(block.get("id"), int):
            new_id = block["id"]
            break

    if new_id is not None:
        print(f"\nCreated document id: {new_id}")
        print(
            "This document has NO BODY yet. Publish markdown into it with:\n"
            f"  onping-doc-write --id {new_id} --markdown <file.md> --audience <persona> --yes"
        )
    else:
        print(
            "\nCreated, but no id was parsed from the response. "
            "Find it with onping-doc-list --where "
            f"'{{\"slug\":{{\"equals\":\"{args.slug}\"}}}}'",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
