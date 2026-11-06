---
name: onping-generic-swd-list
description: List the generic-SWD offload kiosks (including Ticket Permissive kiosks) in the OnPing groups you own or belong to, with each kiosk's UUID, name, group and whether you own that group. Read-only. Use it to find the kiosk UUID that onping-generic-swd-get and onping-generic-swd-update need.
allowed-tools: Bash(uv run *)
---

# OnPing Generic SWD List

List the **generic-SWD kiosks** you can see: the saltwater-disposal offload kiosks that drivers use to start an offload, including the Ticket Permissive kiosks. **Read-only**: it changes nothing, so there is no `--yes`.

A kiosk belongs to one OnPing permission group. This skill only asks for the kiosks of groups you own or are a member of, and it marks each kiosk `owned` when you own its group. You need to own the group to change the kiosk with `onping-generic-swd-update`.

## Use This Skill For

- Finding a kiosk's UUID by its name
- Seeing which kiosks are in a group, and which of them you can change (`owned`)

## Do Not Use This Skill For

- Reading a kiosk's lanes, status map or tickets. Use `onping-generic-swd-get`.
- Changing a kiosk. Use `onping-generic-swd-update`.
- Creating, deleting or moving a kiosk to another group, or starting an offload. Use the OnPing UI.

## Related Skills

- `onping-login`: access tokens
- `onping-generic-swd-get`: one kiosk's configuration, live lane states and tickets
- `onping-generic-swd-update`: change a kiosk's name, lanes or status map

## Commands

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
LIST=~/.claude/skills/onping-generic-swd-list/scripts/list_generic_swd.py
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

```
list_generic_swd.py TOKEN [--group GID ...] [--owned-only] [--json]
```

```bash
uv run "$LIST"                       # every kiosk in your groups
uv run "$LIST" --owned-only          # only kiosks you can change
uv run "$LIST" --group <group-id>    # one group (repeatable)
uv run "$LIST" --json
```

- The skill reads your owned groups (`GET /permissions/groups/ownership`) and member groups (`GET /permissions/groups/membership`), then asks `POST /generic-swd/kiosk/configs` for the kiosks of those groups.
- `--group` must be a group you own or belong to. Any other group is refused (exit 3) before any kiosk request. The server also returns kiosks only for groups you own or belong to.
- If either group read fails, the skill refuses (exit 3) rather than guess.
- `--json` prints `{"ok", "count", "kiosks": [{"uuid", "name", "group_id", "group_name", "owned", "ip", "port"}]}`.
- The kiosk list route may also return other kiosk kinds in your groups. `onping-generic-swd-get` fails (exit 1) for a kiosk that is not a generic-SWD kiosk.

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Listed (possibly zero kiosks) |
| 1 | The kiosk list request failed |
| 2 | Usage error; no request sent |
| 3 | Refused: a group outside your groups, or your groups could not be read |

## Environment

- `ONPING_BASE_URL`: the server, default `https://onping.plowtech.net`.
- Requires `uv` and network access to OnPing. The script imports `_generic_swd_routes` (and, through it, `_pid_routes`) from the sibling skills directory.

## Testing

```bash
uv run --with pytest --with requests pytest onping/skills/onping-generic-swd-list/tests
```

The tests are offline and use the in-memory server in `_generic_swd_routes/tests/gswd_fakes.py`.
