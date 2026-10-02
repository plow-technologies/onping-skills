# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List OnPing event tables from dashboard JSON, with a reverse PID lookup.

No route lists event tables, and a table's title lives only in its dashboard,
so this script walks dashboard JSON: `panels[] -> carr.arr[]` content objects,
recursing into `sub.panels[]`. A content object whose `plist` holds
`EventTableConfig` is an event table.

  --dashboard KEY      one dashboard; KEY is the `o…` key from a
                       /v3/dashboards/<KEY> URL. The key is first checked against
                       GET /data/dashboard/values, because GET /data/dashboard
                       silently returns your DEFAULT dashboard for a key it
                       cannot parse.
  --all                every dashboard you can see (GET /data/dashboard/list,
                       large and unpaginated).
  --title TEXT         keep tables whose title equals TEXT, ignoring case
                       (repeatable).
  --references-pid N   read each table's config and keep the tables that bind
                       PID N. A table whose read fails is listed as UNCHECKED,
                       never dropped, and the script then exits 1.

Read-only — no `--yes` gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _event_table_routes.event_table_http import EventTableError, die, get_json, post_json
from _event_table_routes.keys import describe, pid_matches
from _event_table_routes.routes import ROUTES

_HEX24 = re.compile(r"^o?([0-9a-fA-F]{24})$")


def normalise_key(raw) -> str | None:
    """Return the 24-hex body of a dashboard key, or None if it is not one."""
    text = raw if isinstance(raw, str) else json.dumps(raw)
    m = _HEX24.match(text.strip().strip('"'))
    return m.group(1).lower() if m else None


def _uuid_of(pointer) -> str | None:
    raw = pointer.get("eventTableUUID") if isinstance(pointer, dict) else None
    if isinstance(raw, dict):
        raw = raw.get("unEventTableUUID")
    return raw if isinstance(raw, str) else None


def walk(node, panel: str, found: list[dict]) -> None:
    """Collect {panel, title, uuid} for every event-table content object."""
    if isinstance(node, list):
        for item in node:
            walk(item, panel, found)
        return
    if not isinstance(node, dict):
        return
    if "mconfig" in node and ("carr" in node or "sub" in node):
        mconfig = node.get("mconfig") or {}
        panel = node.get("name") or (mconfig.get("text") if isinstance(mconfig, dict) else None) or panel
    plist = node.get("plist")
    if isinstance(plist, dict) and "EventTableConfig" in plist:
        found.append({
            "panel": panel,
            "title": node.get("title"),
            "uuid": _uuid_of(plist["EventTableConfig"]),
        })
    for value in node.values():
        walk(value, panel, found)


def dashboards(token: str, args) -> list[tuple[str, dict]]:
    """Return [(dashboard key as o…, dashboard JSON)]."""
    if args.all:
        listing = get_json(token, ROUTES["dashboard_list"]["endpoint"])
        out = []
        for entry in listing:
            hex24 = normalise_key(entry.get("key"))
            out.append((f"o{hex24}" if hex24 else str(entry.get("key")), entry.get("value") or {}))
        return out

    wanted = {}
    for raw in args.dashboard:
        hex24 = normalise_key(raw)
        if hex24 is None:
            raise EventTableError(f"not a dashboard key (expected `o` + 24 hex): {raw!r}")
        wanted[hex24] = raw
    values = get_json(token, ROUTES["dashboard_values"]["endpoint"])
    names = {normalise_key(v.get("key")): v.get("value") for v in values}
    out = []
    for hex24 in wanted:
        if hex24 not in names:
            raise EventTableError(
                f"dashboard o{hex24} is not among the dashboards you can see "
                f"(GET /data/dashboard/values). Not reading it, because "
                f"GET /data/dashboard would silently return your default dashboard."
            )
        dash = get_json(token, ROUTES["dashboard"]["endpoint"], params={"dashId": f"o{hex24}"})
        if dash.get("name") != names[hex24]:
            raise EventTableError(
                f"GET /data/dashboard returned {dash.get('name')!r} for o{hex24}, "
                f"expected {names[hex24]!r} — refusing a possible fallback to the default dashboard."
            )
        out.append((f"o{hex24}", dash))
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description="List OnPing event tables from dashboard JSON. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--dashboard", action="append", metavar="KEY",
                     help="dashboard key `o…` from a /v3/dashboards/<KEY> URL (repeatable)")
    src.add_argument("--all", action="store_true", help="every dashboard you can see")
    p.add_argument("--title", action="append", default=[], help="keep this widget title (repeatable)")
    p.add_argument("--references-pid", type=int, metavar="N", help="keep tables that bind PID N")
    p.add_argument("--json", action="store_true", help="emit records as JSON")
    args = p.parse_args()

    try:
        dashes = dashboards(args.access_token, args)
    except EventTableError as err:
        die(err)

    records = []
    for key, dash in dashes:
        found: list[dict] = []
        walk(dash.get("panels", []), "", found)
        for r in found:
            records.append({"dashboardKey": key, "dashboardName": dash.get("name"), **r})

    wanted_titles = {t.strip().lower() for t in args.title}
    if wanted_titles:
        records = [r for r in records if (r["title"] or "").strip().lower() in wanted_titles]

    unchecked = 0
    if args.references_pid is not None:
        kept = []
        for i, r in enumerate(records, 1):
            print(f"reading config {i}/{len(records)}: {r['title']!r}", file=sys.stderr)
            try:
                config = post_json(args.access_token, ROUTES["config"]["endpoint"],
                                   {"unEventTableUUID": r["uuid"]})
            except EventTableError as err:
                kept.append({**r, "status": "UNCHECKED", "error": str(err)})
                unchecked += 1
                continue
            as_pid, as_vpid = pid_matches(config, args.references_pid)
            if as_pid:
                kept.append({**r, "status": "REFERENCED", "deleted": config.get("eventTableDeleted"),
                             "bindings": [describe(b) for b in as_pid],
                             "vpidNote": [describe(b) for b in as_vpid]})
        records = kept

    if args.json:
        print(json.dumps(records, indent=2))
    else:
        if args.references_pid is not None:
            print(f"event tables that bind PID {args.references_pid}: "
                  f"{sum(r['status'] == 'REFERENCED' for r in records)}"
                  + (f" ({unchecked} UNCHECKED)" if unchecked else ""))
        for r in records:
            status = f"[{r['status']}] " if "status" in r else ""
            print(f"{status}{r['title']!r}  uuid={r['uuid']}")
            print(f"    dashboard {r['dashboardKey']} {r['dashboardName']!r}, panel {r['panel']!r}")
            for line in r.get("bindings", []):
                print(f"    {line}")
            for line in r.get("vpidNote", []):
                print(f"    note: {line} (a VPID, not the PID)")
            if r.get("error"):
                print(f"    error: {r['error']}")
        if not records:
            print("no event tables matched")
    if unchecked:
        sys.exit(1)


if __name__ == "__main__":
    main()
