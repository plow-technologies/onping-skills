# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List, show, export, set and delete PAK transport Ticket Permissive links.

    pak_link.py list (--serial N ... | --all-owned) [--json]
    pak_link.py get --id UUID [--json]
    pak_link.py export (--serial N ... | --all-owned | --id UUID) -o FILE [--json]
    pak_link.py set [--id UUID] [--from FILE [--new-id]] [--serial N [--allow-move]]
                [--facility-id TEXT] [--facility-name TEXT] [--url HOST] [--port N]
                [--map BAY=LANE ...] [--backup-dir DIR] [--yes] [--dry-run] [--json]
    pak_link.py delete --id UUID [--backup-dir DIR] [--yes] [--dry-run] [--json]

A link ties one PAK transport facility to one Lumberjack (LJ) and maps each
PAK bay to an LJ lane. One link per LJ; a bay may appear in one link only;
several bays may share a lane.

`set` and `delete` preview by default and write only with `--yes`. `--dry-run`
wins. Before a write the script runs a read-only preflight that mirrors the
cloud app's 400 rejections (no mappings, a repeated bay, a bay claimed by
another link, a second link on the LJ, a bad host or port), and an ownership
guard: the script loads the stored record by its id through the list route and
refuses unless the caller owns its LJ. OnPing's handlers apply the same rule to
the stored record and to the LJ in the request.
Each write saves a backup first, is one request with no retry, and is then
read back.

Exit codes: 0 ok/preview/no-op, 1 request failure (nothing written), 2 usage or
input file, 3 ownership-guard or preflight refusal (or the old record shape),
4 unknown outcome or read-back mismatch.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pak_routes as pr  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _token_input import token_source

EXIT_OK, EXIT_FAILURE, EXIT_USAGE, EXIT_REFUSED, EXIT_UNVERIFIED = 0, 1, 2, 3, 4

SCRIPT_CMD = 'uv run ~/.claude/skills/onping-pak-transport-link/scripts/pak_link.py'
BACKUP_KIND = "onping-pak-transport-link-backup"


class LinkExit(Exception):
    def __init__(self, code: int, message: str, doc: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.doc = doc  # printed on stdout with --json


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # usage errors exit 2 before any request
        raise LinkExit(EXIT_USAGE, f"usage error: {message}")


# ─────────────────────────────── parsing ───────────────────────────────


def _serial(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an LJ serial: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"not an LJ serial: {text!r}")
    return value


def _word64(text: str, what: str, pair: str) -> int:
    t = text.strip()
    if not t.isdigit():
        raise argparse.ArgumentTypeError(f"--map {pair!r}: {what} must be a whole number from 0 to 2^64-1")
    value = int(t, 10)
    if value > pr.WORD64_MAX:
        raise argparse.ArgumentTypeError(f"--map {pair!r}: {what} is larger than 2^64-1")
    return value


def _mapping(text: str) -> dict:
    if text.count("=") != 1:
        raise argparse.ArgumentTypeError(f"--map wants BAY=LANE, got {text!r}")
    bay, lane = text.split("=")
    return {"bayLaneBayId": _word64(bay, "BAY", text), "bayLaneLaneNumber": _word64(lane, "LANE", text)}


def _port(text: str) -> int:
    try:
        return int(text, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--port wants a number, got {text!r}") from None


def _uuid(text: str) -> str:
    if not pr.is_uuid(text):
        raise argparse.ArgumentTypeError(f"not a config UUID: {text!r}")
    return text.lower()


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="pak_link.py", description=__doc__.split("\n\n")[1])
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)

    ls = sub.add_parser("list", help="show the links on the given LJs")
    g = ls.add_mutually_exclusive_group(required=True)
    g.add_argument("--serial", type=_serial, nargs="+", metavar="N")
    g.add_argument("--all-owned", action="store_true", help="every LJ you own")
    ls.add_argument("--json", action="store_true")

    gt = sub.add_parser("get", help="show one link by its config id")
    gt.add_argument("--id", type=_uuid, required=True, metavar="UUID")
    gt.add_argument("--json", action="store_true")

    ex = sub.add_parser("export", help="write links to a JSON file (a backup set-from can read)")
    g = ex.add_mutually_exclusive_group(required=True)
    g.add_argument("--serial", type=_serial, nargs="+", metavar="N")
    g.add_argument("--all-owned", action="store_true")
    g.add_argument("--id", type=_uuid, metavar="UUID")
    ex.add_argument("-o", "--output", required=True, metavar="FILE")
    ex.add_argument("--json", action="store_true")

    st = sub.add_parser("set", help="create or edit one link")
    st.add_argument("--id", type=_uuid, metavar="UUID", help="the link to edit (or the one to pick from --from)")
    st.add_argument("--from", dest="from_file", metavar="FILE", help="a record, an export or a backup")
    st.add_argument("--new-id", action="store_true", help="give the --from record a fresh id (a create)")
    st.add_argument("--serial", type=_serial, metavar="N", help="the LJ (create, or a move with --allow-move)")
    st.add_argument("--allow-move", action="store_true", help="let an edit move the link to another LJ")
    st.add_argument("--facility-id", metavar="TEXT")
    st.add_argument("--facility-name", metavar="TEXT")
    st.add_argument("--url", metavar="HOST", help="LJ host for the switcher (create default: the LAS profile URL)")
    st.add_argument("--port", type=_port, metavar="N", help=f"LJ app port (create default: {pr.DEFAULT_PORT})")
    st.add_argument("--map", type=_mapping, action="append", metavar="BAY=LANE", help="repeatable; replaces the whole list")
    _write_flags(st)

    dl = sub.add_parser("delete", help="delete one link (hard delete; the backup is the undo)")
    dl.add_argument("--id", type=_uuid, required=True, metavar="UUID")
    _write_flags(dl)
    return p


def _write_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--backup-dir", default="./pak-link-backups", metavar="DIR")
    p.add_argument("--yes", action="store_true", help="write (default: preview only)")
    p.add_argument("--dry-run", action="store_true", help="preview only; wins over --yes")
    p.add_argument("--json", action="store_true")


# ─────────────────────────────── output ───────────────────────────────


def _say(args, text: str = "") -> None:
    # With --json, stdout carries only the JSON document; prose goes to stderr.
    print(text, file=sys.stderr if getattr(args, "json", False) else sys.stdout)


def _emit(args, doc: dict) -> None:
    if args.json:
        print(json.dumps(doc, indent=2))


def describe(rec: dict) -> list[str]:
    maps = ", ".join(f"bay {m['bayLaneBayId']} -> lane {m['bayLaneLaneNumber']}" for m in pr.canonical(rec)["pakTransportBayLaneMappings"])
    return [
        f"link {rec['pakTransportConfigId']}",
        f"  LJ            {rec['pakTransportLumberjackId']}",
        f"  facility id   {rec['pakTransportFacilityId']}",
        f"  facility name {rec['pakTransportFacilityName']}",
        f"  LJ address    {rec['pakTransportLumberjackUrl']}:{rec['pakTransportLumberjackPort']}",
        f"  mappings      {maps or '(none)'}",
    ]


# ─────────────────────────────── shared reads ───────────────────────────────


class Context:
    """The caller's owned LJs and every link on them (the guard's view)."""

    def __init__(self, token: str):
        self.token = token
        self.ownership = pr.Ownership(token)
        self.visible: list[dict] = pr.list_configs(token, sorted(self.ownership.owned)) if self.ownership.owned else []

    def by_id(self, config_id: str) -> dict | None:
        for rec in self.visible:
            if rec["pakTransportConfigId"].lower() == config_id.lower():
                return rec
        return None

    def guard(self, config_id: str) -> dict:
        """The stored record for this id, only if the caller owns its LJ."""
        rec = self.by_id(config_id)
        if rec is None:
            raise LinkExit(
                EXIT_REFUSED,
                f"refused: no link {config_id} on an LJ you own. The list route hides links on LJs you do not "
                "own, so this id is either new or someone else's; this skill will not write to it.",
            )
        if not self.ownership.owns(rec["pakTransportLumberjackId"]):  # list already filters; belt and braces
            raise LinkExit(EXIT_REFUSED, f"refused: link {config_id} is on LJ {rec['pakTransportLumberjackId']}, which you do not own")
        return rec


def _context(token: str) -> Context:
    try:
        return Context(token)
    except pr.ShapeError as exc:
        raise LinkExit(EXIT_REFUSED, f"refused: {exc}") from exc
    except pr.RouteFailure as exc:
        raise LinkExit(EXIT_FAILURE, f"read failed: {exc}") from exc


def _list(token: str, serials: list[int]) -> list[dict]:
    try:
        return pr.list_configs(token, serials)
    except pr.ShapeError as exc:
        raise LinkExit(EXIT_REFUSED, f"refused: {exc}") from exc
    except pr.RouteFailure as exc:
        raise LinkExit(EXIT_FAILURE, f"read failed: {exc}") from exc


# ─────────────────────────────── read commands ───────────────────────────────


def _select(args, ctx: Context) -> tuple[list[dict], list[dict]]:
    if getattr(args, "id", None):
        return [pr.canonical(ctx.guard(args.id))], []
    serials = sorted(ctx.ownership.owned) if args.all_owned else sorted(set(args.serial))
    wanted = set(serials)
    configs = [pr.canonical(r) for r in ctx.visible if r["pakTransportLumberjackId"] in wanted]
    have = {r["pakTransportLumberjackId"] for r in configs}
    missing = []
    if not args.all_owned:
        for s in serials:
            if s not in have:
                why = "no link" if ctx.ownership.owns(s) else "not owned (the list route hides links on LJs you do not own)"
                missing.append({"serial": s, "reason": why})
    configs.sort(key=lambda r: (r["pakTransportLumberjackId"], r["pakTransportConfigId"]))
    return configs, missing


def cmd_list(args) -> int:
    ctx = _context(args.access_token)
    configs, missing = _select(args, ctx)
    for rec in configs:
        for line in describe(rec):
            _say(args, line)
    for m in missing:
        _say(args, f"LJ {m['serial']}: {m['reason']}")
    if not configs and not missing:
        _say(args, "no links on the LJs you own")
    _emit(args, {"configs": configs, "missing": missing})
    return EXIT_OK


def cmd_get(args) -> int:
    ctx = _context(args.access_token)
    rec = pr.canonical(ctx.guard(args.id))
    for line in describe(rec):
        _say(args, line)
    _emit(args, {"config": rec})
    return EXIT_OK


def cmd_export(args) -> int:
    out = Path(args.output)
    if out.exists():
        raise LinkExit(EXIT_USAGE, f"usage error: {out} already exists; pick a new file")
    ctx = _context(args.access_token)
    configs, missing = _select(args, ctx)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(configs, indent=2) + "\n")
    _say(args, f"wrote {len(configs)} link(s) to {out}")
    for m in missing:
        _say(args, f"LJ {m['serial']}: {m['reason']}")
    _emit(args, {"file": str(out), "count": len(configs), "missing": missing})
    return EXIT_OK


# ─────────────────────────────── set ───────────────────────────────


def _load_from(path: str, pick: str | None) -> dict:
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise LinkExit(EXIT_USAGE, f"usage error: cannot read {path}: {exc}") from exc
    if isinstance(payload, dict) and payload.get("kind") == BACKUP_KIND:
        if payload.get("before") is None:
            raise LinkExit(
                EXIT_USAGE,
                f"usage error: {path} is the backup of a create (there was no link before). "
                f"Undo it with: {SCRIPT_CMD} delete --id {payload.get('configId')} --yes",
            )
        payload = payload["before"]
    if isinstance(payload, list):
        if pick:
            hits = [r for r in payload if isinstance(r, dict) and str(r.get("pakTransportConfigId", "")).lower() == pick]
            if len(hits) != 1:
                raise LinkExit(EXIT_USAGE, f"usage error: {path} has {len(hits)} link(s) with id {pick}")
            payload = hits[0]
        elif len(payload) == 1:
            payload = payload[0]
        else:
            raise LinkExit(EXIT_USAGE, f"usage error: {path} holds {len(payload)} links; pick one with --id")
    try:
        rec = pr.check_record(payload, path)
    except pr.ShapeError as exc:
        raise LinkExit(EXIT_USAGE, f"usage error: {exc}") from exc
    if not pr.is_uuid(str(rec["pakTransportConfigId"]).lower()):
        raise LinkExit(EXIT_USAGE, f"usage error: {path}: pakTransportConfigId is not a UUID")
    if pick and str(rec["pakTransportConfigId"]).lower() != pick:
        raise LinkExit(EXIT_USAGE, f"usage error: {path} holds link {rec['pakTransportConfigId']}, not {pick}")
    for key in ("pakTransportLumberjackId", "pakTransportLumberjackPort"):
        if isinstance(rec[key], bool) or not isinstance(rec[key], int):
            raise LinkExit(EXIT_USAGE, f"usage error: {path}: {key} is not a number")
    return dict(rec)


def _overlay(args, rec: dict) -> dict:
    out = dict(rec)
    for flag, key in (
        ("facility_id", "pakTransportFacilityId"),
        ("facility_name", "pakTransportFacilityName"),
        ("url", "pakTransportLumberjackUrl"),
        ("port", "pakTransportLumberjackPort"),
    ):
        value = getattr(args, flag)
        if value is not None:
            out[key] = value
    if args.map is not None:
        out["pakTransportBayLaneMappings"] = list(args.map)
    if args.serial is not None:
        out["pakTransportLumberjackId"] = args.serial
    return out


def _desired(args, ctx: Context) -> tuple[dict, dict | None]:
    """(the record to save, the stored record it replaces or None)."""
    if args.new_id and not args.from_file:
        raise LinkExit(EXIT_USAGE, "usage error: --new-id needs --from")
    if args.from_file:
        base = _load_from(args.from_file, args.id)
        if args.new_id:
            base["pakTransportConfigId"] = pr.new_config_id()
            before = None
        else:
            try:
                before = ctx.guard(base["pakTransportConfigId"])
            except LinkExit as exc:
                raise LinkExit(exc.code, exc.message + " To save the file's record as a new link, add --new-id.") from None
    elif args.id:
        before = ctx.guard(args.id)
        base = dict(before)
    else:
        missing = [f for f, v in (("--serial", args.serial), ("--facility-id", args.facility_id), ("--facility-name", args.facility_name)) if v is None]
        if missing:
            raise LinkExit(EXIT_USAGE, f"usage error: a create needs {', '.join(missing)} (or give --id to edit)")
        url = args.url if args.url is not None else ctx.ownership.default_url(args.serial)
        if url is None:
            raise LinkExit(EXIT_REFUSED, f"refused: LJ {args.serial} has no LAS profile URL to default to; give --url")
        base = {
            "pakTransportConfigId": pr.new_config_id(),
            "pakTransportFacilityId": args.facility_id,
            "pakTransportFacilityName": args.facility_name,
            "pakTransportLumberjackId": args.serial,
            "pakTransportLumberjackUrl": url,
            "pakTransportLumberjackPort": pr.DEFAULT_PORT,
            "pakTransportBayLaneMappings": [],
        }
        before = None
    want = _overlay(args, base)
    if before is not None and want["pakTransportLumberjackId"] != before["pakTransportLumberjackId"] and not args.allow_move:
        raise LinkExit(
            EXIT_USAGE,
            f"usage error: this moves link {before['pakTransportConfigId']} from LJ {before['pakTransportLumberjackId']} "
            f"to LJ {want['pakTransportLumberjackId']}; add --allow-move if that is meant",
        )
    return want, before


def cmd_set(args) -> int:
    ctx = _context(args.access_token)
    want, before = _desired(args, ctx)
    action = "create" if before is None else "update"
    config_id = want["pakTransportConfigId"]
    others = [r for r in ctx.visible if r["pakTransportConfigId"].lower() != config_id.lower()]
    problems = pr.preflight(want, others, ctx.ownership)
    doc: dict[str, Any] = {"action": action, "configId": config_id, "before": pr.canonical(before) if before else None}
    if problems:
        doc.update(status="refused", problems=problems)
        raise LinkExit(EXIT_REFUSED, "refused by preflight (nothing sent):\n  - " + "\n  - ".join(problems), doc)
    want = pr.canonical(want)
    doc["after"] = want
    changes = pr.diff(before, want)
    if not changes:
        doc["status"] = "no-op"
        _say(args, f"link {config_id} already matches; nothing to do")
        _emit(args, doc)
        return EXIT_OK
    _say(args, f"{action} link {config_id} on LJ {want['pakTransportLumberjackId']}:")
    for key, old, new in changes:
        _say(args, f"  {key}: {json.dumps(old)} -> {json.dumps(new)}")
    doc["changes"] = [{"field": k, "old": o, "new": n} for k, o, n in changes]
    if args.dry_run or not args.yes:
        doc["status"] = "preview"
        _say(args, "preview only; add --yes to save" + (" (--dry-run wins)" if args.dry_run else ""))
        _emit(args, doc)
        return EXIT_OK

    backup = _write_backup(args.backup_dir, action, config_id, before, want)
    doc["backup"] = str(backup)
    _say(args, f"backup: {backup}")
    sent_ok, status, body = _send_write(args, doc, pr.REPSERT, want)

    serials = {want["pakTransportLumberjackId"]} | ({before["pakTransportLumberjackId"]} if before else set())
    try:
        after = [r for r in pr.list_configs(args.access_token, sorted(serials)) if r["pakTransportConfigId"].lower() == config_id.lower()]
    except pr.RouteFailure as exc:
        doc["status"] = "unverified"
        raise LinkExit(EXIT_UNVERIFIED, f"saved state unknown: the read-back failed: {exc}. Backup: {backup}", doc) from exc
    got = pr.canonical(after[0]) if len(after) == 1 else None
    doc["readBack"] = got
    if before is None:
        undo = f"{SCRIPT_CMD} delete --id {config_id} --yes"
    else:
        # Undoing a move is itself a move back, which needs --allow-move.
        moved = before["pakTransportLumberjackId"] != want["pakTransportLumberjackId"]
        undo = f"{SCRIPT_CMD} set --from {shlex.quote(str(backup))}{' --allow-move' if moved else ''} --yes"
    if sent_ok and got == want:
        doc.update(status="saved", undo=undo)
        _say(args, f"saved and read back. Undo: {undo}")
        _emit(args, doc)
        return EXIT_OK
    unchanged = got == (pr.canonical(before) if before else None)
    if not sent_ok and unchanged:
        doc["status"] = "not-saved"
        code = EXIT_REFUSED if status == 403 else EXIT_FAILURE
        raise LinkExit(code, f"nothing was saved (HTTP {status}: {body}); the read-back matches the record from before", doc)
    doc["status"] = "mismatch"
    raise LinkExit(
        EXIT_UNVERIFIED,
        f"the read-back does not match what was sent (HTTP {status}). Check with get; backup: {backup}",
        doc,
    )


# ─────────────────────────────── delete ───────────────────────────────


def cmd_delete(args) -> int:
    ctx = _context(args.access_token)
    before = pr.canonical(ctx.guard(args.id))
    doc: dict[str, Any] = {"action": "delete", "configId": args.id, "before": before}
    _say(args, "delete (hard; no trash):")
    for line in describe(before):
        _say(args, "  " + line)
    if args.dry_run or not args.yes:
        doc["status"] = "preview"
        _say(args, "preview only; add --yes to delete" + (" (--dry-run wins)" if args.dry_run else ""))
        _emit(args, doc)
        return EXIT_OK
    backup = _write_backup(args.backup_dir, "delete", args.id, before, None)
    doc["backup"] = str(backup)
    _say(args, f"backup: {backup}")
    sent_ok, status, body = _send_write(args, doc, pr.DELETE, before["pakTransportConfigId"])
    try:
        left = [r for r in pr.list_configs(args.access_token, [before["pakTransportLumberjackId"]]) if r["pakTransportConfigId"].lower() == args.id]
    except pr.RouteFailure as exc:
        doc["status"] = "unverified"
        raise LinkExit(EXIT_UNVERIFIED, f"delete state unknown: the read-back failed: {exc}. Backup: {backup}", doc) from exc
    undo = f"{SCRIPT_CMD} set --from {shlex.quote(str(backup))} --new-id --yes"
    if sent_ok and not left:
        doc.update(status="deleted", undo=undo)
        _say(args, f"deleted and read back (gone). Undo (re-creates it under a new id): {undo}")
        _emit(args, doc)
        return EXIT_OK
    if not sent_ok and left and pr.canonical(left[0]) == before:
        doc["status"] = "not-deleted"
        code = EXIT_REFUSED if status == 403 else EXIT_FAILURE
        raise LinkExit(code, f"nothing was deleted (HTTP {status}: {body}); the link is still there", doc)
    doc["status"] = "mismatch"
    raise LinkExit(EXIT_UNVERIFIED, f"unexpected delete outcome (HTTP {status}); check with list. Backup: {backup}", doc)


# ─────────────────────────────── one write ───────────────────────────────


def _send_write(args, doc: dict, endpoint: str, body: Any) -> tuple[bool, int | None, str]:
    """Send one write (no retry). Returns (ok, HTTP status, a short reason).

    OnPing passes a cloud-app rejection on as HTTP 500 wrapping the cloud's
    status and message; that is unwrapped so the reason reads like the cloud's.
    """
    try:
        resp = pr.send(args.access_token, endpoint, body)
    except pr.RouteFailure as exc:
        doc["http"] = {"status": None, "body": str(exc)}
        _say(args, f"the write failed to send or its answer was lost: {exc}")
        return False, None, str(exc)
    status = resp.status_code
    cloud_status, cloud_msg = pr.cloud_error(resp)
    reason = f"the cloud app answered {cloud_status}: {cloud_msg}" if cloud_status else pr.body_text(resp)
    doc["http"] = {"status": status, "cloudStatus": cloud_status, "cloudMessage": cloud_msg,
                   "body": pr.body_text(resp)}
    if status != 200:
        _say(args, f"the write answered HTTP {status}: {reason}")
        if 502 in (status, cloud_status):
            _say(args, "a 502 means a cloud call failed, usually registering the LJ in the switcher; the read-back below says whether anything was saved")
    return status == 200, status, reason


# ─────────────────────────────── backup ───────────────────────────────


def _write_backup(directory: str, action: str, config_id: str, before: dict | None, after: dict | None) -> Path:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = d / f"pak-link-{config_id}-{stamp}.json"
    doc = {
        "kind": BACKUP_KIND,
        "takenAt": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "configId": config_id,
        "before": before,
        "after": after,
    }
    with open(path, "x") as fh:  # never overwrite a backup
        fh.write(json.dumps(doc, indent=2) + "\n")
        fh.flush()
    return path


def main(argv: list[str] | None = None) -> int:
    args = None
    try:
        args = token_source.parse(build_parser(), argv)
        return {"list": cmd_list, "get": cmd_get, "export": cmd_export, "set": cmd_set, "delete": cmd_delete}[args.command](args)
    except LinkExit as exc:
        if exc.doc is not None and getattr(args, "json", False):
            print(json.dumps(exc.doc, indent=2))
        print(exc.message, file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
