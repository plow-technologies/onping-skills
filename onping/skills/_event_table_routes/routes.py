"""Curated route definitions for the OnPing event-table read skills.

This module is the single source of truth for the `onping-event-table-*` skill
tree. Each entry in `ROUTES` describes one route:

  - `endpoint`             — HTTP method + path, with `{name}` placeholders
  - `handler`              — `file:line` of the handler in onping (traceability)
  - `path_params`          — placeholder name -> human description (or {} if none)
  - `query_params`         — query parameter name -> human description
  - `request_content_type` — what the handler consumes (POST only)
  - `response`             — the response body shape / Content-Type
  - `permission`           — the permission the handler enforces
  - `notes`                — anything non-obvious about the route

Schemas are HAND-CURATED from reading the Haskell handlers. The `/event/table/*`
routes are declared at `onping/config/routes` and proxy onto the
separate event-table-server through Haxl (`onping/Handler/EventTable/Service.hs`).
When routes change, re-verify against the recorded `handler` location and update.

ARCHITECTURE GOTCHA: an event table is NOT stored with its dashboard. A dashboard
panel holds only a pointer, `plist = {"EventTableConfig": {"eventTableUUID":
"<uuid>"}}`, on a content object whose `title` is the widget's display name. The
`EventTableConfiguration` itself carries no title. So the only way from a title
("Recent Events") to a UUID is the dashboard JSON.

KEY ENCODING (the `OnpingKey` instances in onping-tag-types):
in JSON, a PID key is a bare integer (`500001`) and a VPID key is an object
(`{"keyType": "VPID", "keyValue": N}`). In Dhall both are `{ type, value }`
records. Unlike the line-graph JSON, the event-table JSON keeps the PID/VPID
distinction, so the config read alone is enough for a PID audit.

PERMISSION: every `/event/table/*` route falls through to the default
`isAuthorized _ _ = isInGroupList ["User"]` (`isAuthorized` in `onping/Foundation.hs`). No
handler performs a per-table, per-dashboard, or per-PID check.

ERROR SHAPES differ by route: the config read answers 404 `{"error": …}`, the
export answers 500 with a bare JSON string, and the rows fetch answers 500
`{"error": …}`. `event_table_http.error_text` unwraps both shapes.

VERIFIED LIVE against onping.plowtech.net on 2026-10-02, read-only:
  - the `onping-login` bearer token works on every route below;
  - `GET /data/dashboard?dashId=o<24 hex>` accepts the key from a dashboard URL;
  - an unknown UUID gives 404 "Failed to lookup EventTableConfiguration by UUID"
    on the config read, and 500 with the same text on the export;
  - a column bound to a deleted PID makes the fetch answer 500
    "failed to lookup TagInfo for key: KeyPID 500001", naming only the FIRST
    dead key (the same table also bound a second deleted PID, 500002);
  - production reward tables put the trigger at eventColumnIndex 0, with
    columns 0 and 1 reading the same PID.
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 60

ROUTES: dict[str, dict] = {
    "config": {
        "endpoint": "POST /event/table/config",
        "handler": "onping/Handler/EventTable/Service.hs (postQueryEventTableConfigR)",
        "path_params": {},
        "query_params": {},
        "request_content_type": 'application/json — {"unEventTableUUID": "<uuid>"}',
        "response": (
            "JSON EventTableConfiguration (raw, no envelope): {eventTableUUID, "
            "eventTableDashboardId, eventTableDeleted, eventTableSortOrder, "
            "eventTableMaxEvents, eventTableEventColumn, eventTableParams}"
        ),
        "permission": "authenticated User-group member (no per-table check)",
        "notes": (
            "POST but read-only. The body is {\"unEventTableUUID\": …}, NOT a bare "
            "string and NOT {\"eventTableUUID\": …} (that is the dashboard-pointer "
            "shape). Unknown UUID -> 404 {\"error\": \"Failed to lookup "
            "EventTableConfiguration by UUID\"}. Soft-deleted tables are returned "
            "with eventTableDeleted: true. A deleted PID is returned unchanged — "
            "the config read never validates keys."
        ),
    },
    "export": {
        "endpoint": "GET /event/table/export/{filename}",
        "handler": "onping/Handler/EventTable/Service.hs (getEventTableExportR)",
        "path_params": {"filename": "download file name only — the server ignores it"},
        "query_params": {"eventTableUUID": "the event-table UUID (required)"},
        "response": (
            "Dhall EventTableConfiguration, Content-Type "
            "application/vnd.plow.event-table+dhall"
        ),
        "permission": "authenticated User-group member (no per-table check)",
        "notes": (
            "The path segment only names the downloaded file "
            "(`_requiredToNameFileInFrontend` in getEventTableExportR). The UUID travels in "
            "the `eventTableUUID` query parameter. A missing "
            "parameter or an unknown UUID -> HTTP 500 with a bare JSON string body. "
            "The output is valid input to POST /event/table/import."
        ),
    },
    "fetch": {
        "endpoint": "POST /event/table/fetch",
        "handler": "onping/Handler/EventTable/Service.hs (postFetchEventTableR)",
        "path_params": {},
        "query_params": {},
        "request_content_type": (
            'application/json — {"fetchEventTableUUID": {"unEventTableUUID": '
            '"<uuid>"}, "fetchTime": "<ISO-8601 UTC>"}'
        ),
        "response": (
            "JSON FetchedEventTable — [{eventTableRowIndex, eventTableRowCells: "
            "[{eventCellRow, eventCellCol, eventCellConfig, eventCellResult, "
            "eventCellCompany, eventCellSite, eventCellLocation}]}]"
        ),
        "permission": "authenticated User-group member (no per-table check)",
        "notes": (
            "Read-only. Rows are the last maxEvents history points of the trigger "
            "PID before fetchTime. Any column key with no TagInfo fails the WHOLE "
            "fetch: HTTP 500 {\"error\": \"failed to lookup TagInfo for key: …\"} "
            "(`makeCell` in the onping-core event-table data source). That "
            "error names the dead key."
        ),
    },
    "dashboard": {
        "endpoint": "GET /data/dashboard",
        "handler": "onping/Handler/JSON/Dashboard.hs (getJsonDashboardR)",
        "path_params": {},
        "query_params": {"dashId": "dashboard key, `o` + 24 hex (from a /v3/dashboards/<key> URL)"},
        "response": "JSON Dashboard value (no key): {name, panels, …}",
        "permission": "authenticated user; dashboard visibility through Haxl",
        "notes": (
            "TRAP: when dashId is missing or does not parse, the handler silently "
            "returns the caller's DEFAULT dashboard with HTTP 200 (getJsonDashboardR), "
            "and the response carries no key to tell the two apart. Callers must "
            "first confirm the key appears in GET /data/dashboard/values. Panels "
            "nest: panels[] -> carr.arr[] content objects, and panels[] -> "
            "sub.panels[] (recurse)."
        ),
    },
    "dashboard_values": {
        "endpoint": "GET /data/dashboard/values",
        "handler": "onping/Handler/JSON/Dashboard.hs (getJsonDashboardValuesR)",
        "path_params": {},
        "query_params": {},
        "response": "JSON [{key, value: <dashboard name>}] for the caller's owned and member groups",
        "permission": "authenticated user; owned and member groups only",
        "notes": "Small. Used to validate a dashboard key before GET /data/dashboard.",
    },
    "dashboard_list": {
        "endpoint": "GET /data/dashboard/list",
        "handler": "onping/Handler/JSON/Dashboard.hs (getJsonDashboardListR)",
        "path_params": {},
        "query_params": {},
        "response": "JSON [{key, value: Dashboard}] for the caller's owned and member groups",
        "permission": "authenticated user; owned and member groups only",
        "notes": "Large and unpaginated — every dashboard the caller can see, in full.",
    },
}
