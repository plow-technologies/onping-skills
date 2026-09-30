---
name: onping-ctable-import
description: Write a CustomTableWidget to OnPing via POST /content/ctable/json — a full-document mongo repsert that preserves the caller's ObjectId. MUTATING, requires --yes. Restores a widget from onping-ctable-export or onping-ctable-audit-export. Refuses the four payloads that quietly ruin a widget, and verifies the write by readback.
allowed-tools: Bash(uv run *)
---

# OnPing ctable-import

> **⚠️ WARNING: this skill changes live data.**
> It replaces the whole custom-table widget document at the target id, or creates it if none exists. Undo by re-importing a backup taken with `onping-ctable-export`, or a prior version recovered with `onping-ctable-audit-export`. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Writes a custom-table widget back into OnPing at an exact ObjectId. This is the
restore half of the round trip whose read half is `onping-ctable-export`.

## Why this route and no other

A custom table is referenced **only** by its mongo `_id`. The dashboard panel
stores `CustomTableIdConfig { cTableId }` and the widget stores the reverse pointer
`customTableWidgetDashboard`. Neither side carries a name or a slug, so a restore
must write back into the same `_id` or the panel points at a document that does not
exist.

`POST /content/ctable/json` is the only path that lets the caller choose the id:

```
postCustomTableJsonR → repsertCustomTableWidget → repsertAndAudit
  → DB.repsert → DB.save collection (keyDoc ++ valueDoc)
```

`DB.save` carrying an `_id` is an upsert at that id. It is also **audited** —
`repsertAndAudit` records `Create` or `Update` with your username — which the
wiki's `mongo … custom.js` path is not.

`POST /content/ctable/config` cannot be used for a restore: it mints a
server-generated id. The XLSX import at `/content/ctable/import` is lossy, rewriting
only headers and cells while dropping title, zoom, and sorting.

## CAUTION: this is a whole-document replace

There is no merge step. Posting a 12-cell widget to a 9,568-cell table leaves 12
cells and discards the rest. Back up first:

```bash
uv run onping/skills/onping-ctable-export/scripts/export_ctable.py \
  "$ACCESS_TOKEN" <id> --output backup.json
```

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# Preview — validates, prints before/after counts, issues no POST:
uv run onping/skills/onping-ctable-import/scripts/import_ctable.py \
  "$ACCESS_TOKEN" o000000000000000000000049 candidate.json --dry-run

# Apply:
uv run onping/skills/onping-ctable-import/scripts/import_ctable.py \
  "$ACCESS_TOKEN" o000000000000000000000049 candidate.json --yes --verify-live
```

| Argument | Meaning |
|---|---|
| `access_token` | OnPing bearer token |
| `ctable_id` | Target widget id (`o`-prefixed or bare 24-hex) |
| `widget_json` | A bare widget, or a `{ctable, cid}` envelope — either is accepted |
| `--yes` | Perform the write. Without it, nothing is posted |
| `--dry-run` | Validate and preview. **Wins over `--yes`** |
| `--force` | Permit a parent-dashboard change |
| `--verify-live` | After the write, report how many PIDs resolve to live values |

## The four refusals, and why each exists

Each corresponds to a way this route quietly ruins a widget. All are checked
locally before any request.

**A null `customTableWidgetDashboard` is refused.** Permission is not read from the
widget — `checkCustomTableUserPermissions` reads the dashboard the widget names and
tests `editDashboardPermission` on it. A widget naming no dashboard yields
`CustomTableUserPermissions False False` and becomes **permanently unwritable
through the API**. One bad post is enough.

**A differing dashboard needs `--force`.** Retargeting a widget's parent silently
moves who can edit it. The skill shows both values and stops.

**A non-null `customTableSortingInformation` is refused.**
`indexCustomTableBySortingInformation` re-sorts the table and rewrites every cell
row index when that field carries both a column and a type. The handler persists
`Nothing` anyway, so null is both safe and faithful.

**An oversize body is refused locally.** The cap is 8 MiB for this route alone.
Measuring locally beats uploading 8 MiB to be told no.

Also checked: the four keys parsed with `.:` rather than `.:?` must be present, and
every `cellDataRow` / `cellDataCol` must be a non-negative integer. A gap in the row
index is a warning, not a refusal — row indices are positional, so a gap renders as
a blank row.

## CAUTION: HTTP 200 does not mean the write happened

`postCustomTableJsonR` answers a permission refusal with the bare JSON string
`"insufficient permissions"` **and a 200 status**. A client that tests the status
code reports a restore that never occurred. This skill parses the body and treats
any JSON string result as a failure; only an echoed `{ctable, cid}` object counts.

## Verification is not optional

After a successful write the skill re-reads the widget and compares:

- all 7 scalar fields, individually
- every cell by `(row, col, pid, vpid, desc)` tuple

Any difference exits non-zero, because a silent partial write is worse than a
reported failure. `--verify-live` additionally calls `/api/customtabledata/get` and
reports how many parameters resolved to current values — the difference between
"the PIDs are present" and "the PIDs are reporting".

Field-verified on 2026-08-26 against a practice widget: 2,544 cells posted, 2,544
read back identical, all scalars matched, and 1,906 of 1,906 parameters resolved
live. The audit row the write produced carried the same `length(cells)` as the source
row — independent proof the round trip is lossless.

## Related skills

- `onping-ctable-export` — back up before writing
- `onping-ctable-audit-history` — find the last good save
- `onping-ctable-audit-export` — decode a prior version into a payload for this skill

## Source of truth

- Handler: `onping/Handler/Tables/CustomTable/Table.hs` (`postCustomTableJsonR`);
  envelope type at `:95-114`; the 200-with-refusal at `:159`
- Repsert chain: `Request/Raw/MongoDB/CustomTableConfig.hs` →
  `Persist/Audit/Queries.hs` → the MongoDB layer
- Permission: `onping/Handler/Tables/CustomTable/Permissions.hs`
- Sorting re-index: `onping/Handler/Tables/CustomTable/TableSort.hs`
- Body cap: `onping/Foundation.hs`

If any of these drift, re-verify against the recorded locations and update
`_ctable_routes/routes.py` and this file.
