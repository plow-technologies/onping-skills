# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List a Lumberjack's LAS dynamic configs (per-package editable keys). Read-only.

    lj_config_list.py TOKEN SERIAL [--package P] [--show-secrets] [--json]
    lj_config_list.py TOKEN --lumberjacks [--name SUBSTR] [--json]

Without --package: one line per package (monitor name, key count, path), with
the Lumberjack's name, whether you own it, and the sync state. With --package:
every key, its type and its value. CPassword values print as ******** unless
--show-secrets is given, in text and JSON output alike.

--lumberjacks lists the Lumberjacks you OWN (the profile list is filtered to
owned groups): serial, name, arch, group, URL. lumberjackPassword is never
printed.

Exit codes: 0 ok, 1 request failure or unknown package, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _las_routes import config_types as ct  # noqa: E402
from _las_routes import configs as cf  # noqa: E402
from _las_routes.las_http import LASError, get_json  # noqa: E402
from _token_input import shapes, token_source


def _yn(v) -> str:
    return "unknown" if v is None else ("yes" if v else "no")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("serial", metavar="SERIAL", nargs="?", type=shapes.int_arg)
    p.add_argument("--lumberjacks", action="store_true",
                   help="list the Lumberjacks you own instead of one Lumberjack's configs")
    p.add_argument("--name", metavar="SUBSTR", help="with --lumberjacks: filter by name")
    p.add_argument("--package", metavar="P", help="show every key of this package")
    p.add_argument("--show-secrets", action="store_true", help="print CPassword values")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = token_source.parse(p, argv, is_id=shapes.is_int)
    if args.lumberjacks == (args.serial is not None):
        p.error("give a SERIAL, or --lumberjacks (not both)")
    if args.name and not args.lumberjacks:
        p.error("--name goes with --lumberjacks")
    return args


def list_lumberjacks(args) -> int:
    rows = [cf.safe_profile(s, p) for s, p in cf.profile_pairs(get_json(args.access_token, "profiles"))]
    if args.name:
        needle = args.name.lower()
        rows = [r for r in rows if needle in (r.get("lumberjackName") or "").lower()]
    rows.sort(key=lambda r: r["serial"])
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print(f"{len(rows)} Lumberjack(s) you own")
    for r in rows:
        print(f"  {r['serial']:>6}  {r.get('lumberjackName') or '-'}  "
              f"[{r.get('lumberjackArch') or '-'}]  group {r.get('lumberjackGroup') or '-'}  "
              f"{r.get('lumberjackUrl') or ''}")
    return 0


def shown_package(pkg: dict, show_secrets: bool) -> dict:
    out = {k: pkg.get(k) for k in ("pkgConfName", "pkgConfMonitorName", "pkgConfPath")}
    out["pkgConfSchema"] = [
        {"configKey": e.get("configKey"), "configType": e.get("configType"),
         "configValue": e.get("configValue") if show_secrets
         else ct.mask(e.get("configType"), e.get("configValue"))}
        for e in cf.schema(pkg)
    ]
    return out


def list_configs(args) -> int:
    serial = args.serial
    configs = get_json(args.access_token, "configs", serial=serial) or []
    synced = get_json(args.access_token, "storage_synced", serial=serial)
    bridge = get_json(args.access_token, "bridge_up", serial=serial)
    prof = cf.profile_for(get_json(args.access_token, "profiles"), serial)
    head = {"serial": serial, "name": prof.get("lumberjackName") if prof else None,
            "owner": prof is not None, "storageSynced": synced, "bridgeUp": bridge}
    pkgs = configs
    if args.package:
        pkg = cf.find_package(configs, args.package)
        if pkg is None:
            print(f"No package {args.package!r} on Lumberjack {serial}. Packages: "
                  f"{', '.join(cf.package_names(configs)) or 'none'}", file=sys.stderr)
            return 1
        pkgs = [pkg]
    if args.json:
        print(json.dumps({**head, "packages": [shown_package(p, args.show_secrets) for p in pkgs]},
                         indent=2, ensure_ascii=False))
        return 0
    print(f"Lumberjack {serial} {json.dumps(head['name']) if head['name'] else '(name unknown)'}"
          f"  owner: {_yn(head['owner'])}  storage synced: {_yn(synced)}"
          f"  bridge up: {_yn(bridge)}")
    if not head["owner"]:
        print("  (not in your owned profiles: lj-config-set and lj-config-export need Owner)")
    if not args.package:
        print(f"{len(configs)} package(s)")
        for p in configs:
            mon = p.get("pkgConfMonitorName") or "(no monitor)"
            print(f"  {p.get('pkgConfName')}  monitor {mon}  keys {len(cf.schema(p))}"
                  f"  {p.get('pkgConfPath')}")
        return 0
    pkg = pkgs[0]
    print(f"package {pkg.get('pkgConfName')}  monitor "
          f"{pkg.get('pkgConfMonitorName') or '(no monitor)'}\n  path {pkg.get('pkgConfPath')}")
    for e in cf.schema(pkg):
        t = e.get("configType")
        print(f"  {e.get('configKey')} ({ct.type_name(t)}) = "
              f"{ct.render(t, e.get('configValue'), args.show_secrets)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return list_lumberjacks(args) if args.lumberjacks else list_configs(args)
    except LASError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
