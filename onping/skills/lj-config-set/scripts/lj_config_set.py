# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "pyyaml"]
# ///
"""Set values of existing keys in a Lumberjack package's LAS dynamic config. MUTATING — requires --yes.

    lj_config_set.py SERIAL --package P KEY=VALUE [KEY:=JSON ...]
                     [--from-yaml FILE] [--restore BACKUP]
                     [--yes] [--dry-run] [--backup PATH] [--allow-noop]
                     [--allow-unsynced] [--wait SECONDS] [--show-secrets] [--token-stdin]

The access token comes from $ONPING_ACCESS_TOKEN, or from stdin with --token-stdin.

KEY=VALUE parses VALUE by the key's declared type; KEY:=JSON takes a raw JSON
value; --from-yaml takes a flat `key: value` map (some or all keys, e.g. an
lj-config-export file); --restore puts every key back to a backup's value.
Every value is checked against its key's ConfigType before anything is sent.
Only values change: the stored key list, key order and types are kept.

Without --yes this prints the preview and writes nothing; --dry-run wins. With
--yes: refuse unless is-storage-synced is true (override: --allow-unsynced),
write a 0600 backup, re-read and abort if the package changed, POST the
patched PackageConfig, wait for the device to acknowledge (--wait, default
60 s), read back, and print an `undo:` command.

A real change makes las-local on the device rewrite the package's YAML and
RESTART its service (pkgConfMonitorName). A same-value write changes nothing on
the device; it is skipped unless --allow-noop.

Exit codes: 0 ok/preview/no-op, 1 request failure, concurrent change or
read-back mismatch, 2 usage or validation (nothing sent), 3 refused by a
preflight check: not an owner, storage not in sync (nothing sent), 4 saved in
the cloud but the device has not acknowledged within --wait.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _las_routes import config_types as ct  # noqa: E402
from _las_routes import configs as cf  # noqa: E402
from _las_routes.las_http import LASError, get_json, post_json  # noqa: E402
from _token_input import shapes, token_source  # noqa: E402

POLL_SECONDS = 2.0


class Usage(Exception):
    """A usage or validation error: exit 2, nothing sent."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("serial", metavar="SERIAL", type=shapes.int_arg)
    p.add_argument("assign", metavar="KEY=VALUE|KEY:=JSON", nargs="*")
    p.add_argument("--package", metavar="P",
                   help="the package (pkgConfName); with --restore, defaults to the backup's")
    p.add_argument("--from-yaml", metavar="FILE", help="flat key: value YAML of new values")
    p.add_argument("--restore", metavar="BACKUP", help="restore every key from a backup file")
    p.add_argument("--yes", action="store_true", help="actually write (default: preview only)")
    p.add_argument("--dry-run", action="store_true", help="preview only; wins over --yes")
    p.add_argument("--backup", metavar="PATH",
                   help="backup path (default ./lj-config-<serial>-<package>-<UTC>.backup.json)")
    p.add_argument("--allow-noop", action="store_true",
                   help="send the write even when no value changes")
    p.add_argument("--allow-unsynced", action="store_true",
                   help="write even when the device has not acknowledged earlier changes")
    p.add_argument("--wait", metavar="SECONDS", type=float, default=60.0,
                   help="how long to wait for the device to acknowledge (default 60)")
    p.add_argument("--show-secrets", action="store_true", help="print CPassword values")
    args = token_source.parse(p, argv, is_id=shapes.is_int, intermixed=True)  # KEY=VALUE may follow options
    if args.restore and (args.assign or args.from_yaml):
        p.error("--restore cannot be combined with KEY=VALUE or --from-yaml")
    if not (args.assign or args.from_yaml or args.restore):
        p.error("nothing to set: give KEY=VALUE, KEY:=JSON, --from-yaml or --restore")
    if not args.package and not args.restore:
        p.error("--package is required")
    if args.wait < 0:
        p.error("--wait must be >= 0")
    return args


# ------------------------------------------------------------------- inputs
def split_assign(item: str) -> tuple[str, str, bool]:
    """KEY=VALUE -> (KEY, VALUE, False); KEY:=JSON -> (KEY, JSON, True)."""
    if "=" not in item:
        raise Usage(f"{item!r}: expected KEY=VALUE or KEY:=JSON")
    key, value = item.split("=", 1)
    raw = key.endswith(":")
    if raw:
        key = key[:-1]
    if not key:
        raise Usage(f"{item!r}: empty key")
    return key, value, raw


def load_yaml(path: str) -> dict[str, Any]:
    import yaml  # pyyaml, declared in the PEP 723 block

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except OSError as e:
        raise Usage(f"--from-yaml {path}: {e.strerror}") from e
    except yaml.YAMLError as e:
        raise Usage(f"--from-yaml {path}: not valid YAML ({e})") from e
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        raise Usage(f"--from-yaml {path}: expected a flat map of key: value")
    return data


def load_backup(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise Usage(f"--restore {path}: {e.strerror}") from e
    except ValueError as e:
        raise Usage(f"--restore {path}: not JSON ({e})") from e


def collect_updates(args, pkg: dict) -> tuple[dict[str, Any], list[str]]:
    """Every named key -> its new value, and the problems (all of them)."""
    errs: list[str] = []
    updates: dict[str, Any] = {}

    def put(key: str, value: Any, origin: str) -> None:
        if key in updates:
            errs.append(f"{key}: named more than once ({origin})")
            return
        updates[key] = value

    if args.from_yaml:
        for k, v in load_yaml(args.from_yaml).items():
            put(k, v, "--from-yaml")
    for item in args.assign:
        key, text, raw = split_assign(item)
        e = cf.entry(pkg, key)
        if raw:
            try:
                put(key, json.loads(text), "KEY:=JSON")
            except ValueError:
                errs.append(f"{key}: {text!r} is not valid JSON")
            continue
        if e is None:
            put(key, text, "KEY=VALUE")  # build_patch reports the unknown key
            continue
        try:
            put(key, ct.from_cli(e.get("configType"), text), "KEY=VALUE")
        except ValueError as ex:
            shown = "(hidden)" if ct.has_password(e.get("configType")) else ""
            msg = str(ex) if not shown else "not a valid value for its type"
            errs.append(f"{key} ({ct.type_name(e.get('configType'))}): {msg}")
    return updates, errs


# --------------------------------------------------------------------- flow
def poll_synced(token: str, serial: int, wait: float) -> tuple[bool | None, int]:
    """(True once is-storage-synced is true, False if it never was, None if polling
    failed; the number of polls)."""
    attempts = int(wait // POLL_SECONDS) + 1
    for i in range(attempts):
        try:
            if get_json(token, "storage_synced", serial=serial) is True:
                return True, i + 1
        except LASError as e:
            print(f"WARNING: could not read is-storage-synced: {e}", file=sys.stderr)
            return None, i + 1
        if i + 1 < attempts:
            time.sleep(POLL_SECONDS)
    return False, attempts


def undo_line(serial: int, package: str, backup: str) -> str:
    script = shlex.quote(str(Path(__file__).resolve()))
    return (f'undo: uv run {script} {serial} --package {shlex.quote(package)} '
            f"--restore {shlex.quote(backup)} --yes")


def run(args) -> int:
    serial = args.serial
    backup_in = load_backup(args.restore) if args.restore else None
    if backup_in is not None and not args.package:
        args.package = (backup_in.get("packageConfig") or {}).get("pkgConfName") \
            if isinstance(backup_in, dict) else None
        if not args.package:
            raise Usage(f"--restore {args.restore}: the backup names no package")
    if args.backup and os.path.exists(args.backup):
        raise Usage(f"--backup {args.backup} exists; choose a new path")

    if cf.profile_for(get_json(args.access_token, "profiles"), serial) is None:
        print(f"Lumberjack {serial} is not in your owned profiles. Writing configs needs "
              "Owner of the Lumberjack's group. Nothing was sent.", file=sys.stderr)
        return 3
    synced = get_json(args.access_token, "storage_synced", serial=serial)
    configs = get_json(args.access_token, "configs", serial=serial) or []
    pkg = cf.find_package(configs, args.package)
    if pkg is None:
        raise Usage(f"No package {args.package!r} on Lumberjack {serial}. Packages: "
                    f"{', '.join(cf.package_names(configs)) or 'none'}")

    if backup_in is not None:
        updates, errs = cf.restore_updates(backup_in, serial, pkg)
    else:
        updates, errs = collect_updates(args, pkg)
    new_pkg, changes, perrs = cf.build_patch(pkg, updates)
    errs += perrs
    if errs:
        raise Usage("Refusing to write; nothing was sent:\n  " + "\n  ".join(errs))

    real = [c for c in changes if c.changed]
    monitor = pkg.get("pkgConfMonitorName") or ""
    print(f"Lumberjack {serial}  package {pkg.get('pkgConfName')}  "
          f"monitor {monitor or '(none)'}")
    print(f"  path {pkg.get('pkgConfPath')}")
    print(f"  storage synced: {'yes' if synced is True else 'no'}")
    print(f"  {len(real)} change(s) of {len(changes)} key(s) named:")
    for c in changes:
        print(cf.change_line(c, args.show_secrets))
    if real:
        if monitor:
            print(f"  NOTE: applying this restarts the service {monitor!r} on the Lumberjack.")
        else:
            print("  WARNING: this package has no monitor name, so las-local cannot restart "
                  "its service; the new values may not take effect until it restarts.")
    if not real and not args.allow_noop:
        print("No value changes; nothing to send. (--allow-noop sends it anyway; it does "
              "not rewrite or restart anything on the device.)")
        return 0
    if args.dry_run:
        print("\nDRY RUN — nothing was written.")
        return 0
    if not args.yes:
        print("\nPREVIEW ONLY — nothing was written. Re-run with --yes to apply.")
        return 0
    if synced is not True and not args.allow_unsynced:
        print("Refusing: is-storage-synced is not true, so the device has not acknowledged "
              "earlier changes (it may be offline). A write now would apply, with a restart, "
              "whenever it reconnects. Pass --allow-unsynced to queue it anyway. Nothing was "
              "sent.", file=sys.stderr)
        return 3

    backup_path = args.backup or \
        f"./lj-config-{serial}-{pkg.get('pkgConfName')}-{cf.utc_stamp()}.backup.json"
    backup_path = cf.write_private(backup_path, cf.dump_json(cf.backup_doc(serial, pkg, configs)))
    print(f"Backup (mode 0600, holds CPassword values): {backup_path}")

    again = cf.find_package(get_json(args.access_token, "configs", serial=serial) or [], args.package)
    if again is None or not cf.same_package(pkg, again):
        print("Aborting: the package's config changed since it was read. Nothing was sent; "
              "re-run to preview against the new values.", file=sys.stderr)
        return 1

    try:
        post_json(args.access_token, "configs_post", new_pkg, serial=serial)
    except LASError as e:
        print(f"The write failed: {e}\nCheck the stored values with lj-config-list; the "
              f"backup is {backup_path}.", file=sys.stderr)
        return 1
    print("POST configs: 200 (saved in the cloud replica)")

    acked, polls = poll_synced(args.access_token, serial, args.wait)
    code = 0
    try:
        got = cf.find_package(get_json(args.access_token, "configs", serial=serial) or [], args.package)
    except LASError as e:
        print(f"Read-back failed: {e}", file=sys.stderr)
        got = None
        code = 1
    if got is not None:
        diffs = cf.schema_mismatches(new_pkg, got, args.show_secrets)
        if diffs:
            print("Read-back MISMATCH:\n  " + "\n  ".join(diffs), file=sys.stderr)
            code = 1
        else:
            print(f"Read-back: all {len(cf.schema(got))} key(s) match what was sent.")
    elif code == 0:
        print("Read-back: the package is missing from the configs.", file=sys.stderr)
        code = 1
    if acked:
        print(f"Device acknowledged (is-storage-synced: true at poll {polls}, "
              f"about {(polls - 1) * POLL_SECONDS:g}s after the POST).")
    elif code == 0:
        print(f"The device has not acknowledged within {args.wait:g}s. The change is saved in "
              "the cloud and will apply, with a service restart, when the device "
              "acknowledges. Check later with lj-config-list.", file=sys.stderr)
        code = 4
    print(undo_line(serial, pkg.get("pkgConfName"), backup_path))
    return code


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except Usage as e:
        print(str(e), file=sys.stderr)
        return 2
    except FileExistsError as e:
        print(f"Refusing to overwrite {e.filename}; choose a new --backup path.", file=sys.stderr)
        return 2
    except LASError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
