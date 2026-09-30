---
name: onping-ctable-audit-export
description: Pull one custom_table_widget_audit row and decode it into the JSON shape POST /content/ctable/json accepts. Read-only, SELECT only. Handles the four encodings that differ between the audit table and the API, including the S-prefix that applies to exactly two fields. Emits a bare widget by default so it cannot be posted by accident.
allowed-tools: Bash(uv run *)
---

# OnPing ctable-audit-export

Recovers a prior version of a custom-table widget from the audit database and decodes
it into a payload `onping-ctable-import` can post.

**Read-only.** SELECT statements only, no `--yes` gate. Credentials resolve at run
time exactly as in `onping-ctable-audit-history`.

## Usage

```bash
# 1. find the version you want
uv run onping/skills/onping-ctable-audit-history/scripts/ctable_audit_history.py \
  <audit-host> o000000000000000000000049

# 2. decode it — bare widget, not postable yet
uv run onping/skills/onping-ctable-audit-export/scripts/ctable_audit_export.py \
  <audit-host> 600001 --output candidate.json --compare-live backup.json
```

| Argument | Meaning |
|---|---|
| `audit_host` | The audit-server host. **Required, no default** |
| `audit_row_id` | The audit table's own row id, from `onping-ctable-audit-history` |
| `--output PATH` | Write here instead of stdout |
| `--as-envelope ID` | Wrap as `{ctable, cid}` for import. **Off by default** |
| `--compare-live PATH` | Assert key-set parity against an `onping-ctable-export` file |
| `--indent N` | Pretty-print |

**Output is a bare widget unless you ask otherwise.** Without `--as-envelope` the
result is not in postable shape, so it cannot be piped into a write by accident. Pass
the flag only when you mean to prepare a restore.

## The four encodings, and why each has an assertion

The audit table does not store the widget in the shape the API accepts. Every item
below was found by getting it wrong against real data, so each one fails loudly rather
than passing a corrupted value onward.

**1 — The `s` prefix has exactly two homes.** `encodeStringWithSPrefix = Text.cons 's'`,
so the header `Identifier` is stored as `sIdentifier`. It applies to `headers` and to
each cell's `desc`, and **to nothing else**. `title` and `type` persist through a bare
`SomePersistField` and are stored raw.

> This was the first bug in the real decoder. Stripping a character from `type` turns
> `customTable` into `ustomTable`. The skill asserts that the decoded `type` is null or
> exactly `customTable`, so a reintroduced version of this bug fails instead of
> shipping a broken widget.

**2 — `dashboard` is `MongoIdUtf8NoO`.** The hex of the ASCII id with the leading `o`
removed: `\x303030...` decodes to `000000...`, and the `o` must be restored. A widget
posted with the raw hex names an unresolvable parent, and a widget whose parent will
not resolve is unwritable through the API. The decoder fails rather than pass hex on.

**3 — Six cell fields cannot round-trip.** `PostgresCellData` models 16 of `CellData`'s
22 fields; `fromPostgresCellData` hardcodes the other six to null:
`cellDataShowcompanyid`, `cellDataShowcompany`, `cellDataShowsiteid`,
`cellDataShowsite`, `cellDataShowlocid`, `cellDataShowsourceid`.

> These are **display toggles**, and the loss is in the schema rather than in this
> skill. Row and column indices, every PID and VPID, status, description, and
> conditional formatting all survive intact.

**4 — Sorting is forced to null.** A stored value carrying both a column and a type
makes the import handler re-sort the table and renumber every cell row index. The
handler persists `Nothing` anyway, so null is both safe and faithful.

## Verify parity before you trust it

`--compare-live` compares the decoded key sets against a live
`onping-ctable-export` file — both top-level keys and cell keys. A missing cell key is
silently dropped data rather than an error at post time, so this is the regression
guard for the decoder.

Field-verified on 2026-08-26: decoding audit row `600001` produced exact key parity
with the live widget, and the restore it fed posted 2,544 cells that read back
identical.

## Transfer integrity is a real problem, not a precaution

The cells column of a large table is hundreds of kilobytes of JSON. `psql -tA`
line-wraps long values and `COPY` tab-escapes backslashes; **both were observed
producing unparseable output** on the same row. This skill base64-encodes server-side
and decodes locally, and a result that does not re-parse is a hard failure rather than
a quietly truncated return.

## Errors

| Condition | Behavior |
|---|---|
| Non-integer row id | Caught locally, exit 2 |
| No such audit row | Exit 1, pointing at `onping-ctable-audit-history` |
| A header without the `s` prefix | Exit 1 naming the value |
| `type` decoded to anything unexpected | Exit 1 — the trap-1 tripwire |
| `dashboard` not decodable to an id | Exit 1 |
| Key parity failure | Exit 1 listing each missing or extra key |
| Transfer not re-parseable | Exit 1, nothing written |

## Related skills

- `onping-ctable-audit-history` — find the row id first
- `onping-ctable-import` — post what this produces
- `onping-ctable-export` — a live widget, for `--compare-live`
- `onping-audit-recover` — the generic version, which deliberately does *not* decode

## Source of truth

- Audit model / column order: `Dashboard/Persist/Audit/Models/CustomTableWidgetAudit.hs`
  (`toPersistFields` at `:162-174` — which columns are encoded and which are raw)
- The S-prefix: `onping-types/onping-types/src/Onping/Persist/Audit/ColumnSerialization.hs`
- The dropped six: `Dashboard/Persist/Audit/ColumnSerialization/PostgresCellData.hs`
- Sorting re-index: `onping/Handler/Tables/CustomTable/TableSort.hs`
- Live widget shape: `Dashboard/Persist/Models/Internal/CustomTableWidget.hs`

If any of these drift, re-verify against the recorded locations and update
`_ctable_routes/decode.py` and this file.
