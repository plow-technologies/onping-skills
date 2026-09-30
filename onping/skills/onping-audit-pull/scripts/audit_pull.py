# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Pull the OnPing audit trail via POST /log/audit2/query (Bearer auth).

Read-only. The route is a POST but mutates no server state, so there is no --yes gate.

One route covers all three audit backends -- the OnPing audit server, RTU Manager write
audits, and the OnPing authentication server -- because the handler fans out and
normalizes 30 payload types into a single view.

Source of truth:
  route    onping/config/routes
  handler  onping/Handler/Audit/AuditService.hs
  query    onping-core Haxl audit client
"""

import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

QUERY_URL = "https://onping.plowtech.net/log/audit2/query"

# Page size is hardcoded to 10 in Client.hs and no request field reaches it,
# so there is deliberately no --size flag.
SERVER_PAGE_SIZE = 10

# Elasticsearch track_total_hits default. meta_count stops counting here, so at this
# exact value the figure is a lower bound rather than a total.
COUNT_SATURATION = 10000

# An empty page does NOT mean the walk is over. Elasticsearch returns audit POINTERS
# which queryAudit then hydrates from three backends; a page whose 10 pointers all fail
# to hydrate (permission-scoped away, or dangling) yields zero items while pagination is
# nowhere near done. Verified on `usertag`: pages 1-5 empty, then data resumed and ran
# for 70 more pages. Over 75 pages the empty runs were 5, 1, 4, 7, 2, 1 -- so the
# longest observed run is 7 and this default leaves headroom above it.
DEFAULT_EMPTY_PAGE_LIMIT = 10

# The 30 wire names from GET /log/audit2/available-audits (config/routes),
# mapped to their display names. Embedded rather than fetched: the list is a
# constant that changes only when OnPing ships a new audit type.
AUDIT_TYPES = {
    "group": "Groups",
    "usertag": "User Settings",
    "alarm": "Alarms",
    "masktype": "Masks",
    "callorder": "Call Orders",
    "location": "Locations",
    "site": "Sites",
    "company": "Companies",
    "dashboard": "Dashboards",
    "tflow": "TotalFlow Writes",
    "micrologix": "Micrologix Writes",
    "bristol": "Bristol Writes",
    "manual": "Manual Writes",
    "roctlp": "Roc TLP Writes",
    "modbus": "Modbus Flexible Writes",
    "controllogix": "ControlLogix Writes",
    "hazardpro": "Hazard Pro Writes",
    "opcua": "OPC UA Writes",
    "chartreport": "Chart Report Writes",
    "userauthentication": "Authentication",
    "virtualparameter": "Virtual Parameters",
    "unico": "Unico Writes",
    "lufkin": "Lufkin Writes",
    "mqttjson": "MqttJson Writes",
    "dnp3": "DNP3 Writes",
    "tablesource": "Table Sources",
    "tableview": "Table Views",
    "groupcapability": "Group Capability",
    "logtablesource": "Log Table Sources",
    "logtableview": "Log Table Views",
}

# available-audits omits vpalarm because the handler folds VP alarms into `alarm`
# (AuditService.hs, shim at Client.hs), but the query route accepts it and
# returns records. Accept it rather than second-guessing a caller who asks for it.
EXTRA_ACCEPTED_TYPES = {"vpalarm"}

ACCEPTED_TYPES = set(AUDIT_TYPES) | EXTRA_ACCEPTED_TYPES

CSV_COLUMNS = ["editedOn", "editedBy", "type", "action", "description", "json"]

MAX_AUTH_RETRIES = 3


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def parse_timestamp(raw: str, flag: str) -> datetime:
    """Validate an ISO 8601 timestamp locally so a typo costs no round trip.

    Both `Z` and numeric offsets are accepted by the route; fromisoformat handles
    offsets natively and needs `Z` rewritten for Python < 3.11. A timezone is
    mandatory -- the server rejects a naive timestamp with
    `400 ... could not parse date: Unexpected end-of-input, expecting timezone`,
    so catching it here saves a round trip.
    """
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        die(f"{flag} is not a valid ISO 8601 timestamp: {raw!r}")
    if parsed.tzinfo is None:
        die(
            f"{flag} must carry a timezone (`Z` or a numeric offset like `-05:00`); "
            f"OnPing rejects a naive timestamp: {raw!r}"
        )
    return parsed


def build_query_range(since: str | None, until: str | None) -> dict | None:
    """Map --since/--until onto SearchQueryRange (Query.hs).

    The payload shape differs per variant and this asymmetry is a wire requirement:
    RangeGte/RangeLte take a BARE STRING, RangeGteLte takes a TWO-ELEMENT ARRAY.
    """
    if since is not None and until is not None:
        return {"tag": "RangeGteLte", "contents": [since, until]}
    if since is not None:
        return {"tag": "RangeGte", "contents": since}
    if until is not None:
        return {"tag": "RangeLte", "contents": until}
    return None


def unquote_type(raw: str) -> str:
    """Strip the outer quotes from a double-encoded auditview_type.

    auditTypeFrontEndText (AuditFrontEndResult.hs) JSON-encodes the AuditType and
    stores the result in a Text field, so the value arrives as the literal 14
    characters "\"controllogix\"". Anything matching `controllogix` fails without this.
    """
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def looks_like_login_page(resp: requests.Response) -> bool:
    """An expired token yields a redirect or an HTML login body, not a clean 401."""
    if 300 <= resp.status_code < 400:
        return True
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        return True
    return "/auth/login" in resp.headers.get("Location", "")


def server_error_text(resp: requests.Response) -> str:
    """Surface the server's {"error": ...} verbatim, falling back to raw text."""
    try:
        payload = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}, non-JSON body:\n{resp.text}"
    if isinstance(payload, dict) and "error" in payload:
        return f"HTTP {resp.status_code}: {payload['error']}"
    return f"HTTP {resp.status_code}:\n{resp.text}"


def request_page(session: requests.Session, token: str, body: dict) -> dict:
    """Issue one query, retrying a bounded number of times on auth-ish responses."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    tries = 0
    while True:
        try:
            resp = session.post(
                QUERY_URL,
                json=body,
                headers=headers,
                allow_redirects=False,
                timeout=60,
            )
        except requests.RequestException as exc:
            die(f"request failed: {exc}")

        if looks_like_login_page(resp):
            tries += 1
            if tries >= MAX_AUTH_RETRIES:
                die(
                    "authentication failed -- the access token appears expired "
                    "(OnPing returned a login redirect or HTML body). "
                    "Get a fresh token from onping-login."
                )
            continue

        if resp.status_code == 500:
            # The handler logs the real cause server-side and returns a generic
            # message (AuditService.hs); there is no client-visible detail.
            die(
                f"{server_error_text(resp)} "
                "(detail is server-side only; retrying will not add information)"
            )

        if resp.status_code != 200:
            die(server_error_text(resp))

        try:
            return resp.json()
        except ValueError as exc:
            die(f"could not decode JSON response: {exc}\nRaw response:\n{resp.text}")


def walk(
    session: requests.Session,
    token: str,
    audit_types: list[str],
    terms: str,
    query_range: dict | None,
    max_pages: int | None,
    empty_page_limit: int,
) -> tuple[list[dict], int | None, str | None, int, int]:
    """Paginate the audit query to completion.

    Returns (items, server_reported_count, stop_reason, pages_fetched, empty_pages).
    stop_reason is None on a clean end, or "max_pages" / "empty_run" when the walk was
    cut short -- both of which mean records may remain.

    Two termination facts, both learned the hard way:

    1. A null meta_nextKey is the server's real end signal, but it arrives one page
       LATE. The key is built from the last hit of the page (Client.hs), so it
       stays non-null on the last page that still carries data: a 35-record query pages
       10, 10, 10, 5 -- each with a non-null key -- then returns 0 items with a null
       key. So the walk must keep going while the key is non-null.

    2. An empty page is NOT the end. Elasticsearch returns audit pointers which are
       then hydrated from three backends, and a page whose pointers all fail to hydrate
       yields zero items mid-walk. Verified on `usertag`: five empty pages, then 70
       pages of data. So we tolerate a run of empty pages and stop only when the run
       exceeds empty_page_limit -- a heuristic, hence reported as a cut-short reason
       rather than a clean end.
    """
    items: list[dict] = []
    next_key = None
    server_count: int | None = None
    pages = 0
    empty_pages = 0
    consecutive_empty = 0
    stop_reason: str | None = None

    while True:
        if max_pages is not None and pages >= max_pages:
            stop_reason = "max_pages"
            break

        body = {
            # Required by the parser, and discarded: the handler overwrites it from
            # the authenticated session (AuditService.hs). Omitting it 400s;
            # setting it to another user's ident changes nothing. Hence no flag.
            "auditquery_userIdent": "",
            "auditquery_auditView": audit_types,
            # Passed through verbatim. Terms rank rather than filter, and rewriting
            # them (injecting AND, quoting) would return results the caller did not
            # ask for and diverge from the OnPing UI sharing this endpoint.
            "auditquery_searchTerms": terms,
            "auditquery_queryRange": query_range,
            "auditquery_nextKey": next_key,
        }

        payload = request_page(session, token, body)
        pages += 1

        page_items = payload.get("auditresult_items")
        if not isinstance(page_items, list):
            die(
                "unexpected response shape: 'auditresult_items' missing or not a list "
                "-- the OnPing API contract may have changed"
            )

        metadata = payload.get("auditresult_metadata") or {}
        if isinstance(metadata.get("meta_count"), int):
            # Every page reports the same total; the first is authoritative.
            if server_count is None:
                server_count = metadata["meta_count"]

        items.extend(page_items)
        next_key = metadata.get("meta_nextKey")

        # The server's real end signal. Checked after extending, so the final page
        # carrying data is never dropped. A clean walk ends on one trailing empty page,
        # which is the normal shape rather than a mid-walk gap -- so it is not counted.
        if next_key is None:
            break

        if page_items:
            consecutive_empty = 0
        else:
            empty_pages += 1
            consecutive_empty += 1

        if consecutive_empty >= empty_page_limit:
            stop_reason = "empty_run"
            break

    return items, server_count, stop_reason, pages, empty_pages


def normalize(raw_item: dict) -> dict:
    """Flatten one AuditFrontEndView, preserving the payload verbatim."""
    raw_type = raw_item.get("auditview_type", "")
    return {
        "editedOn": raw_item.get("auditview_editedOn"),
        "editedBy": raw_item.get("auditview_editedBy"),
        "type": unquote_type(raw_type) if isinstance(raw_type, str) else raw_type,
        # Keep the server's double-encoded form so the strip is auditable, not silent.
        "type_raw": raw_type,
        "action": raw_item.get("auditview_action"),
        "description": raw_item.get("auditview_description"),
        # Shape varies across the 30 audit types; pass through untouched.
        "json": raw_item.get("auditview_json"),
    }


def render_csv(items: list[dict]) -> str:
    """Emit the six stable envelope columns.

    auditview_json is embedded as a JSON string rather than expanded: there is no
    stable schema across 30 audit types, so columns would be a guess. This keeps CSV
    lossless without pretending the payload is tabular.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in items:
        row = {key: item.get(key) for key in CSV_COLUMNS}
        row["json"] = json.dumps(item.get("json"), separators=(",", ":"), sort_keys=True)
        writer.writerow(row)
    return buf.getvalue()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull OnPing audit records (read-only).",
        epilog=(
            "Search terms RANK rather than filter -- adding a term can REMOVE records. "
            "Type and time range are the real filters. There is no flag for "
            "auditquery_userIdent because the server discards its value; to see one "
            "user's changes, post-filter the output on editedBy."
        ),
    )
    parser.add_argument("access_token", help="Bearer access token from onping-login")
    parser.add_argument(
        "--type",
        dest="types",
        action="append",
        metavar="NAME",
        help=(
            "Audit type wire name; repeatable. At least one is required. "
            "Note `alarm` already includes vpalarm records."
        ),
    )
    parser.add_argument("--since", metavar="ISO", help="Lower bound on edited-on (ISO 8601)")
    parser.add_argument("--until", metavar="ISO", help="Upper bound on edited-on (ISO 8601)")
    parser.add_argument(
        "--terms",
        default="",
        help="Relevance search terms, passed through verbatim (default: none)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        metavar="N",
        help=(
            "Stop after N pages of %d records (default: 50). Truncation is always "
            "reported." % SERVER_PAGE_SIZE
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Walk until exhausted, ignoring --max-pages (many round trips)",
    )
    parser.add_argument(
        "--empty-page-limit",
        type=int,
        default=DEFAULT_EMPTY_PAGE_LIMIT,
        metavar="N",
        help=(
            "Give up after N consecutive empty pages (default: %d). Empty pages occur "
            "mid-walk when audit pointers fail to hydrate; the longest run observed in "
            "testing was 7." % DEFAULT_EMPTY_PAGE_LIMIT
        ),
    )
    parser.add_argument("--csv", action="store_true", help="Emit CSV envelope columns")
    parser.add_argument("--pretty", action="store_true", help="Indent the JSON output")
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write to PATH instead of stdout, only on a successful walk",
    )
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="Print the accepted audit type wire names and exit",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_types:
        for wire, display in AUDIT_TYPES.items():
            print(f"{wire}\t{display}")
        for wire in sorted(EXTRA_ACCEPTED_TYPES):
            print(f"{wire}\t(accepted by the query route; folded into `alarm`)")
        return

    # An empty auditquery_auditView short-circuits server-side to an empty result
    # before any query runs (Client.hs), so refuse locally rather than let a
    # misleading 200 with zero records look like "no audits exist".
    if not args.types:
        die(
            "at least one --type is required; an empty type list returns an empty "
            "result server-side without querying anything. "
            "Run with --list-types to see the accepted names."
        )

    unknown = [t for t in args.types if t not in ACCEPTED_TYPES]
    if unknown:
        die(
            f"unknown audit type(s): {', '.join(sorted(set(unknown)))}. "
            "Run with --list-types to see the accepted names."
        )

    # De-duplicate, preserving first-seen order so the request is predictable.
    audit_types: list[str] = []
    for t in args.types:
        if t not in audit_types:
            audit_types.append(t)

    start = parse_timestamp(args.since, "--since") if args.since is not None else None
    end = parse_timestamp(args.until, "--until") if args.until is not None else None
    if start is not None and end is not None and start > end:
        die(f"--since ({args.since}) is later than --until ({args.until})")

    query_range = build_query_range(args.since, args.until)

    if args.max_pages < 1:
        die("--max-pages must be at least 1")
    if args.empty_page_limit < 1:
        die("--empty-page-limit must be at least 1")
    max_pages = None if args.all else args.max_pages

    session = requests.Session()
    items_raw, server_count, stop_reason, pages, empty_pages = walk(
        session,
        args.access_token,
        audit_types,
        args.terms,
        query_range,
        max_pages,
        args.empty_page_limit,
    )

    items = [normalize(item) for item in items_raw]
    saturated = server_count == COUNT_SATURATION
    truncated = stop_reason is not None
    # Fewer records than Elasticsearch counted, on a walk that ran to a clean end.
    # Caused by pointers that failed to hydrate, so it is a real shortfall rather than
    # a counting artifact -- and invisible unless reported.
    shortfall = (
        not truncated
        and not saturated
        and server_count is not None
        and len(items) < server_count
    )

    if args.csv:
        text = render_csv(items)
    else:
        result = {
            "retrieved": len(items),
            "server_reported_count": server_count,
            "count_saturated": saturated,
            "truncated": truncated,
            "stop_reason": stop_reason,
            "empty_pages": empty_pages,
            "shortfall": shortfall,
            "items": items,
        }
        text = json.dumps(result, indent=2 if args.pretty else None)

    if args.output:
        # Written only here, after a fully successful walk.
        Path(args.output).write_text(text if text.endswith("\n") else text + "\n")
        print(f"Wrote {len(items)} audit record(s) to {args.output}", file=sys.stderr)
    else:
        print(text)

    # Summary on stderr so it never contaminates piped output.
    if saturated:
        count_note = f"server reported >= {COUNT_SATURATION} matches (count ceiling)"
    elif server_count is None:
        count_note = "server reported no match count"
    else:
        count_note = f"server reported {server_count} match(es)"
    print(
        f"Retrieved {len(items)} record(s) over {pages} request(s); {count_note}.",
        file=sys.stderr,
    )

    if saturated:
        print(
            f"note: {COUNT_SATURATION} is Elasticsearch's count ceiling, not a total. "
            "Narrow --since/--until for an exact count.",
            file=sys.stderr,
        )

    # Truncation warnings are not suppressible: a partial pull that reads as complete
    # is the failure this whole skill is designed against.
    if stop_reason == "max_pages":
        print(
            f"warning: stopped at the --max-pages limit of {args.max_pages} "
            f"({args.max_pages * SERVER_PAGE_SIZE} records); MORE RECORDS MAY EXIST. "
            "Pass --all or narrow the time range.",
            file=sys.stderr,
        )
    elif stop_reason == "empty_run":
        print(
            f"warning: stopped after {args.empty_page_limit} consecutive empty pages, "
            "which is a heuristic, not the server's end-of-data signal "
            "(meta_nextKey was still set); MORE RECORDS MAY EXIST. "
            "Raise --empty-page-limit to keep going.",
            file=sys.stderr,
        )

    if empty_pages and stop_reason != "empty_run":
        print(
            f"note: {empty_pages} page(s) returned no records mid-walk; this is normal "
            "-- audit pointers that fail to hydrate yield an empty page while more data "
            "still follows.",
            file=sys.stderr,
        )

    if shortfall:
        print(
            f"note: retrieved {len(items)} of the {server_count} match(es) the search "
            "index counted. The shortfall is audit pointers that did not resolve to "
            "records -- typically permission-scoped or dangling. The walk did reach the "
            "end of the result set.",
            file=sys.stderr,
        )

    if not items:
        print(
            "note: no records matched. Results cover only audits visible to the "
            "authenticated caller's permission groups, so this means 'none visible', "
            "not necessarily 'none exist'.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
