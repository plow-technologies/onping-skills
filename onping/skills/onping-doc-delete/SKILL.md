---
name: onping-doc-delete
description: Delete documents from the OnPing customer-facing documentation site (Payload CMS) via the deleteDocs MCP tool. MUTATING — a single-id delete needs --yes, and a --where bulk delete needs --yes AND a --confirm-count matching the resolved count. No undo exists; back up with onping-doc-get --json first.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc Delete

Remove a page from the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`.

**MUTATING, and there is no undo.** Back the document up first:

```bash
uv run ~/.claude/skills/onping-doc-get/scripts/get_doc.py --id 16 --json > backup-16.json
```

**The target is a live customer-facing documentation site.** Deleting a page breaks
whatever links to it.

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
| `--id N` | Document id to delete |
| `--where JSON` | Payload filter. Requires `--confirm-count` **and** `--yes` |
| `--confirm-count N` | The number of documents the filter is expected to match |
| `--depth N` | Population depth in the response |
| `--yes` | Actually delete |

Passing neither `--id` nor `--where` is refused. A delete with no selector is never
what you meant.

## Why `--where` needs a second confirmation

`deleteDocs` accepts `id` **or** `where`, `where` is an arbitrary Payload filter
string, and the tool offers **no dry run of its own**. One malformed filter deletes
the whole collection.

So this skill resolves the same filter with `findDocs` first, prints every match,
and requires two independent confirmations:

```
--yes                 the caller intends a mutation
--confirm-count <n>   the caller knows HOW MANY documents match
```

**`--yes` alone is not sufficient**, and that is deliberate. `--yes` asserts intent
to mutate. It does not assert that the caller knows the filter matches nine
documents rather than one. Requiring the count turns a silent mass delete into a
failed precondition:

```
Refusing to run: a --where delete needs --confirm-count.
This filter matches 4 document(s). If that is what you intend, re-run with:
  --confirm-count 4 --yes
```

A count that disagrees with reality is refused with both numbers reported, and
nothing is deleted:

```
Refusing to run: count mismatch.
  --confirm-count says: 1
  the filter matches:   4
Nothing was deleted. Re-check the filter.
```

This is stricter than the rest of the `onping/skills/` catalog. The extra strictness
is scoped to the one operation that can destroy an unbounded number of
customer-facing pages in a single call.

## The delete is a real delete

Unlike `onping-hmi-delete`, which is a soft delete that sets `dashDeleted=true`,
`deleteDocs` removes the record. There is no flag to unset and no trash to restore
from — the `trash=false` query parameter in the site's own URLs is a Payload
listing filter, not a recovery path this skill can reach.

## Related

- `onping-doc-get` — take a `--json` backup before deleting.
- `onping-doc-list` — resolve ids and preview a filter with the same `--where`.
- `onping-doc-category` — deleting a category orphans its documents instead.
- `_docs_routes` — the shared transport, and the full list of this service's traps.
