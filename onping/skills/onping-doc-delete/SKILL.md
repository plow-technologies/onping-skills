---
name: onping-doc-delete
description: Move documents to the trash on the OnPing customer-facing documentation site (Payload CMS) via the moveToTrash MCP tool — a soft delete, the only delete the server offers over MCP. MUTATING — a single-id trash needs --yes, and a --where bulk trash needs --yes AND a --confirm-count matching the resolved count. Only a human can restore, from the admin panel; back up with onping-doc-get --json first.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc Delete

> **⚠️ WARNING: this skill changes live data.**
> It removes documents from the live customer-facing documentation site by moving them to the trash. No skill can restore them — a human must, from the Payload admin panel — so back each document up first with `onping-doc-get --json`. It previews and changes nothing until you pass `--yes`, and a `--where` run also needs a matching `--confirm-count`.

Remove a page from the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`.

**MUTATING.** Back the document up first:

```bash
uv run ~/.claude/skills/onping-doc-get/scripts/get_doc.py --id 16 --json > backup-16.json
```

**The target is a live customer-facing documentation site.** Trashing a page hides
it from the site and from search, and breaks whatever links to it.

## Usage

```bash
# single document
uv run ~/.claude/skills/onping-doc-delete/scripts/delete_doc.py --id 18 --yes

# bulk, by filter — needs the count as well as --yes
uv run ~/.claude/skills/onping-doc-delete/scripts/delete_doc.py \
  --where '{"_status":{"equals":"draft"}}' --confirm-count 3 --yes
```

| Option | Description |
| --- | --- |
| `--id N` | Document id to move to the trash |
| `--where JSON` | Payload filter. Requires `--confirm-count` **and** `--yes` |
| `--confirm-count N` | The number of documents the filter is expected to match |
| `--yes` | Actually move to the trash |

Passing neither `--id` nor `--where` is refused. A delete with no selector is never
what you meant.

On success the server answers `Moved document "<title>" (ID: N) to trash.` and the
script exits `0`. Any refusal — a missing id, a permission error — exits non-zero
with the server's wording.

## The delete is a soft delete: `moveToTrash`

Since the onping-doc server added `moveToTrash`, the server offers **no hard delete over MCP**. It removed
`deleteDocs` and `deleteCategories` and added one tool:

```
moveToTrash  {"collection": "docs" | "categories", "id": <n>}
```

It sets `deletedAt` on the record. A trashed document drops out of the site and out
of search.

- **Restore** is a human action in the Payload admin panel. No MCP tool restores a
  record.
- **Permanent delete** is owner-only, in the admin UI. An admin — the role the API
  key acts as — is refused.

This is the same shape as `onping-hmi-delete`, which sets `dashDeleted=true`, except
that here no skill can undo it.

**Before this skill handled that change, it reported false success.** It still
called `deleteDocs`; the server answered HTTP `200` with
`MCP error -32602: Tool deleteDocs not found`, and the skill printed
`Deleted document N.` and exited `0`. `call_tool` now fails on that reply. If a
document you believed deleted before 2026-10-19 is still listed, it was never
removed.

## Why `--where` needs a second confirmation

`moveToTrash` takes **one id**. So a `--where` run resolves the filter with
`findDocs` first, prints every match, and then trashes each resolved id in turn.
One broad filter still trashes many customer-facing pages, so the run needs two
independent confirmations:

```
--yes                 the caller intends a mutation
--confirm-count <n>   the caller knows HOW MANY documents match
```

**`--yes` alone is not sufficient**, and that is deliberate. `--yes` asserts intent
to mutate. It does not assert that the caller knows the filter matches nine
documents rather than one. Requiring the count turns a silent mass trash into a
failed precondition:

```
Refusing to run: a --where delete needs --confirm-count.
This filter matches 4 document(s). If that is what you intend, re-run with:
  --confirm-count 4 --yes
```

A count that disagrees with reality is refused with both numbers reported, and
nothing is trashed:

```
Refusing to run: count mismatch.
  --confirm-count says: 1
  the filter matches:   4
Nothing was trashed. Re-check the filter.
```

The ids are trashed one call at a time. If one call fails, the script exits
non-zero at that id: the ids printed before it are in the trash, and the rest are
untouched.

**A filter that matches more than one page is refused.** `findDocs` returns at most
100 matches per call, so the script reads the match total from the
`Total: N documents` line of its reply. If the total is larger than the ids it
resolved, the script exits non-zero without trashing anything:

```
Refusing to run: the filter matches 150 document(s), but one call resolves at most 100 and this one returned 100.
Narrow the filter so it matches no more than that, and re-run.
```

Without this, `--confirm-count 100` would approve the first page and leave the other
50 matches live.

This is stricter than the rest of the `onping/skills/` catalog. The extra strictness
is scoped to the one operation that can remove an unbounded number of
customer-facing pages in one run.

## Related

- `onping-doc-get` — take a `--json` backup before trashing.
- `onping-doc-list` — resolve ids and preview a filter with the same `--where`.
- `onping-doc-category` — `--delete` trashes a category, which hides its documents
  from search.
- `_docs_routes` — the shared transport, and the full list of this service's traps.
