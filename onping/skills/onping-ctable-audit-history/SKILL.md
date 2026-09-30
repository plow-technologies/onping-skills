---
name: onping-ctable-audit-history
description: List the save history of an OnPing custom-table widget from the audit database — when, who, action, and payload size per version. Read-only, SELECT only. Reaches history that POST /log/audit2/query cannot see at all, and flags the size step that means a table was overwritten rather than edited.
allowed-tools: Bash(uv run *)
---

# OnPing ctable-audit-history

Lists every save of a custom-table widget: audit row id, timestamp, author, action,
and the byte length of the cells and headers columns.

**Read-only.** SELECT statements only, no `--yes` gate.

## Why this goes to postgres and not to the audit API

OnPing writes a **full snapshot** of a custom table on every save into
`custom_table_widget_audit`. `toAudit` copies all eight widget fields verbatim, and
the delete path reads the document before removing it, so even a deletion row
carries the final pre-delete content.

`POST /log/audit2/query` cannot read any of it, for two unrelated reasons that
stack — fixing either alone changes nothing:

| Layer | Why it stops |
|---|---|
| Elasticsearch | `CustomTableWidget` derives `NoIndex`, so nothing about it is ever indexed |
| `auditGet` dispatch | An enumerated per-`AuditType` case list with no custom-table branch |
| `AuditType` enum | No constructor exists to request one |

Verified live rather than inferred: `onping-audit-pull --list-types` returns 30 audit
types and not one is a custom table. So postgres over SSH is the only path, which is
why this skill needs a host argument and a VPN rather than just a bearer token.

## Usage

```bash
uv run onping/skills/onping-ctable-audit-history/scripts/ctable_audit_history.py \
  <audit-server-host> o000000000000000000000049
```

| Argument | Meaning |
|---|---|
| `audit_host` | The audit-server host. **Required — this skill carries no default address** |
| `ctable_id` | The widget id. Accepts `o`-prefixed or bare 24-hex |
| `--limit N` | Rows to show, default 25 |
| `--all` | Every version |
| `--tsv` | Tab-separated output |
| `--quiet-resolve` | Suppress the resolved-target line on stderr |

## Read the cells length first

```
audit_id  edited_on                        edited_by             action    cells_len   hdrs
  600002  2026-08-25 16:27:19.893406-05    someone@example.com   Update      2462311    340  <== SIZE STEP
  600001  2026-08-17 13:37:02.091438-05    another@example.com   Update       655787    213
```

`cells_len` is the column that identifies an overwrite. An edit moves it by a little;
a *replacement* moves it by a lot. The row flagged above is a real incident: a
12-column liquid-measurement table was replaced by a 23-column gas-measurement table
under the same ObjectId, and the size step is what made it visible after the header
lists were compared.

Versions whose cells length changes by 2× or more against the next-older version are
flagged. **The flag is advisory and never changes the exit code** — a legitimate bulk
edit can trip it.

## Two traps this skill handles for you

**The id form.** The HTTP routes want `o000000000000000000000049`; the audit table
stores `000000000000000000000049` in `original_id`. Querying with the wrong form
returns **zero rows rather than an error**, which reads exactly like "this widget has
no history". Both forms are accepted, and the output states which interpretation was
used.

**`length()`, not `array_length()`.** The `headers` column is `character varying`, not
an array, so `array_length(headers, 1)` errors out. Learned the hard way.

## Credentials are read at run time, never stored

The skill SSHes to the audit host, reads the postgres block from the deployed
`onping-audit-server` config, and connects with what it finds. No password, username,
or database name is stored in this repository, and a password rotation needs no
change here.

Two topology facts the skill encodes, both of which cost real time to discover:

- **The audit host is a required argument.** The wiki runbook this work replaced
  hardcoded a mongo hostname that is now NXDOMAIN and an IP in a non-production
  subnet. Baking in an address is how that document became wrong.
- **Postgres binds to the database host's own address, not localhost.** A `localhost`
  connection is refused *from the database host itself*. The address comes from the
  config's `host` field, resolved through consul when it is a `.service.consul` name.
  The audit server and the database are different machines, and only the database
  host has `psql`.

## Errors

| Condition | Behavior |
|---|---|
| Malformed id | Caught locally, exit 2, no connection made |
| No rows for that id | Exit 1, naming which id interpretation was used |
| Table absent | Exit 1 |
| VPN down / SSH refused | Exit 1 naming the host tried; **no fallback to any other address** |

## Related skills

- `onping-ctable-audit-export` — pull and decode one of these versions
- `onping-ctable-export` — the widget's *current* state, over HTTP
- `onping-audit-recover` — the same access, generalized to any audited model
- `onping-audit-pull` — the supported HTTP route, for the models it covers

## Source of truth

- Audit model: `onping-types/onping-content-config-types/src/Dashboard/Persist/Audit/Models/CustomTableWidgetAudit.hs`
  (`toAudit` at `:86-103`; the 13-column layout at `:123-141`)
- The `NoIndex` derivation: `onping-audit-server/src/Onping/Audit/Index/Model.hs`
- The enumerated read path: `onping-audit-server/src/Onping/Audit/Server.hs`

If any of these drift, re-verify against the recorded locations and update
`_audit_db/audit_db.py` and this file.
