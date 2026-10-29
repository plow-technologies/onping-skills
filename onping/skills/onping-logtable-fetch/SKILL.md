---
name: onping-logtable-fetch
description: Read an OnPing log table's recorded rows newest first, with the row count and the newest event time and its age — "is it still recording?" — optionally between --since/--until (UTC, inclusive, minute precision) or from an older schema --version. Read-only.
allowed-tools: Bash(uv run *)
---

# OnPing Log Table — Fetch

Read the rows a log table has recorded. The newest event time tells you whether
the trigger PID is still updating.

> **Read-only** — no `--yes` gate. The query route is a POST, but it only reads.

> **One schema version at a time.** Every column edit starts a new, empty
> version. Right after an edit the current version has no rows; older rows are
> under `--version N` (see `onping-logtable-get` for the list).

> **Time bounds are UTC, inclusive, to the minute.** The server compares
> `strftime('%Y-%m-%d %H:%M', …)`, so `--until "2026-01-01 12:00"` includes
> 12:00:59.

## Related Skills

- **onping-logtable-get** — the columns and versions
- **onping-datatable-fetch** — the data-table row the log table mirrors

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-logtable-fetch/scripts/fetch_logtable.py
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --limit 1                     # is it recording?
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --since "2026-01-01" --until "2026-01-02 06:00"
uv run $S "$ACCESS_TOKEN" <LJ> <table-uuid> --version 3 --json
```

## Flags

- `--limit N` (default 10), `--offset N` — newest first.
- `--since UTC`, `--until UTC` — `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`, or with `:SS`. A bare date means 00:00, so `--until 2026-01-02` stops at 00:00:59 that day.
- `--version N` — read an older schema version's rows.
- `--json` — JSON with columns (key, selector, event) and rows.

## Output

Table name, version, `rows matching: N`, `newest event: <UTC> (<age> ago)`,
then one line per row: `row <id>: <column>: <value>; …`. Hidden columns are
included. Two columns with the same name are labelled `name@position`.

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/logtable/<LJ>/source/list` | GET | — | `[LogTableSource]` |
| `/logtable/<LJ>/source/content/query/v2` | POST (read-only) | the LogTableSource set to one version, with pagination, order, filters | `{queryResponseContent, queryResponseCount}` |

Handler: `onping/Handler/OnpingLogTable/Service.hs (postLogTableSourceContentQueryAndCountR)`. Routes and notes: `_lj_table_routes/routes.py`.

## Permissions

Owned-or-member groups.

## Error Handling

- **Bad date** — exit 1 naming the accepted formats.
- **No such version / UUID** — exit 1.
- **LJ has no routing / token expired** — exit 1 with a hint.
