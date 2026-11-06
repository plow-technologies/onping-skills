---
name: onping-create-singlewell-manual
description: Create one OnPing singlewell-manual location on a Lumberjack through POST /singlewellmanual/location/add. MUTATING — previews by default, posts only with --yes, refuses a group you do not own, a site outside the company, or a duplicate name at the site, and reads every sent field back with /singlewellmanual/get/loc. Add parameters afterwards with onping-import-singlewell-manual.
allowed-tools: Bash(uv run *)
---

# OnPing Singlewell Manual — Create Location

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> It creates a manual location on a live Lumberjack. It previews by default
> and changes nothing until you pass `--yes`; `--dry-run` also previews and
> wins over `--yes`. Remove the location with `onping-delete-singlewell-manual`,
> but the delete leaves the MySQL location row and the single-well extras
> record behind (servers before the 2026.11.5.1 fix also left the group join and
> the switcher index), and no route removes them.

One location per run. The location is created with no parameters
(`locationData: []`), empty notes unless `--notes` is given, and no
coordinates. The Lumberjack is named by serial: its URL comes from the LAS
profile (`lumberjackUrl`), never from a typed URL.

The add route is **not transactional**. It writes the MySQL row, the switcher
index, the manual record (Step 1), the Mongo location (Step 2), the extras
record (Step 3) and the group join (Step 4), and stops at the first failure
without undoing anything. The skill checks that you own the group before it
sends anything. A server with the 2026.11.5.1 fix checks it again and answers
403 for a group you do not own.

## Related Skills

- **onping-login** — get the access token
- **lj-profile** — find a Lumberjack serial
- **onping-export-singlewell-manual** — see the locations already on the LJ
- **onping-import-singlewell-manual** — add parameters to the new location
- **onping-delete-singlewell-manual** — remove it again
- **onping-add-singlewell-manual** — the request and response schema (read-only)

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-create-singlewell-manual/scripts/create_location.py
uv run $S --lj <serial> --company <company-id> --site <site-id> --group <group-id> --name "Well 7 Manual"
uv run $S --lj <serial> --company <company-id> --site <site-id> --group <group-id> --name "Well 7 Manual" --yes
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

## Flags

- `--lj SERIAL` (required) — the Lumberjack; refused (exit 3) if it has no LAS profile with a `lumberjackUrl`.
- `--company ID`, `--site ID` (required) — refused if the site is not a live site of the company.
- `--group GID` (required) — must be one of your owned groups (`/permissions/groups/ownership`).
- `--name NAME` (required) — refused if a manual location at the site already has it.
- `--port N` — the manual server port; default `13001`, the OnPing UI default.
- `--notes TEXT` — default empty.
- `--yes` — create. `--dry-run` — preview only; wins over `--yes`.
- `--json` — print one JSON report instead of text.

## Output

The body that would be sent, the checks that passed, and the delete command
that undoes it. With `--yes`: `created location <id>`, then
`Verified: get/loc <id> matches every field sent (...)` and the delete
command with the new id. A partial create prints the failed step, the
location id, the records that now exist and the ones that do not.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Preview, or a create the read-back confirmed |
| 1 | A request failed before anything was written (including HTTP 400) |
| 2 | Usage error |
| 3 | Preflight refusal: no LJ URL, group not owned, site not in company, duplicate name |
| 4 | Partial create, lost response, unrecognised answer, or read-back mismatch |

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/las/api/v1/lumberjack/profiles` | GET | — | `[[serial, profile]]`; the URL is `lumberjackUrl` |
| `/permissions/groups/ownership` | GET | — | `[{key: gid, value: {name, ...}}]` |
| `/json/listers/siteLister?getCompanyLookupList=<company>` | GET | — | `[{key, value: {cid, delete, name, refId}}]` |
| `/singlewellmanual/locations` | POST (read-only) | `[siteId]` | `[{refId, name, site, company, url, slaveId, delete}]` |
| `/singlewellmanual/location/add` | POST | `ManualLocationConfig` (see `onping-add-singlewell-manual`) | 200 `{"int": id}`; 400 parse error; 500 `{"error": "... Step N ... LocationIdRef id ..."}` |
| `/singlewellmanual/get/loc` | POST (read-only) | `id` (bare integer) | the full config, or 400 `{"error"}` |

Handlers: `onping/Handler/SingleWellManual/Service.hs`. Routes, the step
table and the residue: `_singlewell_manual_routes/routes.py`.

## Permissions

You must own the group. The skill checks this in its preflight and refuses
otherwise (exit 3). A server with the 2026.11.5.1 fix enforces the same rule and
answers 403 before it writes anything. A server without the fix checked only
that you were logged in, so on such a server the skill's check is the only
one.

## Error Handling

- **Partial create (500 naming a step)** — exit 4. The output lists the id and
  the records left. If the manual record exists, the delete skill removes it
  and any Mongo location; nothing removes the MySQL row or switcher index.
- **Lost response** — exit 4. The skill looks for the name in the site listing
  and prints any id it finds. It never retries.
- **HTTP 400** — exit 1; the server did not parse the body.
- **HTTP 403** — exit 4 today: the script has no 403 branch, so it prints
  `UNKNOWN: HTTP 403: <body>` and then looks for the name in the site listing
  like a lost response. A fixed server checks the group before it writes
  anything, so on a 403 nothing was written, and the name search should find
  nothing. Check that your token's account owns the group. The skill's own
  ownership check normally refuses first (exit 3).
- **Token expired** — exit 1; get a new token with `onping-login`.

## Tests

```bash
uv run --with pytest --with requests pytest onping/skills/onping-create-singlewell-manual/tests
```
