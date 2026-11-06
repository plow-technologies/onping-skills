---
name: lj-config-list
description: List a Lumberjack's LAS dynamic configs — the per-package editable keys (poll intervals, ports, MQTT URIs, log levels) that OnPing's LAS pages edit — with each key's type and value, the device sync state, and whether you own the Lumberjack. CPassword values are masked unless --show-secrets. Also lists the Lumberjacks you own (--lumberjacks). Read-only.
allowed-tools: Bash(uv run *)
---

# Lumberjack Config — List

Read the LAS dynamic configs of one Lumberjack: one `PackageConfig` per
installed package that uses the editable-config library, each with a list of
`{configKey, configType, configValue}`. Read-only: it sends GETs only.

## Related Skills

- **onping-login** — get an access token
- **lj-config-export** — save one package's config to a file
- **lj-config-set** — change values (live data)
- **lj-profile** — find a Lumberjack by OnPing location ID

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/lj-config-list/scripts/lj_config_list.py
uv run $S --lumberjacks --name <substring>    # find the serial
uv run $S <serial>                            # packages
uv run $S <serial> --package single-well-tflow
uv run $S <serial> --package <pkg> --json
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

## Flags

- `SERIAL` — the Lumberjack serial (the `lumberjackId` that `lj-profile` reports).
- `--package P` — every key of package `P` (its `pkgConfName`), with type and value.
- `--show-secrets` — print `CPassword` values. Without it they show as `********`
  (also inside `CMaybe` / `CList`, and in `--json`).
- `--json` — the same data as JSON.
- `--lumberjacks [--name SUBSTR]` — instead of a serial: the Lumberjacks you
  OWN (serial, name, arch, group, URL). `lumberjackPassword` is never printed.

## Output

The header line gives the Lumberjack's name, `owner: yes|no` (whether it is in
your owned profiles; `lj-config-set` and `lj-config-export` need Owner),
`storage synced` (whether the device has acknowledged every change the cloud
holds), and `bridge up`. Then one line per package: name, monitor (the service
las-local restarts after a change; `(no monitor)` means it cannot), key count
and YAML path on the device.

`bridge up` is usually `unknown`: OnPing's `is-mqtt-bridge-up` answered `null`
for a live, synced Lumberjack, because the cloud does not track device-side
bridges. Use `storage synced` to judge whether the device is reachable.

Exit codes: 0 ok, 1 request failure or unknown package, 2 usage.

## API Reference

| Route | Role | Used for |
|-------|------|----------|
| `GET /las/api/v1/lumberjack/configs?serial=N` | Member | the configs |
| `GET /las/api/v1/is-storage-synced?serial=N` | Member | sync state |
| `GET /las/api/v1/is-mqtt-bridge-up?serial=N` | Member | bridge state (often null) |
| `GET /las/api/v1/lumberjack/profiles` | — | name and ownership (filtered to owned groups) |

A 403 (`"User is not authorized to access Lumberjack"`) means you are not a
member of the Lumberjack's group. las-server errors arrive as OnPing 500s; the
skill prints las-server's own status and message.

Tests (offline):

```bash
uv run --with pytest --with requests pytest onping/skills/lj-config-list/tests
```
