---
name: onping-audit-recover
description: Recover prior state for any audited OnPing model from the audit database in postgres. Read-only, SELECT only. Reaches the models POST /log/audit2/query cannot see, because the audit write path is generic while the read path is an enumerated list. Emits columns as stored and deliberately does not decode per-model encodings.
allowed-tools: Bash(uv run *)
---

# OnPing audit-recover

Lists and dumps audit rows for **any** audited OnPing model, by querying its
`<model>_audit` table directly.

**Read-only.** SELECT statements only, no `--yes` gate.

## Why this exists

The audit **write** path is generic. `auditInsert` folds over every audited model, so
every save of every model lands in `<model>_audit` as a full snapshot.

The audit **read** path is not. `auditGet` dispatches over a hand-maintained
`AuditType` case list, and many models derive `NoIndex` so they never reach
Elasticsearch either. For those models `POST /log/audit2/query` returns **nothing at
all** — not an error, just an empty result that reads like "no history exists".

A generic writer paired with an enumerated reader drifts. Custom tables were the
instance that prompted this skill and they are not the only one: `MenuPanelAudit`,
`ContentObjAudit`, `ContentArrayAudit`, and `ParameterHistoryAudit` are among the
models in the same position.

**Prefer `onping-audit-pull` for the models the API covers.** It is a supported route,
it is permission-scoped server-side, and it needs no SSH. Reach for this skill when
that one returns nothing for a record you know changed.

## Usage

```bash
# what audit tables exist, and how big
uv run onping/skills/onping-audit-recover/scripts/audit_recover.py \
  <audit-host> --list-tables

# a record's version history
uv run onping/skills/onping-audit-recover/scripts/audit_recover.py \
  <audit-host> --table menu_panel_audit --original-id o000000000000000000000005

# one version, every column, as JSON
uv run onping/skills/onping-audit-recover/scripts/audit_recover.py \
  <audit-host> --table custom_table_widget_audit --dump-row 600001 --output row.json
```

| Argument | Meaning |
|---|---|
| `audit_host` | The audit-server host. **Required — no default address** |
| `--list-tables` | Enumerate audit tables with row counts |
| `--table NAME` | The `<model>_audit` table to work with |
| `--original-id ID` | The record's mongo id (`o`-prefixed or bare 24-hex) |
| `--dump-row N` | Emit one audit row as JSON |
| `--limit N` / `--all` | Bound or unbound the version list |
| `--output PATH` | Write `--dump-row` output here |
| `--indent N` | Pretty-print |

An unknown table name exits non-zero and suggests the nearest match.

## CAUTION: this skill does not decode anything

Columns come out **as stored**. That is deliberate. Audit columns use several
encodings and which one applies is per model:

| Encoding | Where it appears |
|---|---|
| A literal `s` text prefix | Some text and text-list columns |
| Hex-of-ASCII (`MongoIdUtf8NoO`) | Id reference columns |
| Haskell `Show`/`Read` | Some structured columns |
| Plain JSON | Others |

A generic decoder across those would **silently corrupt values** rather than fail,
which is worse than not decoding. Decoding is the caller's job.

`onping-ctable-audit-export` is the worked example of what per-model decoding looks
like: four encodings, each with an assertion, each documented against its source
location.

## Deletions are recoverable

The delete path reads the document *before* removing it, so a row whose `audit_action`
is `Delete` carries the record's final pre-delete content. A deleted record is
therefore recoverable, and the version list marks the action so you can find it.

## Reading the version list

Byte lengths of the large columns are included, because a step change in one of them
is the signature of a wholesale overwrite rather than an edit. That signal is what
identified the incident this skill family was built for.

## Credentials are read at run time, never stored

The skill SSHes to the audit host, reads the postgres block from the deployed
`onping-audit-server` config, and connects with what it finds. No password, username,
or database name lives in this repository, and a rotation needs no change here.

Two topology facts, both of which cost real time to discover:

- **The audit host is a required argument.** The wiki runbook this work replaced
  hardcoded a mongo hostname that is now NXDOMAIN and an IP in a non-production
  subnet. Baking in an address is how that document became wrong.
- **Postgres binds to the database host's own address, not localhost.** A `localhost`
  connection is refused *from the database host itself*. The address comes from the
  config's `host` field, resolved through consul when it is a `.service.consul` name.
  The audit server and the database are different machines, and only the database host
  has `psql`.

## Errors

| Condition | Behavior |
|---|---|
| No operation requested | Exit 2 listing the valid combinations |
| Unknown table | Exit 1 with the nearest-match suggestion |
| Malformed id | Exit 2, no connection made |
| No rows for that id | Exit 1, naming which id interpretation was used |
| Table has no `original_id` | Exit 1 — it is not a per-record audit table |
| VPN down / SSH refused | Exit 1 naming the host tried; **no fallback** |

An id in the wrong form returns zero rows rather than an error, so the output always
states which interpretation it used.

## Related skills

- `onping-audit-pull` — the supported HTTP route; prefer it where it works
- `onping-ctable-audit-export` — the worked per-model decoder
- `onping-ctable-audit-history` — the custom-table-specific version list

## Source of truth

- The generic write path: `onping-audit-server/src/Onping/Audit/Server.hs`
  (`auditInsert`, dispatching over `foldAuditModelSum`)
- The enumerated read path: `onping-audit-server/src/Onping/Audit/Server.hs`
  (`auditGet`)
- The `NoIndex` derivations: `onping-audit-server/src/Onping/Audit/Index/Model.hs`
- Delete-then-audit ordering: `onping-core audit queries module`
- `AuditAction`: `onping-audit-types/src/Onping/Audit/Types/AuditAction.hs`

If any of these drift, re-verify against the recorded locations and update
`_audit_db/audit_db.py` and this file.
