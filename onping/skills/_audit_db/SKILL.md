---
name: _audit_db
description: Internal helper — do not invoke. Shared Python module (audit_db.py, ids.py) imported by the OnPing audit-recovery skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _audit_db (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
entry point. It exists so the Nix bundler places the module at the skills root,
where the audit-recovery scripts import it as a sibling.

| Module | Contents |
|---|---|
| `audit_db.py` | Runtime credential resolution, SSH transport, and the base64-safe query verbs |
| `ids.py` | Conversion between the three forms the same mongo id takes |

Three behaviors these modules centralize:

1. **Credentials resolve at run time.** `resolve_pg()` reads the postgres block from
   the deployed `onping-audit-server` config over SSH. No password, username, or
   database name is stored in this repository, so a rotation needs no change here.
2. **No default host anywhere.** The audit host is a required argument in every
   caller. The wiki runbook this work replaced hardcoded an address that is now
   NXDOMAIN, and baking one in is how that document became wrong.
3. **Transfers are base64-encoded.** `psql -tA` line-wraps and `COPY` tab-escapes;
   both were observed corrupting a 655 KB cells column. A result that does not
   re-parse is a hard failure rather than a truncated return.

User-facing skills: `onping-ctable-audit-history`, `onping-ctable-audit-export`,
`onping-audit-recover`.
