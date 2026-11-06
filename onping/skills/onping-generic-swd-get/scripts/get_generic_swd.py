# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Show one generic-SWD kiosk's configuration, live lane states and tickets. Read-only.

Usage:
  get_generic_swd.py TOKEN UUID [--live] [--tickets N] [--output FILE] [--json]

The kiosk must be in a group you own or belong to (exit 3 otherwise).
--live reads the lane states from the kiosk (one PID poll per lane on the
Lumberjack). --tickets N reads the N most recent tickets. --output FILE writes
the configuration in the backup format that
`onping-generic-swd-update ... replace --from FILE` reads.

Exit codes: 0 ok; 1 a read failed (the configuration is still printed when
only --live or --tickets failed); 2 usage; 3 refused.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _generic_swd_routes import cli, guard, model, routes  # noqa: E402
from _token_input import shapes, token_source

MAX_TICKETS = 100


def build_parser() -> cli.Parser:
    p = cli.Parser(prog="get_generic_swd.py", description="Show one generic-SWD kiosk.")
    p.add_argument("uuid", help="the kiosk UUID (from onping-generic-swd-list)", type=shapes.uuid_arg)
    p.add_argument("--live", action="store_true", help="also read the current lane states")
    p.add_argument("--tickets", type=int, metavar="N", help=f"also read the N most recent tickets (1-{MAX_TICKETS})")
    p.add_argument("--output", metavar="FILE", help="write the configuration to FILE (backup format)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def _value(v) -> str:
    return "-" if v is None else model.num_text(v) if isinstance(v, (int, float)) else str(v)


def lane_lines(m: dict, enrich: dict[int, dict]) -> list[str]:
    out = []
    for ln in sorted(m["lanes"], key=lambda x: x["number"]):
        e = enrich.get(ln["number"], {})
        rd, wr = e.get("read", {}), e.get("write", {})
        out.append(f"lane {ln['number']}:")
        out.append(f"  read PID  {ln['read_pid']}  {rd.get('laneParamName') or ''}".rstrip())
        out.append(f"    raw {_value(rd.get('laneParamRawValue'))}  masked {_value(rd.get('laneParamMaskedValue'))}"
                   f"  status {model.status_text(rd.get('laneParamStatus')) if rd.get('laneParamStatus') is not None else '-'}")
        if rd.get("laneParamRawValue") is not None and rd.get("laneParamMaskedValue") is None:
            out.append("    note: the read PID has a value but no masked value; the mask script did not evaluate")
        out.append(f"  script    {json.dumps(ln['script'])}")
        out.append(f"  write PID {ln['write_pid']}  {wr.get('laneParamName') or ''}".rstrip())
        out.append(f"  waiting-to-start value {model.num_text(ln['wait'])}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = token_source.parse(parser, argv, is_id=shapes.is_uuid)
    if not model.valid_uuid(args.uuid):
        parser.error(f"not a kiosk UUID: {args.uuid}")
    if args.tickets is not None and not (1 <= args.tickets <= MAX_TICKETS):
        parser.error(f"--tickets must be from 1 to {MAX_TICKETS}")
    if args.output and Path(args.output).exists():
        parser.error(f"--output {args.output} already exists; choose a new file")

    try:
        who = guard.caller(args.access_token)
        kiosk = guard.find_kiosk(args.access_token, who, args.uuid, write=False)
    except guard.Refused as exc:
        return cli.fail(args.json, cli.EXIT_REFUSED, f"refused: {exc}")
    try:
        raw = routes.kiosk_config(args.access_token, kiosk.uuid)
        m = model.from_wire(raw)
    except (routes.RouteFailure, model.ModelError) as exc:
        return cli.fail(args.json, cli.EXIT_READ, f"read failed: {exc}", {"kiosk": kiosk.doc(who)})
    enrich = model.enrichment(raw)
    errors, warnings = model.validate(m)

    doc: dict = {"ok": True, "kiosk": kiosk.doc(who), "config": model.to_wire(m),
                 "lanes_reported": {str(k): v for k, v in enrich.items()},
                 "stored_config_problems": errors, "warnings": warnings}
    lines = [f"kiosk {kiosk.uuid}  {kiosk.name!s}",
             f"group {kiosk.group_id} ({who.name(kiosk.group_id)}), {'owned' if kiosk.owned else 'member only: read-only for you'}",
             f"name: {json.dumps(m['name'])}", *lane_lines(m, enrich), "status map:"]
    lines += [f"  {model.num_text(v)} -> {model.status_text(s)}" for v, s in sorted(m["status_map"], key=lambda p: float(p[0]))]
    if errors:
        lines.append("the stored configuration fails these checks (an update must fix them first):")
        lines += [f"  - {e}" for e in errors]
    lines += [f"warning: {w}" for w in warnings]

    code = cli.EXIT_OK
    if args.live:
        try:
            states = routes.kiosk_lanes(args.access_token, kiosk.uuid)
            doc["live"] = {"ok": True, "lanes": states}
            lines.append("live lane states:")
            for s in states:
                extra = f" ({s.get('message')})" if s.get("message") else ""
                lines.append(f"  lane {s.get('lane')}: {s.get('status')}{extra}")
        except routes.RouteFailure as exc:
            doc["live"] = {"ok": False, "error": str(exc)}
            lines.append(f"live lane states: FAILED: {exc}")
            code = cli.EXIT_READ
    if args.tickets:
        try:
            tickets = routes.kiosk_tickets(args.access_token, kiosk.uuid, args.tickets)
            doc["tickets"] = {"ok": True, "tickets": tickets}
            lines.append(f"recent tickets ({len(tickets)}):")
            for t in tickets:
                st = t.get("ticketStatus") or {}
                lines.append(f"  {t.get('ticketId')}  lane {t.get('ticketLane')}  {st.get('tag')}  "
                             f"{json.dumps(st.get('contents'))[:160]}")
        except routes.RouteFailure as exc:
            doc["tickets"] = {"ok": False, "error": str(exc)}
            lines.append(f"recent tickets: FAILED: {exc}")
            code = cli.EXIT_READ
    if args.output:
        backup = model.backup_doc({"uuid": kiosk.uuid, "group_id": kiosk.group_id}, m, cli.utc_now())
        Path(args.output).write_text(json.dumps(backup, indent=2, sort_keys=True) + "\n")
        doc["output"] = args.output
        lines.append(f"wrote {args.output}")
    doc["ok"] = code == cli.EXIT_OK
    cli.emit(args.json, doc, lines)
    return code


if __name__ == "__main__":
    sys.exit(main())
