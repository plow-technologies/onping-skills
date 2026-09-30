---
name: onping-ctable-export
description: Export an OnPing custom-table widget as JSON via GET /content/ctable/json. Read-only. The backup half of the custom-table restore round trip, and the first step before any onping-ctable-import. Reports the payload size against the 8 MiB cap that the import route enforces.
allowed-tools: Bash(uv run *)
---

# OnPing ctable-export

Downloads a custom-table widget as JSON — title, headers, every cell, type, zoom,
and the parent dashboard id. Its write counterpart is `onping-ctable-import`,
together giving the export → edit → re-import round trip.

**Read-only.** No `--yes` gate.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

uv run onping/skills/onping-ctable-export/scripts/export_ctable.py \
  "$ACCESS_TOKEN" o000000000000000000000049 --output backup.json
```

| Argument | Meaning |
|---|---|
| `access_token` | OnPing bearer token (from `onping-login`) |
| `ctable_id` | The widget id. Accepts `o`-prefixed or bare 24-hex |
| `--output PATH` | Write here instead of stdout |
| `--indent N` | Pretty-print. Omit for the compact form that round-trips byte-identically |

## Two things that look like bugs and are not

**`cTableId` is a query parameter, never a path segment.** The route
`GET /content/ctable/export/{filename}` takes a *download filename* in its path,
not the table id, which is easy to misread. Putting the id in the path returns
`400 "No table id found"` — a message that reads like a missing widget and is
actually a missing query parameter. This skill always sends it correctly.

**A missing widget returns `null` with HTTP 200, not a 404.** So a naive client
writes the four bytes `null` into a file and calls it a backup. This skill treats
`null` as a failure, writes nothing, and exits non-zero. When you only need the
existence answer, `GET /does/content/ctable/json/exist` is cheaper.

## What the summary tells you

```
o000000000000000000000049: 416 rows x 23 columns, 9568 cells
  dashboard : o000000000000000000000005
  size      : 5210190 bytes (62% of the 8 MiB import cap)
  wrote     : backup.json
```

The size line matters because `POST /content/ctable/json` caps its body at 8 MiB
and **that cap belongs to this route alone** — every other OnPing route carries a
different figure. Above 75 percent the summary warns you, because a widget that
grows past the cap can no longer be restored through the API at all.

A gap in the row index is also reported. Row indices are positional, so a gap
renders as a blank row in the widget.

## Errors

| Condition | Behavior |
|---|---|
| Malformed id | Caught locally, exit 2, no request issued |
| No widget at that id (`null` body) | Exit 1, nothing written |
| Expired token | Exit 1 naming the token — see below |
| Non-200 | Exit 1 with the response surfaced |

**An expired token presents three different ways** against these routes, and all
three are detected: a `303 → /auth/login` redirect, a 200 carrying an HTML login
page, and `401 {"error":"NotAuthenticated"}`. The 401 was found while building this
skill; reported as a generic HTTP error it sent the reader looking at the id
instead of the token, so it now names the token explicitly.

The output file is written **only** after a confirmed non-null object, so a failure
never clobbers an existing backup.

## Related skills

- `onping-ctable-import` — the write counterpart, a full-document repsert
- `onping-ctable-audit-history` — a widget's save history, when the current state is wrong
- `onping-ctable-audit-export` — recover a prior version from the audit database

## Source of truth

- Handler: `onping/Handler/Tables/CustomTable/Table.hs` (`getCustomTableJsonR`)
- Route: `onping/config/routes` (`CustomTableJsonR GET POST`)
- Types: `onping-types/onping-content-config-types/src/Dashboard/Persist/Models/Internal/CustomTableWidget.hs`
  (the record; `ToJSON`/`FromJSON` at `:178-201`)
- Body cap on the write route: `onping/Foundation.hs`

If any of these drift, re-verify against the recorded locations and update
`_ctable_routes/routes.py` and this file.
