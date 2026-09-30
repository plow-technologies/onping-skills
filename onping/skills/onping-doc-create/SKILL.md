---
name: onping-doc-create
description: Create a document on the OnPing customer-facing documentation site (Payload CMS) via the createDocs MCP tool. MUTATING — requires --yes, and prints the exact tool call without it. Creates an empty page; publish its body with onping-doc-write.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc Create

> **⚠️ WARNING: this skill changes live data.**
> It creates a new document on the live customer-facing documentation site. Undo by deleting it with `onping-doc-delete`. It previews and changes nothing until you pass `--yes`.

Create a new page on the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`.

**MUTATING.** Requires `--yes`. Without it, the exact tool call is printed and
nothing is created.

**The target is a live customer-facing documentation site.** That is a higher stake
than most `onping/skills/` mutations: an operator sees a bad setpoint, but a
customer reads a bad page.

## Usage

```bash
uv run ~/.claude/skills/onping-doc-create/scripts/create_doc.py \
  --title "MQTT JSON Configuration Guide" --slug mqtt-json-configuration-guide \
  --category onping --order 5 --yes
```

| Option | Required | Description |
| --- | --- | --- |
| `--title` | **yes** | The page title |
| `--slug` | **yes** | URL-friendly identifier — this is the site's URL path |
| `--category` | **yes** | Sidebar category: numeric id **or** slug |
| `--order` | **yes** | Position within the category or parent |
| `--description` | no | Brief excerpt |
| `--parent N` | no | Parent document id, for a nested page |
| `--status` | no | `draft` or `published` |
| `--draft` | no | Create as a draft |
| `--depth N` | no | Population depth in the response |
| `--yes` | — | Actually create |

All four required fields are checked **locally** before any request, so a missing
one costs no round trip and names the field it wants.

`--category` accepts a slug and resolves it to an id first, consistent with
`onping-doc-list`. This matters because the server's slug handling elsewhere is
broken — see `onping-doc-list` for the `params: NaN` case.

## A created document has no body

`createDocs` sets metadata only. The new page is one of the null-content records
that `onping-doc-list` hides by default, and it will render as an empty page on the
site.

So a create is normally step one of two. The new id is printed with the follow-up
command:

```
Created document id: 18
This document has NO BODY yet. Publish markdown into it with:
  onping-doc-write --id 18 --markdown <file.md> --audience <persona> --yes
```

There is no `updateDocs` tool — the API key grants `docs` find, create, and delete
but **not** update — so `onping-doc-write` (which wraps `updateDocWithMarkdown`) is
the only way to give the page content.

## A colliding slug is surfaced before the call

The slug is the site's URL path, so a duplicate matters to a reader. When the
requested slug already belongs to another document, the run warns and names it:

```
WARNING: slug 'dnp3' already belongs to document 16 ('DNP3'). The slug is the site's URL path.
```

The warning does not block the create. Payload permits duplicate slugs; whether
that is what you want is your call.

## Related

- `onping-doc-write` — publish the body. Nearly always the next step.
- `onping-doc-list` — check existing slugs and category ids first.
- `onping-doc-category` — create the sidebar tab, if it does not exist yet.
- `_docs_routes` — the shared transport, and the full list of this service's traps.
