---
name: onping-doc-get
description: Read one document from the OnPing customer-facing documentation site (Payload CMS) by id or slug, and report its Lexical content shape. Read-only. Use to inspect or back up a document before editing it with onping-doc-write or removing it with onping-doc-delete.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc Get

Read a single document from the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`. Read-only — no `--yes` gate.

Use `--json` to take a backup **before** any destructive operation. No undo exists
on this service.

## Usage

```bash
uv run ~/.claude/skills/onping-doc-get/scripts/get_doc.py --slug dnp3
uv run ~/.claude/skills/onping-doc-get/scripts/get_doc.py --id 14 --json > backup-14.json
```

| Option | Default | Description |
| --- | --- | --- |
| `--id N` | — | Document id. Mutually exclusive with `--slug` |
| `--slug S` | — | Document slug, resolved through a `where` filter |
| `--depth N` | 0 | Relationship population depth |
| `--select JSON` | none | Restrict which fields come back |
| `--draft` | off | Read from the versions table |
| `--json` | off | Emit the raw document JSON — use this for backups |

`findDocs` takes an id, so `--slug` is resolved with a `where` filter first. A slug
matching more than one document is an error rather than an arbitrary pick.

## The body is Lexical rich text, not markdown

A document's `content` is:

```
{root: {type: "root", children: [Node], direction, format, indent, version}}
```

The default output summarizes the node types rather than dumping the tree:

```
content: Lexical rich text — 106 root children (56 paragraph, 34 heading, 15 list, 1 block)
```

Per-node `format` is an integer bitfield, where `16` marks inline code. A document
whose children are all `upload` nodes carries images and **no prose**, and the
output says so explicitly — document 16 is a screenshot dump of exactly that kind.

**To change a body, use `onping-doc-write` with markdown.** There is no `updateDocs`
tool: the API key grants `docs` find, create, and delete but **not** update, so
`updateDocWithMarkdown` is the only body-editing path. The server converts markdown
to Lexical. Do not hand-author Lexical nodes.

## Field shapes depend on `--depth`

At `--depth 0` the `category` and `parent` fields are integer foreign keys:

```
category:    1  (integer id at depth 0)
```

At `--depth 1` or deeper they are nested objects:

```
category:    {'id': 1, 'title': 'OnPing', 'slug': 'onping', ...}  (nested object)
```

The output labels which shape it returned. A consumer must not assume one.

## A missing document is an error, not an empty result

The server reports a missing id as a **successful** JSON-RPC result whose text
begins with an error sentence:

```
Error: Document with ID "99999" not found in collection "docs"
```

`_docs_routes` detects this and exits non-zero, surfacing the server's wording
verbatim. A client that checked only for a JSON-RPC `error` member would report the
lookup as a success.

## Related

- `onping-doc-list` — discover ids and slugs.
- `onping-doc-write` — publish markdown to a document.
- `onping-doc-delete` — remove a document; back it up here first.
- `_docs_routes` — the shared transport, and the full list of this service's traps.
