# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Change one generic-SWD kiosk's name, lanes or status map. MUTATING with --yes.

Usage:
  update_generic_swd.py UUID name-set --name TEXT [common]
  update_generic_swd.py UUID lane-set --lane N [--read-pid P] [--write-pid P]
                        [--wait-val X] [--script TEXT | --script-file F | --clear-script] [common]
  update_generic_swd.py UUID lane-add --lane N --read-pid P --write-pid P --wait-val X
                        [--script TEXT | --script-file F] [common]
  update_generic_swd.py UUID lane-delete --lane N [common]
  update_generic_swd.py UUID status-set --value V (--status NAME | --disabled MESSAGE) [common]
  update_generic_swd.py UUID status-delete --value V [common]
  update_generic_swd.py UUID replace --from FILE [common]

  common: [--yes] [--dry-run] [--backup PATH] [--no-live-check] [--json]

Every subcommand builds the whole new configuration from the current one,
validates it, applies the ownership guard, and prints the diff. Nothing is
sent without --yes, and --dry-run wins over --yes. A write then: writes a
backup file, re-reads the configuration and refuses if it changed, reads the
live lane states, sends one lane update, reads the configuration back,
checks the changed lanes' mask results, and reads the live lane states
again. `replace --from BACKUP --yes` restores a backup.

Exit codes: 0 written and confirmed, or no change; 1 a read failed, or the
write was rejected and nothing changed; 2 usage; 3 refused by the guard, the
validation, the drift check or the backup; 4 unknown or wrong outcome (the
restore command is printed).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _generic_swd_routes import cli, guard, model, routes  # noqa: E402
from _token_input import shapes, token_source

SUBCOMMANDS = ("name-set", "lane-set", "lane-add", "lane-delete", "status-set", "status-delete", "replace")


def _pid(text: str) -> int:
    try:
        v = int(text)
    except ValueError:
        raise ValueError(f"not an integer PID: {text}")
    if v <= 0:
        raise ValueError(f"a PID must be positive: {text}")
    return v


def _lane(text: str) -> int:
    try:
        v = int(text)
    except ValueError:
        raise ValueError(f"not an integer lane number: {text}")
    if not (0 <= v <= model.MAX_LANE):
        raise ValueError(f"a lane number must be from 0 to {model.MAX_LANE}: {text}")
    return v


def _num(text: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"not a number: {text}")
    if not math.isfinite(v):
        raise ValueError(f"not a finite number: {text}")
    return v


def _typed(fn):
    def conv(text: str):
        try:
            return fn(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc))
    conv.__name__ = fn.__name__.strip("_")
    return conv


def build_parser() -> cli.Parser:
    p = cli.Parser(prog="update_generic_swd.py", description="Change one generic-SWD kiosk's configuration.")
    p.add_argument("uuid", help="the kiosk UUID (from onping-generic-swd-list)")
    sub = p.add_subparsers(dest="command", required=True, parser_class=cli.Parser)

    def common(sp):
        sp.add_argument("--yes", action="store_true", help="send the change (without it: preview only)")
        sp.add_argument("--dry-run", action="store_true", help="preview only; never send (wins over --yes)")
        sp.add_argument("--backup", metavar="PATH", help="backup file (default ./generic-swd-<uuid8>-<UTC>.backup.json)")
        sp.add_argument("--no-live-check", action="store_true", help="skip the live lane-state read before and after")
        sp.add_argument("--json", action="store_true", help="machine-readable output")

    def script_opts(sp, clear: bool):
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--script", metavar="TEXT", help="the lane's mask script (empty string for none)")
        g.add_argument("--script-file", metavar="FILE", help="read the mask script from FILE")
        if clear:
            g.add_argument("--clear-script", action="store_true", help="remove the lane's mask script")

    sp = sub.add_parser("name-set", help="rename the kiosk configuration")
    sp.add_argument("--name", required=True)
    common(sp)

    sp = sub.add_parser("lane-set", help="change one existing lane")
    sp.add_argument("--lane", required=True, type=_typed(_lane))
    sp.add_argument("--read-pid", type=_typed(_pid))
    sp.add_argument("--write-pid", type=_typed(_pid))
    sp.add_argument("--wait-val", type=_typed(_num), help="the value written to the write PID to start an offload")
    script_opts(sp, clear=True)
    common(sp)

    sp = sub.add_parser("lane-add", help="add a lane")
    sp.add_argument("--lane", required=True, type=_typed(_lane))
    sp.add_argument("--read-pid", required=True, type=_typed(_pid))
    sp.add_argument("--write-pid", required=True, type=_typed(_pid))
    sp.add_argument("--wait-val", required=True, type=_typed(_num))
    script_opts(sp, clear=False)
    common(sp)

    sp = sub.add_parser("lane-delete", help="remove a lane")
    sp.add_argument("--lane", required=True, type=_typed(_lane))
    common(sp)

    sp = sub.add_parser("status-set", help="add or change one status-map entry")
    sp.add_argument("--value", required=True, type=_typed(_num), help="the masked read value")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", choices=model.PLAIN_STATUSES)
    g.add_argument("--disabled", metavar="MESSAGE", help="a disabled status with this message")
    common(sp)

    sp = sub.add_parser("status-delete", help="remove one status-map entry")
    sp.add_argument("--value", required=True, type=_typed(_num))
    common(sp)

    sp = sub.add_parser("replace", help="write a whole configuration from a file (the restore path)")
    sp.add_argument("--from", dest="from_file", required=True, metavar="FILE",
                    help="a backup file, or a FrontendKioskServerConfig JSON file")
    common(sp)
    return p


class Stop(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def parse(argv: list[str] | None):
    parser = build_parser()
    args = token_source.parse(parser, argv, is_id=shapes.is_uuid)
    if not model.valid_uuid(args.uuid):
        parser.error(f"not a kiosk UUID: {args.uuid}")
    if args.command == "lane-set" and not any(
            v is not None and v is not False for v in (args.read_pid, args.write_pid, args.wait_val, args.script,
                                                        args.script_file, args.clear_script or None)):
        parser.error("lane-set needs at least one of --read-pid, --write-pid, --wait-val, --script, "
                     "--script-file, --clear-script")
    script_file = getattr(args, "script_file", None)
    if script_file:
        try:
            args.script = Path(script_file).read_text()
        except OSError as exc:
            parser.error(f"cannot read --script-file: {exc}")
    if args.command == "replace":
        try:
            args.replacement_text = Path(args.from_file).read_text()
        except OSError as exc:
            parser.error(f"cannot read --from: {exc}")
    if args.backup and Path(args.backup).exists():
        parser.error(f"--backup {args.backup} already exists; choose a new file")
    return args


def apply_edit(args, current: dict) -> dict:
    c = args.command
    if c == "name-set":
        return model.name_set(current, args.name)
    if c == "lane-set":
        script = "" if getattr(args, "clear_script", False) else args.script
        return model.lane_set(current, args.lane, read_pid=args.read_pid, write_pid=args.write_pid,
                              script=script, wait=args.wait_val)
    if c == "lane-add":
        return model.lane_add(current, args.lane, args.read_pid, args.write_pid, args.wait_val, args.script or "")
    if c == "lane-delete":
        return model.lane_delete(current, args.lane)
    if c == "status-set":
        return model.status_set(current, args.value, args.status or {"disabled": args.disabled})
    if c == "status-delete":
        return model.status_delete(current, args.value)
    if c == "replace":
        return model.read_config_file(args.replacement_text, args._kiosk_uuid)
    raise AssertionError(c)


def pid_lines(model_new: dict, listed: dict[int, dict], touched: dict[int, dict]) -> list[str]:
    out = []
    for ln in sorted(model_new["lanes"], key=lambda x: x["number"]):
        t = touched.get(ln["number"])
        if not t:
            continue
        for role, key in (("read", "read_pid"), ("write", "write_pid")):
            if not t.get(role):
                continue
            e = listed.get(ln[key], {})
            if e.get("found"):
                out.append(f"  lane {ln['number']} {role} PID {ln[key]}: {e.get('description')!s}, location "
                           f"{e.get('location_id')}, value {e.get('value')!s}, {e.get('writeability')}")
            else:
                out.append(f"  lane {ln['number']} {role} PID {ln[key]}: NOT FOUND")
    return out


def mask_problems(raw: dict, touched: dict[int, dict]) -> list[str]:
    out = []
    for num, e in model.enrichment(raw).items():
        if num not in touched:
            continue
        rd = e.get("read") or {}
        if rd.get("laneParamRawValue") is not None and rd.get("laneParamMaskedValue") is None:
            out.append(f"lane {num}: the read PID has a value but no masked value; the mask script did not evaluate")
    return out


def run(args, doc: dict, lines: list[str]) -> int:
    token = args.access_token
    try:
        who = guard.caller(token)
        kiosk = guard.find_kiosk(token, who, args.uuid, write=True)
    except guard.Refused as exc:
        raise Stop(cli.EXIT_REFUSED, f"refused: {exc}; nothing written")
    uuid = kiosk.uuid
    args._kiosk_uuid = uuid
    doc["kiosk"] = kiosk.doc(who)
    lines.append(f"kiosk {uuid}  {kiosk.name!s}  group {kiosk.group_id} ({who.name(kiosk.group_id)}), owned")

    try:
        current_raw = routes.kiosk_config(token, uuid)
        current = model.from_wire(current_raw)
    except (routes.RouteFailure, model.ModelError) as exc:
        raise Stop(cli.EXIT_READ, f"read failed: {exc}; nothing written")
    try:
        new = apply_edit(args, current)
    except model.ModelError as exc:
        raise Stop(cli.EXIT_REFUSED, f"refused: {exc}; nothing written")

    errors, warnings = model.validate(new)
    doc["validation"] = {"errors": errors, "warnings": warnings}
    if errors:
        lines.append("the new configuration fails validation:")
        lines += [f"  - {e}" for e in errors]
        raise Stop(cli.EXIT_REFUSED, f"refused: {len(errors)} validation error(s); nothing written")

    changes = model.diff(current, new)
    doc["changes"] = changes
    if model.canonical(current) == model.canonical(new):
        doc["outcome"] = "no-change"
        lines.append("no change: the configuration already says this; nothing to send")
        return cli.EXIT_OK
    touched = model.touched(current, new)
    lines.append("changes:")
    lines += [f"  {c}" for c in changes]

    try:
        listed, problems, pid_warnings = guard.pid_report(token, who, new, touched)
    except guard.Refused as exc:
        raise Stop(cli.EXIT_REFUSED, f"refused: {exc}; nothing written")
    warnings = warnings + pid_warnings
    if any(ln["script"] != "" and touched.get(ln["number"], {}).get("script") for ln in new["lanes"]):
        warnings.append("mask scripts are checked for shape only, not grammar; the read-back after the write "
                        "shows whether the kiosk could evaluate them")
    doc["pids"] = {str(k): v for k, v in listed.items()}
    doc["warnings"] = warnings
    pl = pid_lines(new, listed, touched)
    if pl:
        lines.append("PIDs this change sets (confirm each is the right register):")
        lines += pl
    lines += [f"warning: {w}" for w in warnings]
    if problems:
        doc["guard_problems"] = problems
        lines.append("the ownership guard refuses:")
        lines += [f"  - {p}" for p in problems]
        raise Stop(cli.EXIT_REFUSED, f"refused: {len(problems)} PID guard problem(s); nothing written")

    backup = args.backup or f"./generic-swd-{uuid[:8]}-{cli.utc_stamp()}.backup.json"
    restore = cli.restore_command(uuid, backup)
    doc["restore"] = restore
    if args.dry_run or not args.yes:
        doc["outcome"] = "dry-run" if args.dry_run else "preview"
        lines.append("DRY RUN — nothing was posted." if args.dry_run
                     else "PREVIEW ONLY — nothing was posted. Re-run with --yes to apply.")
        lines.append(f"with --yes, a backup goes to {backup}; restore with: {restore}")
        return cli.EXIT_OK

    # ── the write ──
    try:
        Path(backup).write_text(json.dumps(model.backup_doc(kiosk.doc(who), current, cli.utc_now()),
                                           indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise Stop(cli.EXIT_REFUSED, f"refused: could not write the backup {backup} ({exc}); nothing written")
    doc["backup"] = backup
    lines.append(f"backup written: {backup}")

    try:
        again = model.from_wire(routes.kiosk_config(token, uuid))
    except (routes.RouteFailure, model.ModelError) as exc:
        raise Stop(cli.EXIT_READ, f"read failed before the write: {exc}; nothing written")
    if model.canonical(again) != model.canonical(current):
        raise Stop(cli.EXIT_REFUSED, "refused: the configuration changed since it was read "
                                     f"({'; '.join(model.diff(current, again)) or 'reordered'}); nothing written. Re-run to see the new diff.")

    live_before = None
    if not args.no_live_check:
        try:
            routes.kiosk_lanes(token, uuid)
            live_before = True
        except routes.RouteFailure as exc:
            live_before = False
            lines.append(f"warning: the live lane read already fails before the write ({exc}); "
                         f"it will not be used as a check")
    doc["live_before"] = live_before

    target = model.to_wire(new)
    try:
        status, body = routes.lane_update(token, uuid, target)
        response = {"status": status, "body": body[:600]}
        accepted = 200 <= status < 300
    except routes.WriteLost as exc:
        response = {"status": None, "error": str(exc)}
        accepted = None
    doc["response"] = response

    try:
        after_raw = routes.kiosk_config(token, uuid)
        after = model.from_wire(after_raw)
    except (routes.RouteFailure, model.ModelError) as exc:
        doc["outcome"] = "unknown"
        lines.append(f"restore: {restore}")
        raise Stop(cli.EXIT_UNKNOWN, f"UNKNOWN: the read-back failed ({exc}); the write may or may not have "
                                     f"landed. Check with onping-generic-swd-get; restore with: {restore}")
    landed = model.canonical(after) == model.canonical(new)
    unchanged = model.canonical(after) == model.canonical(current)

    if accepted is False and unchanged:
        doc["outcome"] = "rejected"
        raise Stop(cli.EXIT_READ, f"rejected: HTTP {response['status']}: {routes.error_text(response['body'])}; "
                                  f"the read-back shows nothing changed")
    problems = []
    if not landed:
        problems.append("the read-back does not match what was sent: " + ("; ".join(model.diff(new, after)) or "?"))
    if accepted is not True:
        problems.append(f"the write response was {response}")
    problems += mask_problems(after_raw, touched)
    if live_before:
        try:
            routes.kiosk_lanes(token, uuid)
            doc["live_after"] = True
        except routes.RouteFailure as exc:
            doc["live_after"] = False
            problems.append(f"the live lane read now fails: {exc}")
    if problems:
        doc["outcome"] = "unconfirmed"
        doc["problems"] = problems
        lines.append("the write is NOT confirmed:")
        lines += [f"  - {p}" for p in problems]
        lines.append(f"restore: {restore}")
        raise Stop(cli.EXIT_UNKNOWN, f"UNCONFIRMED: {len(problems)} problem(s) after the write; restore with: {restore}")
    doc["outcome"] = "written"
    lines.append("written and confirmed: the read-back matches"
                 + (", and the live lane read succeeds" if live_before else ""))
    lines.append(f"restore: {restore}")
    return cli.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    doc: dict = {"command": args.command, "uuid": args.uuid}
    lines: list[str] = []
    try:
        code = run(args, doc, lines)
    except Stop as stop:
        if not args.json:
            print("\n".join(lines))
        return cli.fail(args.json, stop.code, str(stop), doc)
    doc["ok"] = True
    doc["exit"] = code
    cli.emit(args.json, doc, lines)
    return code


if __name__ == "__main__":
    sys.exit(main())
