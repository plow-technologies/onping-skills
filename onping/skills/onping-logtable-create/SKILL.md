---
name: onping-logtable-create
description: Create an OnPing log table on a Lumberjack with all its columns in one step — POST source/create, then one version-1 schema/upgrade holding the LastUpdateDateTime event column keyed by the trigger PID (--event-pid) plus every column given with --column NAME=SOURCE[:TAG], or copied from an onping-logtable-export XLSX with --from. MUTATING — checks the columns before any request, previews by default, posts only with --yes, verifies the read-back, and names any orphaned version-0 source. No dashboard is needed.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — Create

> **⚠️ WARNING: this skill changes live data.** It creates a log table on a
> live Lumberjack, which then records a row every time the trigger PID
> updates. It previews by default and changes nothing until you pass `--yes`;
> `--dry-run` also previews and wins over `--yes`. Remove a table with
> `onping-logtable-delete`.

Creation is two requests. `source/create` makes a version-0 source with no
schema, which records nothing. `schema/upgrade` then adds version 1: the event
column (`LastUpdateDateTime` of the trigger PID) and every column you declared.
Declaring the columns here, rather than with `onping-logtable-column-add`
afterwards, avoids an empty schema version per added column. If the second
request fails the version-0 source is left behind, and the script prints its
UUID.

## Related Skills

- **onping-logtable-list** — the group used by tables already on the LJ
- **onping-logtable-export** — the XLSX that `--from` reads
- **onping-logtable-column-add** — add a column to an existing table (a new, empty version)
- **onping-logtable-import** — upload a template sheet, rows included, to an existing table
- **onping-logtable-delete** — remove a table

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-logtable-create/scripts/create_logtable.py
uv run $S "$ACCESS_TOKEN" <LJ> --name "Well 7 Log" --event-pid 500001          # prints group hints, exit 2
uv run $S "$ACCESS_TOKEN" <LJ> --name "Well 7 Log" --event-pid 500001 --group <group-id> \
    --column "Casing=500002" --column "Tubing=500003" --column "Mode=7 VPID:unit"
uv run $S "$ACCESS_TOKEN" <LJ> --name "Well 7 Log" --event-pid 500001 --group <group-id> \
    --column "Casing=500002" --column "Tubing=500003" --column "Mode=7 VPID:unit" --yes

# copy another table's columns: export it, then create from the file
uv run ~/.claude/skills/onping-logtable-export/scripts/export_logtable.py "$ACCESS_TOKEN" <LJ> <uuid> well7.xlsx
uv run $S "$ACCESS_TOKEN" <LJ> --name "Well 8 Log" --group <group-id> --from well7.xlsx
```

## Flags

- `<LJ>` — the Lumberjack serial.
- `--name NAME` (required) — refused if a table on that LJ already has it.
- `--event-pid N` — the trigger; a PID, never a VPID. Required unless `--from`.
- `--event-name NAME` — the event column's header (default `eventDateTime`). Not with `--from`.
- `--column NAME=SOURCE[:TAG]` (repeatable) — one column, after the event column, in the order given.
  - The text is split at its **last** `=`, so NAME may contain `=` or `:`.
  - SOURCE is `<n>` for a PID or `<n> VPID` for a VPID, the text the export's `source:` row uses.
  - TAG defaults to `result`. It is a tag word in any case — `result`, `unit`,
    `description`, `pid`, `dateTime`, `date`, `time`, `writeable`, `company`,
    `companyId`, `site`, `siteId`, `location`, `locationId` — or a selector
    name (`Unit`, `UnitTagSelector`). `text` is refused: a log table cannot hold it.
- `--from FILE.xlsx` — take the columns, the event column included, from the
  four header rows of an `onping-logtable-export` file. Any `--column` flags
  are added after the file's columns. `--event-pid` and `--event-name` are
  refused with `--from` (exit 2).
- `--group ID` — the owning group (one of your owned groups). Without it the script lists the groups other tables on the LJ use and exits 2.
- `--yes`, `--dry-run` — see the warning.

## What `--from` copies, and what it loses

It reads rows 1–4 of the sheet `Sheet1` (or the first sheet) the way the
server's importer does: `event` in row 1 on the trigger column, then
`name: …`, `tag: …` and `source: …`. It copies each column's name, source and
tag, in the file's order, with the event column where the file puts it.

The export writes each column's name verbatim: a live export on 2026-10-28
gave back `name: Pretty Flow Label` for a column so named, not its key. It
does not carry everything:

- **Hidden columns** are not in the export. Unhide them before exporting, or add them with `--column`.
- **Layout** is not copied: column UUIDs, sort order, filters, widths, pagination and frozen settings.
- **A name containing `:`** exports but cannot be read back (the format allows one `:` per cell). The script names the cell.
- **Data rows** (row 5 on) are counted and ignored. A new table starts empty.

It is stricter than the server in two ways: exactly one column may be marked
`event` (the server takes the last), and two columns with the same name or the
same source and tag are refused. Tag words in the file are case-sensitive, as
on the server (`Result` is refused, with a hint to use `result`).

## Dashboard: not needed

A log table records from the version-1 upgrade on, whether or not it is on a
dashboard. Open it in OnPing at `/v3/onping/logtable/add?serial=<LJ>&tableId=<uuid>`,
or find it through search. Placing it on a dashboard is a separate widget and a
v3 dashboard save, which no skill does.

## Output

Any notes (`--from` file, ignored data rows), then `Schema version 1 (N column(s)):`
and the grid with every column marked new. On `--yes`: `POST source/create: OK -> <uuid>`,
`POST schema/upgrade: OK (version 1, N column(s))`, and the read-back result,
ending with `New log table: LJ <LJ> <uuid>`. Nothing to back up: nothing existed before.

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/logtable/<LJ>/source/create` | POST | LogTableSource, nil UUID, version 0, no schemas | the new UUID (JSON string) |
| `/logtable/<LJ>/source/schema/upgrade` | POST | the source at version 1 with the new schema (all columns) | the stored source |

Handlers: `onping/Handler/OnpingLogTable/Service.hs (postLogTableSourceCreateR, postLogTableSourceSchemaUpgradeR)`. Routes and notes: `_lj_table_routes/routes.py`. Column parsing and the header reader: `_lj_table_routes/logtable_template.py`.

## Permissions

The group must be one of your **owned** groups; otherwise `Permission Denied`
comes back as HTTP 500.

## Error Handling

- **Bad `--column` or `--from` file** — exit 1 naming the flag or the cell (`R3C2: unknown tag selector …`), before any request.
- **`--from` with `--event-pid`/`--event-name`, or neither `--from` nor `--event-pid`** — exit 2, before any request.
- **Missing `--group`** — exit 2 with hints; nothing posted.
- **Upgrade fails after create** — exit 1 naming the orphaned version-0 UUID and the `onping-logtable-delete` command.
- **Read-back mismatch** — exit 1 listing differences.
- **Permission Denied / token expired** — exit 1 with a hint.
- **`Routing index could not be found` (404)** — the LJ has no log-table routing; nothing can be created there.
