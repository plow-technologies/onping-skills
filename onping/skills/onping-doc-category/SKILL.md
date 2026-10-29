---
name: onping-doc-category
description: List, create, update, and trash sidebar categories on the OnPing customer-facing documentation site (Payload CMS) via the three *Categories MCP tools and moveToTrash. --list is read-only; create, update, and delete (a soft delete — move to trash) are MUTATING and require --yes, with a --confirm-count guard on any --where bulk mutation.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc Category

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone by any skill.**
> `--create`, `--update`, and `--delete` change the sidebar categories of the live customer-facing documentation site. `--delete` moves a category to the trash, which hides its documents from search; only a human can restore it, from the admin panel. Undo a create with `--delete` and an update by re-running with the old values. It previews and changes nothing until you pass `--yes`, and a `--where` change also needs a matching `--confirm-count`.

Manage the sidebar tabs on the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`.

`findCategories`, `createCategories`, `updateCategories`, and `moveToTrash` live in
one skill because a category is a small record — `title`, `slug`, `description`,
`icon`, `order` — behind four routes.

**A category is a sidebar tab the customer sees.** Its `order` controls live
navigation, and trashing one hides every document in it from site search.

## Usage

```bash
# read-only
uv run ~/.claude/skills/onping-doc-category/scripts/category.py --list

# create a tab
uv run ~/.claude/skills/onping-doc-category/scripts/category.py \
  --create --title "Drivers" --slug drivers --order 2 --yes

# reorder
uv run ~/.claude/skills/onping-doc-category/scripts/category.py \
  --update --id 3 --order 1 --yes
```

| Mode | Gate |
| --- | --- |
| `--list` | read-only, no `--yes` |
| `--create` | `--yes`; requires `--title`, `--slug`, `--order` |
| `--update` | `--yes`; needs `--id` or `--where`, plus at least one field |
| `--delete` | `--yes`; needs `--id` or `--where`. Moves to the trash |

| Field option | Description |
| --- | --- |
| `--title` | Display title |
| `--slug` | URL-friendly identifier |
| `--description` | Brief description |
| `--icon N` | Media id — must already exist, see below |
| `--order N` | Sidebar position |

| Other | Description |
| --- | --- |
| `--id N` / `--where JSON` | Target selector for update and delete |
| `--confirm-count N` | Required with `--where` on any mutation |
| `--limit N` | Page size for `--list` (default 50) |
| `--depth N` | Population depth |
| `--json` | Emit JSON |

`--create` checks its three required fields locally, before any request.

## Deleting a category moves it to the trash

Since the onping-doc server added `moveToTrash`, the server has no `deleteCategories` tool. `--delete` calls
`moveToTrash` with `{"collection": "categories", "id": <n>}`, which sets
`deletedAt`. A human restores the category from the Payload admin panel; no MCP
tool restores it, and a permanent delete is owner-only in the admin UI.

**Trashing a category hides its documents from site search.** The documents
themselves are not trashed. The dry run counts them first:

```
  id=1  order=0  slug='onping'  title='OnPing'  icon=None   -> 4 document(s) reference it

WARNING: trashing these hides 4 document(s) from site search. The documents themselves are not trashed.
```

`moveToTrash` takes one id, so a `--where` delete trashes each resolved category in
turn. If one call fails, the script exits non-zero at that id: the categories
printed before it are in the trash, and the rest are untouched. A `--where` filter
that matches more than one 100-item page is refused, as in `onping-doc-delete`.

Before 2026-10-19 this skill called the removed `deleteCategories` tool, got
`MCP error -32602: Tool deleteCategories not found` back as an HTTP `200`, and
printed `Deleted N category(ies).` A category you believed deleted before then was
never removed.

## An icon cannot be uploaded

`icon` is a media id, and **the API key grants no `media` access at all**. There is
no MCP upload tool, and REST writes return `500`. So an icon can only be set by
referencing a media id that already exists — for example `52`, which category 3
uses.

`/api/access` reports `media` as create-capable. That is the *collection's* access
config, not this key's capability, and reading it as one is a trap.

## A `--where` mutation needs `--confirm-count`

Same guard as `onping-doc-delete`, for the same reason: `updateCategories` accepts
an arbitrary filter with no dry run of its own, and a `--where` delete trashes every
resolved match. The skill resolves the filter, prints every match, and refuses unless
`--confirm-count` equals the resolved count. `--yes` alone is not sufficient.

Reordering the whole sidebar with one `--where` update is exactly the operation this
guard exists for.

## Related

- `onping-doc-list` — `--category` accepts a slug and resolves it through this data.
- `onping-doc-create` — needs a category id or slug that exists.
- `_docs_routes` — the shared transport, and the full list of this service's traps.
