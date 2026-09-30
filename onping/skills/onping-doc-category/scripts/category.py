# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Manage sidebar categories on the OnPing documentation site.

All four `*Categories` tools in one skill, because a category is a small record
(title, slug, description, icon, order) behind four routes.

  --list                     read-only, no --yes
  --create                   MUTATING
  --update (--id | --where)  MUTATING
  --delete (--id | --where)  MUTATING

A CATEGORY IS A SIDEBAR TAB the customer sees, so its `order` controls live
navigation, and deleting one orphans every document pointing at it — the dry run
reports that count first.

`icon` is a media id. The API key grants NO media access, so an icon can only be
set by referencing an id that already exists; uploading one is impossible here.

The `--where` guard matches onping-doc-delete: a bulk update or delete needs both
`--yes` and a `--confirm-count` equal to the resolved match count.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.docs_http import call_tool, extract_json_blocks
from _docs_routes.routes import resolve_key

CREATE_REQUIRED = ("title", "slug", "order")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Manage sidebar categories on the OnPing documentation site.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="List categories (read-only)")
    mode.add_argument("--create", action="store_true", help="Create a category")
    mode.add_argument("--update", action="store_true", help="Update a category")
    mode.add_argument("--delete", action="store_true", help="Delete a category")

    p.add_argument("--id", help="Category id, for --update or --delete")
    p.add_argument("--where", help="JSON filter, for --update or --delete")
    p.add_argument(
        "--confirm-count",
        type=int,
        help="Expected match count, required with --where on a mutation",
    )

    p.add_argument("--title", help="Display title")
    p.add_argument("--slug", help="URL-friendly identifier")
    p.add_argument("--description", help="Brief description")
    p.add_argument(
        "--icon",
        type=int,
        help="Media id for the icon. Must already exist — no upload is possible.",
    )
    p.add_argument("--order", type=int, help="Sidebar position")

    p.add_argument("--limit", type=int, default=50, help="Page size for --list")
    p.add_argument("--depth", type=int, default=0, help="Population depth")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.add_argument("--yes", action="store_true", help="Actually mutate")
    return p.parse_args()


def categories_from(text: str) -> list[dict]:
    out: list[dict] = []
    for block in extract_json_blocks(text):
        if isinstance(block.get("docs"), list):
            out.extend(d for d in block["docs"] if isinstance(d, dict))
        elif "id" in block or "slug" in block:
            out.append(block)
    return out


def fetch(key: str, where: str | None = None, cat_id: str | None = None,
          limit: int = 50, depth: int = 0) -> list[dict]:
    payload: dict = {"limit": limit, "depth": depth}
    if cat_id is not None:
        payload["id"] = cat_id
    if where:
        payload["where"] = where
    return categories_from(call_tool(key, "findCategories", payload))


def describe(cat: dict) -> str:
    return (
        f"  id={cat.get('id')}  order={cat.get('order')}  "
        f"slug={cat.get('slug')!r}  title={cat.get('title')!r}  "
        f"icon={cat.get('icon')}"
    )


def count_documents_in(key: str, cat_id) -> int:
    """How many documents point at this category — they orphan on delete."""
    text = call_tool(
        key,
        "findDocs",
        {"where": json.dumps({"category": {"equals": cat_id}}), "limit": 100, "depth": 0},
    )
    docs = []
    for block in extract_json_blocks(text):
        if isinstance(block.get("docs"), list):
            docs.extend(d for d in block["docs"] if isinstance(d, dict))
        elif "id" in block:
            docs.append(block)
    return len(docs)


def build_fields(args: argparse.Namespace) -> dict:
    fields: dict = {}
    for name in ("title", "slug", "description", "icon", "order"):
        value = getattr(args, name)
        if value is not None:
            fields[name] = value
    return fields


def resolve_targets(key: str, args: argparse.Namespace, verb: str) -> list[dict]:
    """Resolve --id or --where to concrete categories, enforcing the count guard."""
    if not args.id and not args.where:
        print(
            f"Refusing to {verb}: pass --id or --where.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.id and args.where:
        print("Pass --id or --where, not both.", file=sys.stderr)
        sys.exit(1)

    if args.id:
        targets = fetch(key, cat_id=args.id, depth=args.depth)
        if not targets:
            print(f"Category {args.id} not found.", file=sys.stderr)
            sys.exit(1)
        return targets

    targets = fetch(key, where=args.where, limit=100, depth=args.depth)
    print(f"Filter: {args.where}")
    print(f"Matches {len(targets)} category(ies):")
    for cat in targets:
        print(describe(cat))

    if not targets:
        print(f"\nNothing matches this filter. Nothing to {verb}.")
        sys.exit(0)

    if args.confirm_count is None:
        print(
            f"\nRefusing to {verb}: a --where mutation needs --confirm-count.\n"
            f"This filter matches {len(targets)}. Re-run with "
            f"--confirm-count {len(targets)} --yes.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.confirm_count != len(targets):
        print(
            f"\nRefusing to {verb}: count mismatch.\n"
            f"  --confirm-count says: {args.confirm_count}\n"
            f"  the filter matches:   {len(targets)}\n"
            "Nothing was changed.",
            file=sys.stderr,
        )
        sys.exit(1)
    return targets


def main() -> int:
    args = parse_args()
    key = resolve_key()

    # ── list (read-only) ──
    if args.list:
        cats = fetch(key, where=args.where, limit=args.limit, depth=args.depth)
        if args.json:
            print(json.dumps(cats, indent=2))
        else:
            for cat in sorted(cats, key=lambda c: (c.get("order") or 0, c.get("id") or 0)):
                print(describe(cat))
            print(f"\n{len(cats)} category(ies). These are the site's sidebar tabs.")
        return 0

    # ── create ──
    if args.create:
        missing = [f for f in CREATE_REQUIRED if getattr(args, f) is None]
        if missing:
            print(
                "Missing required field(s): "
                + ", ".join(missing)
                + f"\ncreateCategories requires all of: {', '.join(CREATE_REQUIRED)}.",
                file=sys.stderr,
            )
            return 1
        payload = build_fields(args)
        if not args.yes:
            print("DRY RUN — no category was created. Would call:")
            print("  tool: createCategories")
            print(f"  args: {json.dumps(payload, indent=2)}")
            print("\nRe-run with --yes. A category is a LIVE sidebar tab.")
            return 0
        print(call_tool(key, "createCategories", payload).rstrip())
        return 0

    # ── update ──
    if args.update:
        fields = build_fields(args)
        if not fields:
            print(
                "Nothing to update: pass at least one of --title, --slug, "
                "--description, --icon, --order.",
                file=sys.stderr,
            )
            return 1
        targets = resolve_targets(key, args, "update")
        print("Target category(ies):")
        for cat in targets:
            print(describe(cat))
        print(f"\nChanges: {json.dumps(fields)}")
        if not args.yes:
            print("\nDRY RUN — nothing was changed. Re-run with --yes.")
            return 0
        payload = dict(fields)
        if args.id:
            payload["id"] = args.id
        else:
            payload["where"] = args.where
        print(call_tool(key, "updateCategories", payload).rstrip())
        return 0

    # ── delete ──
    targets = resolve_targets(key, args, "delete")
    print("Target category(ies):")
    total_orphans = 0
    for cat in targets:
        n = count_documents_in(key, cat.get("id"))
        total_orphans += n
        print(f"{describe(cat)}   -> {n} document(s) reference it")

    if total_orphans:
        print(
            f"\nWARNING: deleting these orphans {total_orphans} document(s). "
            "They keep a category id that no longer resolves."
        )
    if not args.yes:
        print("\nDRY RUN — nothing was deleted. Re-run with --yes. There is no undo.")
        return 0

    payload: dict = {"id": args.id} if args.id else {"where": args.where}
    print(call_tool(key, "deleteCategories", payload).rstrip())
    print(f"\nDeleted {len(targets)} category(ies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
