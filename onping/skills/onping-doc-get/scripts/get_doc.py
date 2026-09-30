# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read one document from the OnPing documentation site. Read-only.

`findDocs` takes an id, so `--slug` is resolved through a `where` filter first.

THE BODY IS LEXICAL RICH TEXT, NOT MARKDOWN:

    {root: {type: "root", children: [Node], direction, format, indent, version}}

Document 14 carries 106 root children (56 paragraph, 34 heading, 15 list, 1
block) with per-node `format` integer bitfields, where `format: 16` marks inline
code. Document 16's body is four `upload` nodes and no text at all — a screenshot
dump with no prose.

There is no `updateDocs` tool (the key grants `docs` find/create/delete and not
update), so a body edit goes through `updateDocWithMarkdown` — see
`onping-doc-write`. Do not hand-author Lexical nodes.

FIELD SHAPES DEPEND ON `--depth`: at depth 0 `category` and `parent` are integer
foreign keys; at depth >= 1 they are nested objects. Do not assume one shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.docs_http import call_tool, extract_json_blocks
from _docs_routes.routes import resolve_key


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read one document from the OnPing documentation site.",
    )
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--id", help="Document id")
    sel.add_argument("--slug", help="Document slug (resolved via a where filter)")
    p.add_argument("--depth", type=int, default=0, help="Relationship population depth")
    p.add_argument("--select", help="JSON string selecting which fields to return")
    p.add_argument(
        "--draft",
        action="store_true",
        help="Read from the versions table instead of the published collection",
    )
    p.add_argument("--json", action="store_true", help="Emit the raw document JSON")
    p.add_argument(
        "--markdown-hint",
        action="store_true",
        help="Summarize the Lexical node types instead of dumping the body",
    )
    return p.parse_args()


def fetch(key: str, args: argparse.Namespace) -> dict:
    payload: dict = {"depth": args.depth}
    if args.select:
        payload["select"] = args.select
    if args.draft:
        payload["draft"] = True

    if args.id:
        payload["id"] = args.id
    else:
        payload["where"] = json.dumps({"slug": {"equals": args.slug}})
        payload["limit"] = 2

    text = call_tool(key, "findDocs", payload)
    blocks = extract_json_blocks(text)

    docs: list[dict] = []
    for block in blocks:
        if isinstance(block.get("docs"), list):
            docs.extend(d for d in block["docs"] if isinstance(d, dict))
        elif "id" in block or "title" in block:
            docs.append(block)

    if not docs:
        print(
            "No document parsed from the response. Server said:\n" + text.rstrip(),
            file=sys.stderr,
        )
        sys.exit(1)

    if args.slug and len(docs) > 1:
        ids = [d.get("id") for d in docs]
        print(
            f"Slug {args.slug!r} matched {len(docs)} documents ({ids}). "
            "Pass --id to disambiguate.",
            file=sys.stderr,
        )
        sys.exit(1)

    return docs[0]


def describe_content(content) -> str:
    """Summarize the Lexical body rather than dumping thousands of nodes."""
    if content is None:
        return "content: null (structurally empty document)"
    if not isinstance(content, dict):
        return f"content: unexpected shape {type(content).__name__}"

    children = (content.get("root") or {}).get("children")
    if not isinstance(children, list):
        return "content: a Lexical root with no children array"

    kinds = Counter(c.get("type") for c in children if isinstance(c, dict))
    summary = ", ".join(f"{n} {k}" for k, n in kinds.most_common())
    line = f"content: Lexical rich text — {len(children)} root children ({summary})"
    if kinds and set(kinds) <= {"upload"}:
        line += "\n  NOTE: upload nodes only — this document carries images and NO prose."
    return line


def main() -> int:
    args = parse_args()
    key = resolve_key()
    doc = fetch(key, args)

    if args.json:
        print(json.dumps(doc, indent=2))
        return 0

    cat, parent = doc.get("category"), doc.get("parent")
    print(f"id:          {doc.get('id')}")
    print(f"title:       {doc.get('title')!r}")
    print(f"slug:        {doc.get('slug')!r}")
    print(f"description: {doc.get('description')!r}")
    print(f"status:      {doc.get('_status')}")
    print(f"order:       {doc.get('order')}")
    print(
        f"category:    {cat!r}"
        + ("  (integer id at depth 0)" if not isinstance(cat, dict) else "  (nested object)")
    )
    print(
        f"parent:      {parent!r}"
        + ("  (integer id at depth 0)" if not isinstance(parent, dict) else "  (nested object)")
    )
    print(f"created:     {doc.get('createdAt')}")
    print(f"updated:     {doc.get('updatedAt')}")
    print(describe_content(doc.get("content")))
    print(
        "\nTo change the body, use onping-doc-write (markdown). There is no "
        "updateDocs tool, and the body is Lexical JSON — do not hand-author it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
