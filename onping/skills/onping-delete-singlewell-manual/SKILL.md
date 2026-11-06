---
name: onping-delete-singlewell-manual
description: Delete one OnPing singlewell-manual location through POST /singlewellmanual/delete. MUTATING, no undo — previews by default, posts only with --yes, refuses a group you do not own or a location that still has parameters, backs up the full config first, and decides success from a read-back, never from the HTTP status or body (servers before the 2026.11.5.1 fix answered HTTP 200 for every outcome). Reports the records the server leaves behind.
allowed-tools: Bash(uv run *)
---

# OnPing Singlewell Manual — Delete Location

> **⚠️ WARNING: this skill changes live data, and there is no undo route.**
> It deletes a manual location's manual-server record and its Mongo location.
> It previews by default and changes nothing until you pass `--yes`;
> `--dry-run` also previews and wins over `--yes`. With `--yes` it first
> writes the full `get/loc` config to a backup. The backup is a record, not an
> undo: re-creating from it with `onping-create-singlewell-manual` gives a new
> location id and new parameter ids.

One location per run. Servers before the 2026.11.5.1 fix answered HTTP 200 for
every outcome, with `{"response": "Success"}` or `{"response": "<message>"}`.
Servers with the fix answer 200 `{"response": "Success"}` on success and 400,
403 or 500 with an `error` key otherwise. In both cases the skill prints the
status and body, ignores them for the verdict, and reads back.

**Gone** is defined by the older server's answers: `get/loc` answers
`failed to find single well manual location by id` **and** the site's manual
listing no longer contains the id. A server with the ownership fix does not
answer that way for a deleted location. It checks group ownership first, so once
the location is deleted `get/loc` answers 403 (`Insufficient permissions for
this location or group`), the same answer it gives for a location that never
existed. The skill reads that 403 as unknown.

> **Known limit on a fixed server.** A delete that worked (HTTP 200
> `Success`) can still end in **exit 4, `UNKNOWN: the read-back failed: HTTP
> 403 ...`**. This is expected, not a failure of the delete. It is safe: the
> backup is on disk, nothing is retried, and no second delete is sent. To
> confirm, list the locations at the site (`onping-locations` with the site id,
> or the location list in OnPing) and look for the id; if it is absent, the
> delete worked. Do not re-run the delete to check.

The delete **leaves behind** the MySQL location row and the single-well extras
record, plus the MySQL rows of any parameters (their PIDs are orphaned). No
route removes them. Servers before the 2026.11.5.1 fix also left the location
group join and the switcher index; the fixed server removes both. The skill
still lists all four in its output, so on a fixed server the list can name more
than is left. The skill checks that you own the location's group before it
sends anything, and the fixed server checks it again (403 otherwise).

## Related Skills

- **onping-login** — get the access token
- **onping-export-singlewell-manual** — find the location id and its parameters
- **onping-create-singlewell-manual** — create a location (or re-create from a backup)

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/onping-delete-singlewell-manual/scripts/delete_location.py
uv run $S <location-id>
uv run $S <location-id> --yes
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

## Flags

- `<location-id>` — the location's LocationIdRef (the `refId`).
- `--allow-parameters` — delete even though the location still has parameters. Without it, a location with parameters is refused (exit 3).
- `--backup PATH` — default `./singlewell-manual-<id>-<UTC>.backup.json`. An existing file is never overwritten (exit 1, nothing deleted).
- `--yes` — delete. `--dry-run` — preview only; wins over `--yes`.
- `--json` — print one JSON report instead of text.

## Output

The location's name, URL, port, company, site, group, parameter count, what
the delete removes and what it leaves. With `--yes`: the backup path, the
delete response, then `Verified gone: ...` and the records left behind.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Preview, or a delete the read-back confirmed |
| 1 | A request failed before anything was written, or the backup could not be written |
| 2 | Usage error |
| 3 | Refusal: no such location (older servers only; a fixed server answers 403, exit 1), group not owned, parameters present, or a partial record whose group cannot be read |
| 4 | Still present, partly deleted, or the read-back failed (on a fixed server this includes a delete that worked; see above) |

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/singlewellmanual/get/loc` | POST (read-only) | `id` (bare integer) | the full config; or 400 `{"error": "failed to find single well manual location by id"}` (also `... extras in mongo`, `... group id by location in mongo`) |
| `/permissions/groups/ownership` | GET | — | `[{key: gid, value: {name, ...}}]` |
| `/singlewellmanual/locations` | POST (read-only) | `[siteId]` | `[{refId, name, site, ...}]` |
| `/singlewellmanual/delete` | POST | `[id]` (exactly one) | 200 `{"response": "Success"}`; older servers also answered 200 `{"response": "<message>"}` on failure; fixed servers answer 400, 403 or 500 with `{"error": "<message>"}` |

Handlers: `onping/Handler/SingleWellManual/Service.hs`; delete logic
`deleteManualLocationById` in onping-core. Routes and residue:
`_singlewell_manual_routes/routes.py`.

## Permissions

You must own the location's group. The skill checks this before it sends
anything and refuses otherwise (exit 3). A server with the 2026.11.5.1 fix
enforces the same rule and answers 403 for a location in a group you do not
own, and for a location that does not exist. A server without the fix checked
only that you were logged in, so on such a server the skill's check is the only
one.

## Error Handling

- **No such location** — older servers: `get/loc` answers 400 `failed to find
  ... by id`, exit 3, nothing posted. Fixed servers answer 403 for a missing
  location (the same as for one in a group you do not own), which reads as
  unknown: exit 1, `Could not read location`, nothing posted. A non-manual
  location (fixed servers answer 400 `Not a singlewell-manual location`) also
  exits 1.
- **Successful delete read back as 403 (fixed servers)** — exit 4 UNKNOWN,
  although the delete worked. Safe: backup kept, nothing retried. Confirm by
  listing the site's locations (`onping-locations`).
- **Partial record** (`get/loc` names missing extras or a missing group) — exit 3; the group cannot be read, so the gate cannot pass.
- **Not Success, but read back as gone** — exit 0 with a note. If the
  Lumberjack is unreachable, `get/loc` reads a surviving manual record as
  missing; check again once it is reachable.
- **Still present / partly deleted** — exit 4; the backup is on disk.
- **Token expired** — exit 1; get a new token with `onping-login`.

## Tests

```bash
uv run --with pytest --with requests pytest onping/skills/onping-delete-singlewell-manual/tests
```
