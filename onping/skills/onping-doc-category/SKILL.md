---
name: onping-doc-category
description: List, create, update, and delete sidebar categories on the OnPing customer-facing documentation site (Payload CMS) via the four *Categories MCP tools. --list is read-only; create, update, and delete are MUTATING and require --yes, with a --confirm-count guard on any --where bulk mutation.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc Category

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> `--create`, `--update`, and `--delete` change the sidebar categories of the live customer-facing documentation site. Deletes cannot be undone and leave documents pointing at a missing category; undo a create with `--delete` and an update by re-running with the old values. It previews and changes nothing until you pass `--yes`, and a `--where` change also needs a matching `--confirm-count`.

Manage the sidebar tabs on the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`.

All four `*Categories` tools live in one skill because a category is a small record
— `title`, `slug`, `description`, `icon`, `order` — behind four routes.

**A category is a sidebar tab the customer sees.** Its `order` controls live
navigation, and deleting one orphans every document pointing at it.

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
| `--delete` | `--yes`; needs `--id` or `--where` |

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

## Deleting a category orphans its documents

The dry run counts the affected documents first:

```
  id=1  order=0  slug='onping'  title='OnPing'  icon=None   -> 4 document(s) reference it

WARNING: deleting these orphans 4 document(s). They keep a category id that no longer resolves.
```

The documents are not deleted with the category. They keep a `category` id that no
longer resolves, which is why the count is surfaced before you commit.

## An icon cannot be uploaded

`icon` is a media id, and **the API key grants no `media` access at all**. There is
no MCP upload tool, and REST writes return `500`. So an icon can only be set by
referencing a media id that already exists — for example `52`, which category 3
uses.

`/api/access` reports `media` as create-capable. That is the *collection's* access
config, not this key's capability, and reading it as one is a trap.

## A `--where` mutation needs `--confirm-count`

Same guard as `onping-doc-delete`, for the same reason: `updateCategories` and
`deleteCategories` both accept an arbitrary filter with no dry run of their own. The
skill resolves the filter, prints every match, and refuses unless
`--confirm-count` equals the resolved count. `--yes` alone is not sufficient.

Reordering the whole sidebar with one `--where` update is exactly the operation this
guard exists for.

## Related

- `onping-doc-list` — `--category` accepts a slug and resolves it through this data.
- `onping-doc-create` — needs a category id or slug that exists.
- `_docs_routes` — the shared transport, and the full list of this service's traps.
