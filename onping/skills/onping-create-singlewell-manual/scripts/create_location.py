# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Create one OnPing singlewell-manual location, previewing by default.

    create_location.py TOKEN --lj SERIAL --company ID --site ID --group GID --name NAME
                       [--port 13001] [--notes TEXT] [--yes] [--dry-run] [--json]

Preflight (runs in the preview too): the Lumberjack has a LAS profile with a
lumberjackUrl, the caller owns the group, the site belongs to the company, and
no manual location at the site already has the name. With --yes (and without
--dry-run) it posts POST /singlewellmanual/location/add exactly once, then
reads the new id back with POST /singlewellmanual/get/loc and the site listing.

Exit codes: 0 preview or verified create; 1 a request failed before anything
was written; 2 usage; 3 preflight refusal; 4 partial, unknown or a read-back
mismatch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _singlewell_manual_routes import routes as R  # noqa: E402
from _singlewell_manual_routes import swm_http as H  # noqa: E402
from _token_input import token_source  # noqa: E402

EXIT_OK, EXIT_REQUEST, EXIT_USAGE, EXIT_REFUSED, EXIT_UNKNOWN = 0, 1, 2, 3, 4

DELETE_CMD = (
    'uv run ~/.claude/skills/onping-delete-singlewell-manual/scripts/delete_location.py '
    '{ref} --yes'
)


class Out:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json
        self.report: dict[str, Any] = {"action": "create"}

    def say(self, line: str = "") -> None:
        if not self.as_json:
            print(line)

    def done(self, code: int) -> int:
        self.report["exit"] = code
        if self.as_json:
            print(json.dumps(self.report, indent=2))
        return code


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create one singlewell-manual location (preview unless --yes).")
    p.add_argument("--lj", type=int, required=True, help="Lumberjack serial; its URL comes from the LAS profile")
    p.add_argument("--company", type=int, required=True)
    p.add_argument("--site", type=int, required=True)
    p.add_argument("--group", required=True, help="owned group id (o + 24 hex)")
    p.add_argument("--name", required=True)
    p.add_argument("--port", type=int, default=R.DEFAULT_PORT)
    p.add_argument("--notes", default="")
    p.add_argument("--yes", action="store_true", help="actually create")
    p.add_argument("--dry-run", action="store_true", help="preview only; wins over --yes")
    p.add_argument("--json", action="store_true", help="print one JSON report")
    a = token_source.parse(p, argv)
    a.name = a.name.strip()
    if not a.name:
        p.error("--name must not be empty")
    if not 0 < a.port < 65536:
        p.error("--port must be between 1 and 65535")
    if not a.group.strip():
        p.error("--group must not be empty")
    return a


def build_body(a: argparse.Namespace, url: str) -> dict[str, Any]:
    return {
        "manualLocationName": a.name,
        "manualLocationId": None,
        "manualLocationUrl": url,
        "manualLocationPort": a.port,
        "manualLocationGroupId": a.group,
        "manualLocationRefId": None,
        "locationCompanyId": a.company,
        "locationSiteId": a.site,
        "locationNotes": a.notes,
        "locationData": [],
        "coordinates": None,
    }


def preflight(token: str, a: argparse.Namespace, out: Out) -> tuple[str | None, list[str]]:
    """(lumberjack url, problems). Raises H.RouteFailure on a failed read."""
    problems: list[str] = []
    url = H.lumberjack_url(token, a.lj)
    if url is None:
        problems.append(f"Lumberjack {a.lj} has no LAS profile with a lumberjackUrl")
    owned = H.owned_groups(token)
    if a.group not in owned:
        problems.append(
            f"group {a.group} is not one of your {len(owned)} owned groups; "
            "this skill refuses"
        )
    sites = H.company_sites(token, a.company)
    if a.site not in sites:
        problems.append(f"site {a.site} is not a live site of company {a.company}")
    at_site = H.manual_at_site(token, a.site)
    same = sorted(ref for ref, nm in at_site.items() if (nm or "").strip() == a.name)
    if same:
        problems.append(f"a manual location named {a.name!r} already exists at site {a.site}: {same}")
    out.report["checks"] = {
        "lumberjack_url_found": url is not None,
        "group_owned": a.group in owned,
        "group_name": owned.get(a.group),
        "site_in_company": a.site in sites,
        "name_free_at_site": not same,
        "manual_locations_at_site": len(at_site),
    }
    return url, problems


def compare(sent: dict[str, Any], got: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"field": k, "sent": sent[k], "got": got.get(k)}
        for k in R.READBACK_FIELDS
        if got.get(k) != sent[k]
    ]


def read_back(token: str, ref: int, body: dict[str, Any], out: Out) -> int:
    st = H.read_location(token, ref)
    rb: dict[str, Any] = {"get_loc": st.kind, "detail": st.detail}
    out.report["readback"] = rb
    if st.kind != "present" or st.config is None:
        out.say(f"Read-back FAILED: get/loc {ref} is {st.kind}: {st.detail}")
        return EXIT_UNKNOWN
    diffs = compare(body, st.config)
    rb["mismatches"] = diffs
    rb["coordinates"] = st.config.get("coordinates")
    try:
        listed = H.manual_at_site(token, body["locationSiteId"])
        rb["listed_at_site"] = ref in listed
        rb["listed_name"] = listed.get(ref)
    except H.RouteFailure as exc:
        rb["listed_at_site"] = None
        out.say(f"Read-back FAILED: could not read the site listing: {exc}")
        return EXIT_UNKNOWN
    for d in diffs:
        out.say(f"  mismatch {d['field']}: sent {d['sent']!r}, got {d['got']!r}")
    if not rb["listed_at_site"]:
        out.say(f"  location {ref} is not in the manual listing for site {body['locationSiteId']}")
    if diffs or not rb["listed_at_site"]:
        out.say(f"Read-back MISMATCH for location {ref}.")
        return EXIT_UNKNOWN
    out.say(
        f"Verified: get/loc {ref} matches every field sent "
        f"({', '.join(R.READBACK_FIELDS)}), and the site listing contains it."
    )
    return EXIT_OK


def report_unknown_by_name(token: str, body: dict[str, Any], out: Out) -> None:
    """After a lost response: say whether a location with the name now exists."""
    try:
        listed = H.manual_at_site(token, body["locationSiteId"])
    except H.RouteFailure as exc:
        out.say(f"  Could not read the site listing to look for it: {exc}")
        return
    refs = sorted(r for r, nm in listed.items() if (nm or "").strip() == body["manualLocationName"])
    out.report["found_by_name"] = refs
    if refs:
        out.say(f"  The site listing now has {body['manualLocationName']!r} as {refs}. Check with get/loc.")
    else:
        out.say(
            "  The site listing has no location with that name, but a partial create "
            "(MySQL row, switcher index, manual record) would not be listed."
        )


def main(argv: list[str] | None = None) -> int:
    a = parse(argv)
    out = Out(a.json)
    out.report.update({"lj": a.lj, "company": a.company, "site": a.site, "group": a.group, "name": a.name})
    try:
        url, problems = preflight(a.access_token, a, out)
    except H.RouteFailure as exc:
        print(f"Preflight read failed; nothing was written: {exc}", file=sys.stderr)
        return out.done(EXIT_REQUEST)
    body = build_body(a, url or "")
    out.report["body"] = body
    out.say(f"Create singlewell-manual location {a.name!r}")
    out.say(f"  Lumberjack {a.lj} -> {url or '(no url)'} port {a.port}")
    out.say(f"  company {a.company}, site {a.site}, group {a.group}")
    out.say("  body: " + json.dumps(body))
    if problems:
        out.report["refused"] = problems
        for prob in problems:
            out.say(f"REFUSED: {prob}")
        return out.done(EXIT_REFUSED)
    out.say("  checks: Lumberjack URL found, group owned, site in company, name free at site")
    out.say("  undo once created: " + DELETE_CMD.format(ref="<new id>"))
    if not a.yes or a.dry_run:
        out.report["mode"] = "preview"
        out.say("Preview only. Nothing was sent. Re-run with --yes to create.")
        return out.done(EXIT_OK)

    out.report["mode"] = "write"
    res = H.post_once(a.access_token, R.ADD, body)
    out.report["response"] = {"status": res.status, "body": res.body, "error": res.error}
    if not res.sent:
        out.say(f"NOT SENT: {res.error}. Nothing was written.")
        return out.done(EXIT_REQUEST)
    if res.error is not None:
        out.say(f"UNKNOWN: the request was sent but no response came back ({res.error}).")
        report_unknown_by_name(a.access_token, body, out)
        return out.done(EXIT_UNKNOWN)
    if res.status == 200 and isinstance(res.body, dict) and isinstance(res.body.get("int"), int):
        ref = res.body["int"]
        out.report["location_id"] = ref
        out.say(f"{R.ADD}: created location {ref}")
        code = read_back(a.access_token, ref, body, out)
        out.say("  undo: " + DELETE_CMD.format(ref=ref))
        return out.done(code)
    if res.status == 400:
        out.say(f"REJECTED (HTTP 400): {res.text}. The server did not parse the body; nothing was written.")
        return out.done(EXIT_REQUEST)
    if res.status == 500:
        stage, ref, exist = H.classify_add_failure(res.text)
        if stage is not None:
            missing = [r for r in R.ADD_ORDER if r not in exist]
            out.report.update({"failed_stage": stage, "location_id": ref, "residue": list(exist)})
            out.say(f"PARTIAL CREATE: the add route failed at {stage}.")
            out.say(f"  location id: {ref if ref is not None else 'not in the error text'}")
            out.say(f"  these records now exist: {', '.join(exist)}")
            out.say(f"  these were not written: {', '.join(missing)}")
            out.say(f"  server error: {res.text}")
            if ref is not None and R.ADD_ORDER[2] in exist:
                out.say("  the manual record exists; to remove it and any Mongo location: " + DELETE_CMD.format(ref=ref))
            out.say("  No route removes the MySQL row or the switcher index.")
            return out.done(EXIT_UNKNOWN)
    out.say(f"UNKNOWN: HTTP {res.status}: {res.text}")
    report_unknown_by_name(a.access_token, body, out)
    return out.done(EXIT_UNKNOWN)


if __name__ == "__main__":
    sys.exit(main())
