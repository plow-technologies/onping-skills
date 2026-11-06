---
name: lj-config-set
description: Change values of existing keys in a Lumberjack package's LAS dynamic config (POST /las/api/v1/lumberjack/configs), validating every value against the key's declared ConfigType first. Keeps the stored key list, order and types. MUTATING — previews by default, writes only with --yes, refuses while the device is out of sync, backs up, waits for the device to acknowledge, reads back, prints an undo command. A real change restarts the package's service on the Lumberjack.
allowed-tools: Bash(uv run *)
---

# Lumberjack Config — Set

> **WARNING: with `--yes` this skill changes live data.** Without `--yes` (or
> with `--dry-run`, which wins over `--yes`) it previews and changes nothing.
> With `--yes` it first writes a backup and prints an `undo:` command that
> restores it. A changed value is saved in OnPing's LAS replica, synced to the
> Lumberjack and written to the package's YAML, and the package's service (its
> monitor) is **restarted**, so data collection or control by that package
> pauses briefly. A bad value can leave it failing at start-up.

## Related Skills

- **lj-config-list** — see keys, types, values and sync state first
- **lj-config-export** — save a package's YAML to edit and feed to `--from-yaml`
- **lj-deploy** — installs packages; a package upgrade does NOT refresh its key list

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/lj-config-set/scripts/lj_config_set.py
uv run $S <serial> --package single-well-tflow wait-time=30          # preview
uv run $S <serial> --package single-well-tflow wait-time=30 --yes    # write
uv run $S <serial> --package <pkg> 'hosts:=["a","b"]' maybe-port:=null
uv run $S <serial> --package <pkg> --from-yaml edited.yaml --yes
uv run $S <serial> --restore ./lj-config-<serial>-<pkg>-<UTC>.backup.json --yes
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

## Values

- `KEY=VALUE` — `VALUE` is read by the key's type: `CInteger` / `CPort`
  digits; `CFloat` a number (`nan`/`inf` refused); `CBool` `true`/`false`;
  `CText` / `CPassword` / `CURL` the text as typed; `CMaybe T` `null` or a `T`;
  `CList T` a JSON array.
- `KEY:=JSON` — a raw JSON value (e.g. the string `"null"` for a `CMaybe CText`
  is `key:='"null"'`).
- `--from-yaml FILE` — a flat `key: value` map of some or all keys (an
  `lj-config-export` file works). Quote text that YAML would read as a
  boolean or number (`'on'`, `'0123'`); an unquoted one is refused for a text key.
- `--restore BACKUP` — every key back to the backup's value. Refused if the
  backup's serial, package, keys or types differ from what is stored.

Every value is validated before anything is sent, and every problem is
reported (exit 2): unknown key, key named twice, value of the wrong type,
`CPort` outside 0-65535, whitespace in a `CURL`, a key whose stored type tag is
unknown. Only `configValue`s change; adding, removing or retyping keys is not
supported.

## Flags

- `--yes` — write. `--dry-run` — preview only (wins).
- `--backup PATH` — backup path (must not exist). Default
  `./lj-config-<serial>-<package>-<UTC>.backup.json`. The backup holds the
  package as read plus every package's config, with `CPassword` values in
  plaintext, mode `0600`.
- `--allow-noop` — send even when no value changes. Normally skipped: an
  identical config makes las-local rewrite nothing and restart nothing.
- `--allow-unsynced` — write even when `is-storage-synced` is false.
- `--wait SECONDS` — how long to wait for the device to acknowledge (default 60).
- `--show-secrets` — show `CPassword` values in the preview. Without it a
  changed password shows as `"********" -> "********" (changed)`.

## What --yes does

1. Checks that you own the Lumberjack (owned profile list) — else exit 3.
2. Refuses if `is-storage-synced` is not true (the device has not acknowledged
   earlier changes; it may be offline) — exit 3, unless `--allow-unsynced`.
3. Writes the backup.
4. Re-reads the configs; aborts (exit 1, nothing sent) if the package changed.
5. POSTs the full `PackageConfig` with only the named values changed.
6. Polls `is-storage-synced` every 2 s for up to `--wait` seconds.
7. Reads back and compares every key; a mismatch exits 1.
8. Prints `undo: uv run … --restore <backup> --yes`.

## When the Lumberjack is offline

OnPing accepts the write (200) and las-server saves it even when the device's
MQTT bridge is down; nothing on the server checks the bridge. The device gets
the change when it reconnects (las-local resyncs its RON store) and then
rewrites the YAML and restarts the service — at that later time. So the skill
refuses by default when storage is out of sync, and exits **4** (saved in the
cloud, not acknowledged by the device) when the device does not acknowledge
within `--wait`. `is-mqtt-bridge-up` cannot be used to tell: it answers `null`
even for a live Lumberjack.

## Caveats

- A package with an empty monitor name (`(no monitor)` in `lj-config-list`):
  las-local writes the YAML but its restart call fails silently, so the new
  value may not take effect until the service restarts some other way. The
  preview warns.
- The POST replaces the whole schema. The re-read before the POST narrows,
  but cannot close, the window in which someone else's edit is overwritten.

Exit codes: 0 ok / preview / no-op, 1 request failure, concurrent change or
read-back mismatch, 2 usage or validation (nothing sent), 3 not an owner or
storage not in sync (nothing sent), 4 saved but not acknowledged by the device.

## API Reference

| Route | Role |
|-------|------|
| `GET /las/api/v1/lumberjack/profiles` | ownership precheck |
| `GET /las/api/v1/lumberjack/configs?serial=N` | Member — read, re-read, read-back |
| `POST /las/api/v1/lumberjack/configs?serial=N` | Owner — body: one `PackageConfig`; 200 empty |
| `GET /las/api/v1/is-storage-synced?serial=N` | Member — preflight and acknowledgement |

Tests (offline):

```bash
uv run --with pytest --with requests --with pyyaml pytest onping/skills/lj-config-set/tests
```
