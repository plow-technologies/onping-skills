---
name: onping-logtable-get
description: Read one OnPing log table's LogTableSource — the current (or --version N) schema's columns with position, UUID, PID/VPID key, selector, event marker, hidden flag, and name; the version list; and schema problems — or the raw JSON (--json / --output). Read-only.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — Get

Show one log table's definition. Each column is **keyed by** the PID or VPID it
records and has a selector (Result, Unit, LastUpdateDateTime, …). The column
marked `*` is the event (trigger) column: its key is the table's
`schemaHeaderEventSource`, a PID, and a row is recorded whenever it updates.

> **Read-only** — no `--yes` gate.

> **Schemas are chosen by version, not by list position.** A source keeps every
> schema it ever had, newest first. The script selects by `logSchemaVersion`.

## Related Skills

- **onping-logtable-list** — find the LJ and UUID
- **onping-logtable-fetch** — the rows
- **onping-logtable-column-add** / **-column-delete** / **-column-set** — edits
- **onping-logtable-export** — the same table as the import XLSX template

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-logtable-get/scripts/get_logtable.py "$ACCESS_TOKEN" <LJ> <table-uuid>
uv run ~/.claude/skills/onping-logtable-get/scripts/get_logtable.py "$ACCESS_TOKEN" <LJ> <table-uuid> --version 1
uv run ~/.claude/skills/onping-logtable-get/scripts/get_logtable.py "$ACCESS_TOKEN" <LJ> <table-uuid> --output source.json
```

## Flags

- `--version N` — show schema version N instead of the current one.
- `--json` — the raw LogTableSource (with `--version`, that schema only).
- `--output PATH` — write that JSON to PATH.

## Output

Name, UUID, LJ, group, versions, the version shown, the event PID, any
`requiresRestore` flag or schema problem, then
`pos  uuid  key  selector  event  hidden  name`. A version-0 table (created, no
schema yet) says so and exits 0.

## API Reference

| Endpoint | Method | Response |
|----------|--------|----------|
| `/logtable/<LJ>/source/list` | GET | `[LogTableSource]`; the script keeps the one matching the UUID |

Handler: `onping/Handler/OnpingLogTable/Service.hs (getLogTableSourceListR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned-or-member groups.

## Error Handling

- **UUID not on that LJ** or **no such version** — exit 1.
- **LJ has no routing / token expired** — exit 1 with a hint.
