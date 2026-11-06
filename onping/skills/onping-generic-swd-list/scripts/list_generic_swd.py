# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List the generic-SWD kiosks in your OnPing groups. Read-only.

Usage:
  list_generic_swd.py TOKEN [--group GID ...] [--owned-only] [--json]

Sends only your own owned and member group ids to kiosk/configs. A --group
you neither own nor belong to is refused (exit 3) before any kiosk request.

Exit codes: 0 ok; 1 a read failed; 2 usage; 3 refused.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _generic_swd_routes import cli, guard, routes  # noqa: E402
from _token_input import token_source


def build_parser() -> cli.Parser:
    p = cli.Parser(prog="list_generic_swd.py", description="List generic-SWD kiosks in your groups.")
    p.add_argument("--group", action="append", metavar="GID", help="only this group (repeatable)")
    p.add_argument("--owned-only", action="store_true", help="only kiosks whose group you own")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = token_source.parse(build_parser(), argv)
    for g in args.group or []:
        if not g or not g.strip():
            build_parser().error("--group needs a group id")
    try:
        who = guard.caller(args.access_token)
        kiosks = guard.list_kiosks(args.access_token, who, args.group)
    except guard.Refused as exc:
        return cli.fail(args.json, cli.EXIT_REFUSED, f"refused: {exc}")
    except routes.RouteFailure as exc:
        return cli.fail(args.json, cli.EXIT_READ, f"read failed: {exc}")
    if args.owned_only:
        kiosks = [k for k in kiosks if k.owned]
    kiosks.sort(key=lambda k: (str(k.name), k.uuid))
    docs = [k.doc(who) for k in kiosks]
    lines = [f"{len(docs)} kiosk(s)"]
    for d in docs:
        lines.append(f"{d['uuid']}  {d['name']!s}  group {d['group_id']} ({d['group_name']})"
                     f"  {'owned' if d['owned'] else 'member'}  {d['ip']}:{d['port']}")
    if docs:
        lines.append("The list holds every kiosk kind in your groups; onping-generic-swd-get "
                     "fails for a kiosk that is not a generic-SWD kiosk.")
    cli.emit(args.json, {"ok": True, "count": len(docs), "kiosks": docs}, lines)
    return cli.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
