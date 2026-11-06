---
name: onping-generic-swd-update
description: Change one generic-SWD offload kiosk's configuration (including Ticket Permissive kiosks) - rename it, set, add or delete a lane (read PID, mask script, write PID, waiting-to-start value), set or delete a status-map entry, or restore a whole configuration from a backup. MUTATING with `--yes` (preview by default, `--dry-run` wins). Needs ownership of the kiosk's group, and every new or changed lane PID must pass OnPing's PID-write ownership rule. Each write is validated, backed up, checked for concurrent edits, sent once and confirmed by read-back and a live lane read.
allowed-tools: Bash(uv run *)
---

# OnPing Generic SWD Update

> **⚠️ WARNING: this skill changes live data.**
> A kiosk's lanes decide which register an offload start writes to and which value it writes. A wrong **write PID** or **waiting-to-start value** makes the next offload drive the wrong equipment. A wrong **read PID**, **mask script** or **status map** shows drivers the wrong lane state, or makes the kiosk fail to show any lanes.
> **You must own the kiosk's group.** Every read or write PID that a change adds or changes must also pass OnPing's PID-write rule: its location has exactly one permission group and you own it. A changed write PID must be writeable. The skill refuses otherwise (exit 3).
> **Undo:** every write first saves a backup file, and every preview and report prints the `restore:` command (`replace --from <backup> --yes`).

It previews and changes nothing until you pass `--yes`. `--dry-run` also previews and wins over `--yes`.

## Use This Skill For

- Renaming a kiosk configuration (`name-set`)
- Changing a lane's read PID, mask script, write PID or waiting-to-start value (`lane-set`)
- Adding or removing a lane (`lane-add`, `lane-delete`)
- Adding, changing or removing a status-map entry, including disabled statuses with a message (`status-set`, `status-delete`)
- Restoring a backup from this skill or from `onping-generic-swd-get --output` (`replace --from`)

## Do Not Use This Skill For

- Creating or deleting a kiosk, or moving it to another group, changing its address, its token or its metered-volume settings. Use the OnPing UI.
- Starting an offload, or changing or cancelling a ticket. Use the OnPing UI. This skill never sends an offload request.
- Writing a value to a lane PID. Use `onping-pid-write`.
- Changing a PID's own mask. Use `onping-pid-mask`. The lane mask script is a separate, per-lane script.

## Related Skills

- `onping-login`: access tokens
- `onping-generic-swd-list`: find the kiosk UUID and check that you own its group
- `onping-generic-swd-get`: read the current configuration and live lane states; `--output` saves a backup
- `onping-pid-locate`: confirm a PID's location, description and current value before using it in a lane

## Commands

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
UPDATE=~/.claude/skills/onping-generic-swd-update/scripts/update_generic_swd.py
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

```
update_generic_swd.py TOKEN UUID name-set --name TEXT [common]
update_generic_swd.py TOKEN UUID lane-set --lane N [--read-pid P] [--write-pid P] [--wait-val X]
                      [--script TEXT | --script-file FILE | --clear-script] [common]
update_generic_swd.py TOKEN UUID lane-add --lane N --read-pid P --write-pid P --wait-val X
                      [--script TEXT | --script-file FILE] [common]
update_generic_swd.py TOKEN UUID lane-delete --lane N [common]
update_generic_swd.py TOKEN UUID status-set --value V (--status Available|WaitingToStart|Pumping | --disabled MESSAGE) [common]
update_generic_swd.py TOKEN UUID status-delete --value V [common]
update_generic_swd.py TOKEN UUID replace --from FILE [common]

common: [--yes] [--dry-run] [--backup PATH] [--no-live-check] [--json]
```

```bash
uv run "$UPDATE" <kiosk-uuid> status-set --value 6 --disabled "Lane closed"          # preview
uv run "$UPDATE" <kiosk-uuid> status-set --value 6 --disabled "Lane closed" --yes    # write
uv run "$UPDATE" <kiosk-uuid> lane-set --lane 1 --script 'output := input1 / 10.0;'
uv run "$UPDATE" <kiosk-uuid> lane-add --lane 2 --read-pid <pid> --write-pid <pid> --wait-val 1
uv run "$UPDATE" <kiosk-uuid> replace --from ./generic-swd-1a2b3c4d-20261028T150000Z.backup.json --yes
```

- Every subcommand builds the whole new configuration from the current one. The skill always sends the whole configuration, because the server replaces it as a unit. The server keeps the kiosk's token, metered-volume and attribute settings.
- `--script ''` and `--clear-script` both remove a lane's mask script. With no script the read value is used as it is.
- `--wait-val` and `--value` take finite numbers.
- `replace --from FILE` takes a backup file (it must name this kiosk's UUID, exit 3 otherwise) or a bare configuration object.
- `--backup PATH` chooses the backup file; it must not exist yet (exit 2). The default is `./generic-swd-<uuid8>-<UTC>.backup.json`.

## Validation

The whole new configuration must pass these checks, or the skill refuses (exit 3) and lists every problem:

- the name is non-blank, has no control characters and has at most 200 characters;
- there is at least one lane; lane numbers are integers from 0 to 2^64-1 and are unique;
- every read and write PID is a positive integer; the same PID as both read and write is only a warning;
- every waiting-to-start value is a finite number;
- a mask script has at most 4096 characters, no control characters other than tab and newline, balanced parentheses, no unterminated string literal, and assigns `output` (`output := ...`). The grammar itself is not checked here: the read-back after a write shows whether the kiosk could evaluate it;
- every status-map value is a finite number and appears once; every status is `Available`, `WaitingToStart`, `Pumping` or a disabled status with a non-blank message of at most 200 characters;
- the status map has at least one entry for each of `Available`, `WaitingToStart` and `Pumping`, because an offload waits for each of them in turn.

## What a write does

1. **Kiosk guard.** Reads your owned and member groups and lists the kiosks of those groups. The kiosk must be there and you must own its group. A failed group read refuses; it never passes. The server checks group access on its own side as well and answers HTTP 403 for a kiosk outside your groups. It accepts members of the group, so the owner requirement here is stricter on purpose.
2. **Read and edit.** Reads the configuration, applies the edit, validates it (above) and prints the diff. A change that changes nothing exits 0 with `no change` and sends nothing.
3. **PID guard.** Looks up every lane PID in the parameter lister. Each PID that the change adds or changes must:
   - be returned by the lister;
   - be at a location with exactly one permission group among the groups you can see, and you must own that group. The skill lists the locations of each of your owned and member groups to find this, which takes about 20 seconds for an account with about 1000 groups;
   - for a write PID, be `TagWriteable`.
   A PID that the change leaves alone only produces a warning. The preview lists every PID the change sets with its location and description, so you can confirm each one is the right register.
4. **Preview.** Without `--yes`, or with `--dry-run`, it stops here and prints the backup path and the restore command.
5. **Backup.** Writes the current configuration to the backup file. If that fails, nothing is sent (exit 3).
6. **Concurrent-edit check.** Reads the configuration again. If it changed since step 2, the skill refuses (exit 3); re-run it to see the new diff.
7. **Live check before.** Reads the live lane states (skip with `--no-live-check`). If that read already fails, the skill warns and does not use it as a check.
8. **Write.** Sends one `POST /generic-swd/config/lane/update`. It is never retried.
9. **Confirm.** Reads the configuration back. It must match what was sent. Every changed lane's mask script must evaluate (a raw value with no masked value fails), and the live lane read must still succeed if it succeeded in step 7. Any problem exits 4 and prints the restore command.

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Preview, dry run, no change, or written and confirmed |
| 1 | A read failed before the write, or the write was rejected and the read-back shows nothing changed |
| 2 | Usage error; no request sent |
| 3 | Refused by the kiosk guard, the PID guard, the validation, the concurrent-edit check or the backup; nothing written |
| 4 | Unknown or unconfirmed outcome (lost response, read-back mismatch, a mask that does not evaluate, a live read that now fails). Check with `onping-generic-swd-get --live` and restore with the printed command |

## Environment

- `ONPING_BASE_URL`: the server, default `https://onping.plowtech.net`.
- Requires `uv` and network access to OnPing. The script imports `_generic_swd_routes` and `_pid_routes` from the sibling skills directory.
- Backups are written to the current directory unless `--backup` says otherwise. Keep them until you have checked the kiosk.

## Testing

```bash
uv run --with pytest --with requests pytest onping/skills/onping-generic-swd-update/tests
```

The tests are offline. `_generic_swd_routes/tests/gswd_fakes.py` is an in-memory server that models the permission graph, mask evaluation, the all-or-nothing live lane read and the lane update. The tests also check that no offload, kiosk create, kiosk update or kiosk delete request is ever sent.
