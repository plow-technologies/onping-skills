---
name: lj-config-export
description: Export one Lumberjack package's LAS dynamic config to a local file — the flat key/value YAML from OnPing's configs/export route, or the PackageConfig JSON with types (--json). Needs Owner. The file is created 0600 and never overwritten without --force; it holds CPassword values in plaintext. Read-only against OnPing.
allowed-tools: Bash(uv run *)
---

# Lumberjack Config — Export

Save one package's dynamic config. The YAML form is what OnPing's LAS page
exports and what `lj-config-set --from-yaml` accepts back. Nothing on the
server changes.

> **The export holds secrets.** `CPassword` values are written as the server
> returns them (unmasked), because the file is meant to be restorable. The file
> is created with mode `0600`. Do not commit it or paste it.

## Related Skills

- **lj-config-list** — find the serial and the package names
- **lj-config-set** — apply an edited file with `--from-yaml`

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
S=~/.claude/skills/lj-config-export/scripts/lj_config_export.py
uv run $S <serial> --package single-well-tflow              # ./single-well-tflow.yaml
uv run $S <serial> --package single-well-tflow -o tflow.yaml
uv run $S <serial> --package single-well-tflow --json -o -  # stdout
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

## Flags

- `--package P` (required) — the package's `pkgConfName`.
- `-o FILE` — output path; `-` writes to stdout. Default `./<package>.yaml`
  (`.json` with `--json`).
- `--force` — overwrite an existing file. Without it an existing file is
  refused before any request (exit 2).
- `--json` — write the `PackageConfig` JSON (with `configType`s) from
  `GET configs` instead of the YAML export.

## Rules

- Export needs **Owner** of the Lumberjack's group, even though it is a GET.
  The skill checks the owned profile list first and exits 3 if the serial is
  not there.
- An unknown package: OnPing answers 500 around las-server's 404; the skill
  prints "No configs for package P found for serial N" and exits 1.

Exit codes: 0 ok, 1 request failure or unknown package, 2 usage or existing
file, 3 not an owner.

## API Reference

| Route | Role |
|-------|------|
| `GET /las/api/v1/lumberjack/configs/export?serial=N&package=P` | Owner — `text/plain` YAML, keys sorted |
| `GET /las/api/v1/lumberjack/configs?serial=N` | Member — with `--json` |
| `GET /las/api/v1/lumberjack/profiles` | the ownership precheck |

Tests (offline):

```bash
uv run --with pytest --with requests pytest onping/skills/lj-config-export/tests
```
