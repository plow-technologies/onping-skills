---
name: onping-doc-list
description: List and filter documents on the OnPing customer-facing documentation site (Payload CMS) via the findDocs and getDocsByCategory MCP tools. Read-only. Use to discover document ids, slugs, and categories before reading with onping-doc-get or publishing with onping-doc-write.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc List

Discover documents on the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`. Read-only — no `--yes` gate.

This is the discovery entry point: the ids it returns feed `onping-doc-get`,
`onping-doc-write`, and `onping-doc-delete`.

## Usage

```bash
uv run ~/.claude/skills/onping-doc-list/scripts/list_docs.py --limit 100
uv run ~/.claude/skills/onping-doc-list/scripts/list_docs.py --where '{"title":{"contains":"DNP3"}}'
uv run ~/.claude/skills/onping-doc-list/scripts/list_docs.py --category onping
```

No token from `onping-login` is needed. This service has its own API key, resolved
by `_docs_routes` from `ONPING_DOCS_API_KEY`, a plaintext `onping-docs` file, or
`onping-docs.gpg`.

| Option | Default | Description |
| --- | --- | --- |
| `--category VAL` | none | Filter by category; accepts an id **or** a slug |
| `--where JSON` | none | Payload filter string, passed to `findDocs` |
| `--limit N` | 10 | Page size; the server caps this at 100 |
| `--page N` | 1 | Page number |
| `--sort FIELD` | none | Sort field, e.g. `-updatedAt` for descending |
| `--depth N` | 0 | Relationship population depth |
| `--select JSON` | none | Restrict which fields come back |
| `--draft` | off | Query the versions table instead of the published collection |
| `--include-empty` | off | Show structurally empty documents |
| `--json` | off | Emit JSON instead of the text table |

## Two tools, two response shapes

`--category` routes to `getDocsByCategory`; everything else routes to `findDocs`.
They do not answer in the same format:

- **`findDocs`** returns a prose string with the documents embedded as JSON inside
  a fenced block. This script parses that JSON, so it can filter and tabulate.
- **`getDocsByCategory`** returns prose with `Document ID: <n>` lines and **no JSON
  at all**. This script prints the server's text and appends the parsed id list.

Two tools in the same collection, two parse strategies. That is the server's
design, not this skill's.

## A category slug is resolved before the call

`getDocsByCategory` advertises `["string","number"]` for `category` and its
description claims it accepts a "category slug or ID". **The slug branch is
broken.** A slug reaches an integer column unparsed:

```
Error fetching documents by category: Failed query: select count(*) from "docs"
where "docs"."category_id" = $1  params: NaN
```

So `--category onping` is resolved to `category: 1` through `findCategories`
before the call. A slug is never forwarded, and there is no fallback that does —
an unresolvable slug exits non-zero rather than letting the server produce `NaN`.

## Empty drafts are hidden by default

The collection holds structurally empty records. Documents 17 and 9 carry
`title: null`, `slug: null`, and `content: null`, and document 17's breadcrumb is
`{doc: 17, url: "/null", label: null}`.

Documents with no title are omitted by default, and **the omitted count is always
reported** so a hidden record is never silently dropped:

```
7 document(s) shown.
2 structurally empty document(s) omitted (null title). Pass --include-empty to see them.
```

Presenting a null-titled draft as a documentation page is the defect this default
prevents.

## Trashed documents are not listed

`onping-doc-delete` moves a document to the trash (`moveToTrash` sets `deletedAt`),
and a trashed document drops out of `findDocs` and out of this list. A human sees
and restores it in the Payload admin panel.

This skill used to filter a `trash-` slug and `TRASH` title marker with `--trash`
and `--no-trash`. That marker was a stopgap from before the server offered any
delete, and both flags are gone. A document that still carries the marker is an
ordinary document: trash it with `onping-doc-delete`.

## The documentation collections are world-readable

`GET /api/docs` returns byte-identical payloads with no `Authorization` header, a
garbage token, or the real key. Anything that can reach the host can enumerate
every document, and document 14's full body is retrievable unauthenticated.

The API key is **not** what makes a read succeed. This skill sends it anyway, so a
future tightening of the server's access rules does not break it. This is the
server's access posture — the skill neither introduces it nor can change it.

## Related

- `onping-doc-get` — read one document, including its Lexical body shape.
- `onping-doc-category` — list, create, update, and trash the sidebar tabs.
- `onping-doc-delete` — move a document to the trash.
- `onping-doc-write` — publish markdown to a document.
- `_docs_routes` — the shared transport, and the full list of this service's traps.
