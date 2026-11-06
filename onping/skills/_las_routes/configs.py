"""PackageConfig helpers: find, patch, diff, compare, back up, restore; profiles.

A `PackageConfig` is `{pkgConfName, pkgConfMonitorName, pkgConfPath,
pkgConfSchema: [{configKey, configType, configValue}]}`. A patch NEVER builds
a schema: it copies the stored one and replaces `configValue` for the keys
named, keeping every other key, the key order and every type, because
`POST configs` replaces the whole schema and las-local compares whole configs.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Any

from . import config_types as ct

BACKUP_KIND = "lj-config-backup"


# ------------------------------------------------------------------ packages
def package_names(configs: list[dict]) -> list[str]:
    return [c.get("pkgConfName", "") for c in configs]


def find_package(configs: list[dict], name: str) -> dict | None:
    for c in configs:
        if c.get("pkgConfName") == name:
            return c
    return None


def schema(pkg: dict) -> list[dict]:
    return pkg.get("pkgConfSchema") or []


def entry(pkg: dict, key: str) -> dict | None:
    for e in schema(pkg):
        if e.get("configKey") == key:
            return e
    return None


# --------------------------------------------------------------------- patch
@dataclass
class Change:
    key: str
    type: Any
    old: Any
    new: Any

    @property
    def changed(self) -> bool:
        return not ct.same_value(self.old, self.new)


def check_schema(pkg: dict) -> list[str]:
    """Problems with the stored schema that make any write unsafe."""
    seen: set[str] = set()
    errs = []
    for e in schema(pkg):
        k = e.get("configKey")
        if k in seen:
            errs.append(f"the stored schema names key {k!r} twice; refusing to write it")
        seen.add(k)
    return errs


def build_patch(pkg: dict, updates: dict[str, Any]) -> tuple[dict, list[Change], list[str]]:
    """(new PackageConfig, one Change per named key in schema order, errors)."""
    errs = check_schema(pkg)
    keys = [e.get("configKey") for e in schema(pkg)]
    for k in updates:
        if k not in keys:
            errs.append(f"{k}: no such key in package {pkg.get('pkgConfName')!r} "
                        f"(keys: {', '.join(keys) or 'none'})")
    new = copy.deepcopy(pkg)
    changes: list[Change] = []
    for e in schema(new):
        k = e.get("configKey")
        if k not in updates:
            continue
        v = updates[k]
        problems = ct.validate(e.get("configType"), v, k)
        if problems:
            errs += problems
            continue
        changes.append(Change(k, e.get("configType"), e.get("configValue"), v))
        e["configValue"] = v
    return new, changes, errs


def same_schema(a: list[dict], b: list[dict]) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.get("configKey") != y.get("configKey"):
            return False
        if x.get("configType") != y.get("configType"):
            return False
        if not ct.same_value(x.get("configValue"), y.get("configValue")):
            return False
    return True


def same_package(a: dict, b: dict) -> bool:
    return (a.get("pkgConfName") == b.get("pkgConfName")
            and a.get("pkgConfMonitorName") == b.get("pkgConfMonitorName")
            and a.get("pkgConfPath") == b.get("pkgConfPath")
            and same_schema(schema(a), schema(b)))


def schema_mismatches(sent: dict, got: dict, show_secrets: bool = False) -> list[str]:
    """Human lines describing how the read-back differs from what was sent."""
    out = []
    gk = {e.get("configKey"): e for e in schema(got)}
    for e in schema(sent):
        k = e.get("configKey")
        g = gk.get(k)
        if g is None:
            out.append(f"{k}: missing from the read-back")
            continue
        if g.get("configType") != e.get("configType"):
            out.append(f"{k}: type is {ct.type_name(g.get('configType'))}, sent "
                       f"{ct.type_name(e.get('configType'))}")
        if not ct.same_value(g.get("configValue"), e.get("configValue")):
            t = e.get("configType")
            out.append(f"{k}: read back {ct.render(t, g.get('configValue'), show_secrets)}, "
                       f"sent {ct.render(t, e.get('configValue'), show_secrets)}")
    extra = [k for k in gk if k not in {e.get("configKey") for e in schema(sent)}]
    out += [f"{k}: in the read-back but not sent" for k in extra]
    if not out and [e.get("configKey") for e in schema(sent)] != list(gk):
        out.append("key order differs from what was sent")
    return out


def change_line(c: Change, show_secrets: bool = False) -> str:
    tn = ct.type_name(c.type)
    if not c.changed:
        return f"  {c.key} ({tn}): {ct.render(c.type, c.old, show_secrets)} (unchanged)"
    old = ct.render(c.type, c.old, show_secrets)
    new = ct.render(c.type, c.new, show_secrets)
    note = " (changed)" if old == new else ""
    return f"  {c.key} ({tn}): {old} -> {new}{note}"


# ----------------------------------------------------------- backup/restore
def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_doc(serial: int, pkg: dict, configs: list[dict]) -> dict:
    return {
        "kind": BACKUP_KIND,
        "serial": serial,
        "package": pkg.get("pkgConfName"),
        "takenAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "note": "Holds CPassword values in plaintext. Restore with lj-config-set --restore.",
        "packageConfig": pkg,
        "allConfigs": configs,
    }


def restore_updates(backup: Any, serial: int, pkg: dict) -> tuple[dict[str, Any], list[str]]:
    """The updates that put `pkg` back to the backup, or the reasons it cannot."""
    if not isinstance(backup, dict) or backup.get("kind") != BACKUP_KIND:
        return {}, [f"not an lj-config backup (expected \"kind\": \"{BACKUP_KIND}\")"]
    errs = []
    if backup.get("serial") != serial:
        errs.append(f"the backup is for serial {backup.get('serial')}, not {serial}")
    bp = backup.get("packageConfig") or {}
    if bp.get("pkgConfName") != pkg.get("pkgConfName"):
        errs.append(f"the backup is for package {bp.get('pkgConfName')!r}, "
                    f"not {pkg.get('pkgConfName')!r}")
    bk = [(e.get("configKey"), e.get("configType")) for e in schema(bp)]
    sk = [(e.get("configKey"), e.get("configType")) for e in schema(pkg)]
    if bk != sk:
        errs.append("the backup's keys or types differ from the stored schema; "
                    "a restore only changes values")
    if errs:
        return {}, errs
    return {e["configKey"]: e.get("configValue") for e in schema(bp)}, []


def write_private(path: str, text: str, force: bool = False) -> str:
    """Create `path` with mode 0600. Refuse an existing file unless force."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            f.write(text)
    finally:
        if fd >= 0:
            os.close(fd)
    return os.path.abspath(path)


def dump_json(v: Any) -> str:
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------- profiles
def profile_pairs(profiles: Any) -> list[tuple[int, dict]]:
    out = []
    for item in profiles or []:
        if isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict):
            out.append((item[0], item[1]))
    return out


def profile_for(profiles: Any, serial: int) -> dict | None:
    for s, p in profile_pairs(profiles):
        if s == serial:
            return p
    return None


PROFILE_FIELDS = ("lumberjackName", "lumberjackArch", "lumberjackGroup", "lumberjackUrl",
                  "lumberjackTimezone")


def safe_profile(serial: int, p: dict) -> dict:
    """The printable part of a profile. lumberjackPassword never leaves this function."""
    out: dict[str, Any] = {"serial": serial}
    for f in PROFILE_FIELDS:
        out[f] = p.get(f)
    return out
