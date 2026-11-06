---
name: onping-generic-swd-get
description: Show one generic-SWD offload kiosk's configuration (name, lanes with their read PID, mask script, write PID and waiting-to-start value, and the status map), optionally its live lane states and recent tickets, and save it as a backup file that onping-generic-swd-update can restore. Read-only.
allowed-tools: Bash(uv run *)
---

# OnPing Generic SWD Get

Show one **generic-SWD kiosk**: the offload kiosk configuration, including Ticket Permissive kiosks. **Read-only**: it changes nothing, so there is no `--yes`.

A kiosk configuration has three parts:

- a **name**;
- **lanes**, each with a number, a **read PID** (the lane's state register), an optional **mask script** that turns the read value into a status value, a **write PID** (the register an offload start writes to) and a **waiting-to-start value** (the value written to it);
- a **status map** from masked read values to `Available`, `WaitingToStart`, `Pumping` or `Disabled(<message>)`.

## Use This Skill For

- Reading a kiosk's lanes and status map before changing them
- Checking what each lane reports now (`--live`)
- Reading the most recent tickets (`--tickets N`)
- Saving a backup you can restore with `onping-generic-swd-update ... replace --from FILE --yes` (`--output FILE`)

## Do Not Use This Skill For

- Finding a kiosk's UUID. Use `onping-generic-swd-list`.
- Changing a kiosk. Use `onping-generic-swd-update`.
- Starting an offload or changing a ticket. Use the OnPing UI.

## Related Skills

- `onping-login`: access tokens
- `onping-generic-swd-list`: find the kiosk UUID
- `onping-generic-swd-update`: change the configuration
- `onping-pid-locate`: look up a lane PID's location and current value

## Commands

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
GET=~/.claude/skills/onping-generic-swd-get/scripts/get_generic_swd.py
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

```
get_generic_swd.py TOKEN UUID [--live] [--tickets N] [--output FILE] [--json]
```

```bash
uv run "$GET" <kiosk-uuid>
uv run "$GET" <kiosk-uuid> --live --tickets 5
uv run "$GET" <kiosk-uuid> --output ./kiosk-backup.json
```

- The kiosk must be in a group you own or belong to; any other UUID is refused (exit 3) before its configuration is read. Members can read; only owners can change it. The server also checks your access to the kiosk's group on every kiosk route and answers HTTP 403 otherwise, including for a UUID that does not exist.
- The configuration comes from `POST /generic-swd/kiosk/config`. Each lane also shows the read PID's raw value, its masked value and the status it maps to, as the server reports them. A masked value of `null` with a raw value means the mask script did not evaluate.
- The skill checks the stored configuration with the same rules `onping-generic-swd-update` applies, and lists any problems. An update has to fix them before it can write.
- `--live` reads `GET /generic-swd/kiosk/lanes/<uuid>`. The kiosk polls each lane's read PID in turn, so this takes about half a second per lane. One lane that fails (a PID that cannot be read, a mask script that does not evaluate, or a masked value with no status-map entry) fails the whole read.
- `--tickets N` reads the N most recent tickets (1 to 100) from `GET /generic-swd/kiosk/tickets/<N>/<uuid>`.
- If `--live` or `--tickets` fails, the configuration is still printed and the exit code is 1.
- `--output FILE` writes the configuration in the backup format (`"format": "onping-generic-swd-config/1"`, with the kiosk UUID). FILE must not exist yet (exit 2).
- `--json` prints `{"ok", "kiosk", "config", "lanes_reported", "stored_config_problems", "warnings", "live"?, "tickets"?, "output"?}`.

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Read |
| 1 | A read failed (the configuration, `--live` or `--tickets`) |
| 2 | Usage error (bad UUID, `--tickets` out of range, existing `--output`); no request sent |
| 3 | Refused: the kiosk is not in your groups, or your groups could not be read |

## Environment

- `ONPING_BASE_URL`: the server, default `https://onping.plowtech.net`.
- Requires `uv` and network access to OnPing. The script imports `_generic_swd_routes` from the sibling skills directory.

## Testing

```bash
uv run --with pytest --with requests pytest onping/skills/onping-generic-swd-get/tests
```

The tests are offline and use the in-memory server in `_generic_swd_routes/tests/gswd_fakes.py`.
