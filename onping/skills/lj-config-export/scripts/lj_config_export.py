# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export one package's LAS dynamic config from a Lumberjack to a local file.

    lj_config_export.py TOKEN SERIAL --package P [-o FILE | -o -] [--force] [--json]

Default: the flat `key: value` YAML from GET /las/api/v1/lumberjack/configs/export,
written unchanged (the route needs Owner). --json: the package's PackageConfig
from GET configs instead. Output goes to FILE, to stdout with `-o -`, or by
default to ./<package>.yaml (or .json). The file is created with mode 0600 and
an existing file is never overwritten without --force.

The export holds CPassword values IN PLAINTEXT, as the server returns them.

Exit codes: 0 ok, 1 request failure or unknown package, 2 usage or existing
file, 3 not an owner of the Lumberjack.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _las_routes import configs as cf  # noqa: E402
from _las_routes.las_http import LASError, get_json, get_text  # noqa: E402
from _token_input import shapes, token_source


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("serial", metavar="SERIAL", type=shapes.int_arg)
    p.add_argument("--package", metavar="P", required=True)
    p.add_argument("-o", "--output", metavar="FILE",
                   help="output path, or - for stdout (default ./<package>.yaml|.json)")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    p.add_argument("--json", action="store_true",
                   help="write the PackageConfig JSON instead of the YAML export")
    return token_source.parse(p, argv, is_id=shapes.is_int)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out = args.output or f"./{args.package}.{'json' if args.json else 'yaml'}"
    if out != "-" and os.path.exists(out) and not args.force:
        print(f"{out} exists; pass --force to overwrite it.", file=sys.stderr)
        return 2
    try:
        if cf.profile_for(get_json(args.access_token, "profiles"), args.serial) is None:
            print(f"Lumberjack {args.serial} is not in your owned profiles. Export needs "
                  "Owner of the Lumberjack's group.", file=sys.stderr)
            return 3
        if args.json:
            configs = get_json(args.access_token, "configs", serial=args.serial) or []
            pkg = cf.find_package(configs, args.package)
            if pkg is None:
                print(f"No package {args.package!r} on Lumberjack {args.serial}. Packages: "
                      f"{', '.join(cf.package_names(configs)) or 'none'}", file=sys.stderr)
                return 1
            text = cf.dump_json(pkg)
        else:
            text = get_text(args.access_token, "configs_export", serial=args.serial,
                            package=args.package)
    except LASError as e:
        print(str(e), file=sys.stderr)
        return 1
    if out == "-":
        sys.stdout.write(text)
        return 0
    try:
        path = cf.write_private(out, text, force=args.force)
    except FileExistsError:
        print(f"{out} exists; pass --force to overwrite it.", file=sys.stderr)
        return 2
    print(f"Wrote {path} (mode 0600; CPassword values are in plaintext).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
