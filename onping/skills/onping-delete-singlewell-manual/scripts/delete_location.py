# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete one OnPing singlewell-manual location, previewing by default.

    delete_location.py LOCATION_ID [--allow-parameters] [--backup PATH]
                       [--yes] [--dry-run] [--json]

It reads the location with POST /singlewellmanual/get/loc, refuses one in a
group the caller does not own, and refuses one that still has parameters
unless --allow-parameters is given. With --yes (and without --dry-run) it
writes the full get/loc answer to a backup file, posts
POST /singlewellmanual/delete [id] exactly once, and decides the outcome from a
read-back, never from the HTTP status or body: servers before the 2026.11.5.1
fix answered HTTP 200 whether the delete worked or not.

Gone means (older servers): get/loc answers "failed to find single well manual
location by id" AND the site's manual listing no longer contains the id. A
server with the ownership fix answers 403 for a deleted or missing location
instead, which reads as unknown: a delete that worked (HTTP 200 Success) can
then end in exit 4 UNKNOWN. That is safe (the backup is kept, nothing is
retried); confirm by listing the site's locations. Likewise a missing location
before the delete reads as unknown (exit 1) on a fixed server, not exit 3.

Exit codes: 0 preview or verified gone; 1 a request failed before anything was
written; 2 usage; 3 refusal (missing on older servers, not owned, has
parameters, partial record); 4 still present, partly gone, or the read-back failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _singlewell_manual_routes import routes as R  # noqa: E402
from _singlewell_manual_routes import swm_http as H  # noqa: E402
from _token_input import shapes, token_source

EXIT_OK, EXIT_REQUEST, EXIT_USAGE, EXIT_REFUSED, EXIT_UNKNOWN = 0, 1, 2, 3, 4


class Out:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json
        self.report: dict[str, Any] = {"action": "delete"}

    def say(self, line: str = "") -> None:
        if not self.as_json:
            print(line)

    def done(self, code: int) -> int:
        self.report["exit"] = code
        if self.as_json:
            print(json.dumps(self.report, indent=2))
        return code


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Delete one singlewell-manual location (preview unless --yes).")
    p.add_argument("location_id", type=shapes.int_arg, help="the location's LocationIdRef")
    p.add_argument("--allow-parameters", action="store_true",
                   help="delete even though the location has parameters (their PIDs are orphaned)")
    p.add_argument("--backup", help="backup path (default ./singlewell-manual-<id>-<UTC>.backup.json)")
    p.add_argument("--yes", action="store_true", help="actually delete")
    p.add_argument("--dry-run", action="store_true", help="preview only; wins over --yes")
    p.add_argument("--json", action="store_true", help="print one JSON report")
    a = token_source.parse(p, argv, is_id=shapes.is_int)
    if a.location_id <= 0:
        p.error("location_id must be a positive integer")
    return a


def default_backup(ref: int) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"singlewell-manual-{ref}-{stamp}.backup.json")


def write_backup(path: Path, ref: int, config: dict[str, Any]) -> None:
    doc = {
        "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "route": R.GET_LOC,
        "location_id": ref,
        "note": (
            "A record, not an undo: re-creating from this gives a new location id "
            "and new parameter ids."
        ),
        "config": config,
    }
    with open(path, "x", encoding="utf-8") as fh:  # never overwrite
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def residue_lines(n_params: int) -> list[str]:
    left = list(R.DELETE_LEAVES)
    if n_params:
        left.append(R.PARAMETER_RESIDUE)
    return left


def main(argv: list[str] | None = None) -> int:
    a = parse(argv)
    ref = a.location_id
    out = Out(a.json)
    out.report["location_id"] = ref

    st = H.read_location(a.access_token, ref)
    out.report["before"] = st.kind
    if st.kind == "missing":
        out.say(f"REFUSED: there is no manual location {ref} ({st.detail}). Nothing to delete.")
        return out.done(EXIT_REFUSED)
    if st.kind == "partial":
        out.say(
            f"REFUSED: location {ref} has a manual record but get/loc says {st.detail!r}, "
            "so its group cannot be read and the ownership gate cannot pass."
        )
        return out.done(EXIT_REFUSED)
    if st.kind != "present" or st.config is None:
        print(f"Could not read location {ref}; nothing was written: {st.detail}", file=sys.stderr)
        return out.done(EXIT_REQUEST)
    cfg = st.config
    group = cfg.get("manualLocationGroupId")
    site = cfg.get("locationSiteId")
    tags = cfg.get("locationData") or []
    try:
        owned = H.owned_groups(a.access_token)
        listed_before = H.manual_at_site(a.access_token, site)
    except H.RouteFailure as exc:
        print(f"Preflight read failed; nothing was written: {exc}", file=sys.stderr)
        return out.done(EXIT_REQUEST)

    out.report.update({
        "name": cfg.get("manualLocationName"),
        "group": group,
        "group_owned": group in owned,
        "company": cfg.get("locationCompanyId"),
        "site": site,
        "parameters": len(tags),
        "listed_before": ref in listed_before,
        "removes": list(R.DELETE_REMOVES),
        "leaves": residue_lines(len(tags)),
    })
    out.say(f"Delete singlewell-manual location {ref} {cfg.get('manualLocationName')!r}")
    out.say(f"  url {cfg.get('manualLocationUrl')} port {cfg.get('manualLocationPort')}")
    out.say(f"  company {cfg.get('locationCompanyId')}, site {site}, group {group} ({owned.get(group) or 'not owned'})")
    out.say(f"  parameters: {len(tags)}; listed at site: {ref in listed_before}")
    out.say(f"  removes: {', '.join(R.DELETE_REMOVES)}")
    out.say(f"  leaves (no route removes them): {', '.join(residue_lines(len(tags)))}")
    out.say("  There is no undo. The backup is a record: re-creating gives a new id and new PIDs.")

    problems = []
    if group not in owned:
        problems.append(f"group {group} is not one of your owned groups; this skill refuses")
    if tags and not a.allow_parameters:
        problems.append(
            f"location {ref} has {len(tags)} parameter(s); deleting orphans their PIDs. "
            "Pass --allow-parameters to delete anyway."
        )
    if problems:
        out.report["refused"] = problems
        for prob in problems:
            out.say(f"REFUSED: {prob}")
        return out.done(EXIT_REFUSED)

    backup = Path(a.backup) if a.backup else default_backup(ref)
    out.say(f"  backup: {backup}")
    if not a.yes or a.dry_run:
        out.report["mode"] = "preview"
        out.say("Preview only. Nothing was sent. Re-run with --yes to delete.")
        return out.done(EXIT_OK)

    out.report["mode"] = "write"
    try:
        write_backup(backup, ref, cfg)
    except OSError as exc:
        print(f"Could not write the backup {backup}; nothing was deleted: {exc}", file=sys.stderr)
        return out.done(EXIT_REQUEST)
    out.report["backup"] = str(backup)
    out.say(f"Backup written: {backup}")

    res = H.post_once(a.access_token, R.DELETE, [ref])
    out.report["response"] = {"status": res.status, "body": res.body, "error": res.error}
    if not res.sent:
        out.say(f"NOT SENT: {res.error}. Nothing was deleted.")
        return out.done(EXIT_REQUEST)
    body_ok = isinstance(res.body, dict) and res.body.get("response") == "Success"
    out.say(f"{R.DELETE}: HTTP {res.status} {res.text if res.error is None else res.error}")

    after = H.read_location(a.access_token, ref)
    try:
        listed_after = H.manual_at_site(a.access_token, site)
        still_listed: bool | None = ref in listed_after
    except H.RouteFailure as exc:
        still_listed = None
        out.say(f"  could not read the site listing: {exc}")
    out.report["readback"] = {"get_loc": after.kind, "detail": after.detail, "listed_at_site": still_listed}

    if after.kind == "missing" and still_listed is False:
        out.say(
            f"Verified gone: get/loc {ref} answers {R.MSG_NO_MANUAL!r} and the site "
            "listing no longer contains it."
        )
        if not body_ok:
            out.say(
                f"  NOTE: the delete body was not Success ({res.text or res.error}). If the "
                "Lumberjack is unreachable, get/loc reads a surviving manual record as missing; "
                "check again once it is reachable."
            )
            out.report["note"] = "gone by read-back, but the delete body was not Success"
        out.say(f"  left behind: {', '.join(residue_lines(len(tags)))}")
        return out.done(EXIT_OK)
    if after.kind == "present":
        out.say(f"NOT DELETED: get/loc {ref} still returns the location. Server said: {res.text or res.error}")
    elif after.kind == "partial":
        out.say(f"PARTLY DELETED: get/loc {ref} says {after.detail!r} (the manual record survives).")
    elif after.kind == "missing" and still_listed is None:
        out.say("UNKNOWN: the manual record reads as gone but the site listing could not be read.")
    elif after.kind == "missing":
        out.say(f"PARTLY DELETED: the manual record is gone but the site listing still has {ref} (the Mongo location survives).")
    else:
        out.say(f"UNKNOWN: the read-back failed: {after.detail}")
    out.say(f"  backup: {backup}")
    return out.done(EXIT_UNKNOWN)


if __name__ == "__main__":
    sys.exit(main())
