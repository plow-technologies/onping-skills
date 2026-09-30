"""Curated route definitions for OnPing line-graph widget endpoints.

This module is the single source of truth for the `onping-line-graph-*` skill
tree. Each entry in `ROUTES` describes one `/content/widgets/line-graph/*` route:

  - `endpoint`             — HTTP method + path with `{widget_id}` placeholder
  - `handler`              — `file:line` of the handler in onping (traceability)
  - `path_params`          — placeholder name -> human description (or {} if none)
  - `request_content_type` — Content-Type the handler consumes (POST only)
  - `response`             — the response body shape / Content-Type
  - `permission`           — the OnPing permission the handler enforces
  - `notes`                — anything non-obvious about the route

Schemas are HAND-CURATED from reading the Haskell handlers in
`onping/Handler/Highcharts/{LineGraphWidget,ImportExport}.hs`
and were live-verified against onping.plowtech.net on 2026-07-13. When routes
change, re-verify against the recorded `handler` location and update.
All `onping-line-graph-*` scripts read from this dict; nothing else should
redefine routes inline.

TWO SCHEMA GOTCHAS drive skill design:

1. **Full-vs-data-only Dhall shapes are not interchangeable.**
   `/import/#id` consumes a Dhall `ExportedLineGraphWidget` record
   (`{title, timePeriod, timeUnit, updateInterval, yAxes, eventParameters,
   maxStep, normalizeValue, latestValueLine, legendWithCurrentValue}`).
   `/import-data-only/#id` consumes a Dhall `[Field]` list of
   `{from : {onpingKey, description}, to : Optional {type, value}}` pid
   remappings. Feeding a record to `/import-data-only` (or vice versa) yields
   HTTP 400 with `{"error": "Invalid Dhall.Decoder … ↳ <expected-type>"}`.
   Local skills peek the first non-whitespace character (`{` → record; `[` →
   list) and refuse to route to the wrong endpoint.

2. **`/import/#id` server-side permission-checks every pid/vpid.**
   The handler (`LineGraphWidget.hs`) collects every pid from
   `yAxes[].parameters[].pid` and `eventParameters[].pid`, calls
   `LocationLister.checkOnpingKeysPermission`, and returns HTTP 400 with
   `"Permission error for [<keys>]"` if the caller lacks Read on ANY of them.
   The widget is NOT modified when this fires. `--dry-run` on the import skill
   surfaces the pid list locally so callers can pre-empt.

   **Fail-open on unknown pids** (verified 2026-07-14 by probing `+999999999`
   and small integers `+1..+1000` — all accepted). The check works by mapping
   each pid to its location and denying only pids whose location the caller
   can't read. Pids that don't map to a location at all (e.g. never-existed
   ids, or pids that were deleted) drop out of the check and are silently
   stored on the widget. The permission-error path only fires for pids that
   BOTH (a) exist on a real location AND (b) that location denies the caller.

RESPONSE SHAPE gotcha (verified live 2026-07-13):
`OnpingResponse LineGraphWidget` on the Haskell side is serialized as the
**raw widget JSON** on success (no `{status: "success", data: …}` wrapper).
Error path is a JSON object `{"error": "<message>"}` with HTTP 400. The
wire-level `pid` is a bare integer; the Dhall `{type: "PID", value: +N}`
record is flattened server-side on serialization.

ID FAMILY: line-graph widget IDs are Mongo-style `o…` ids (e.g.
`o00000000000000000000002d`), assigned server-side by `POST /config`. They
cannot be minted client-side, which is why `-import --new` runs a two-step:
`POST /config` mints a fresh id, then `POST /import/#new-id` writes into it.

NO-DELETE-ROUTE constraint: `/content/widgets/line-graph/*` has 7 routes; DELETE
is not one of them. A widget can only be removed as a side-effect of deleting
its parent dashboard (`Handler/Delete/DeleteDashboard.hs`). A wrong `--new`
or half-successful import leaves an orphaned widget behind; cleanup requires
touching the parent dashboard.

AUTH: `Authorization: Bearer <token>` from `onping-login` works on every
`/content/widgets/line-graph/*` route (verified live 2026-07-13).
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 60

ROUTES: dict[str, dict] = {
    "config": {
        "endpoint": "POST /content/widgets/line-graph/config",
        "handler": "onping/Handler/Highcharts/LineGraphWidget.hs",
        "path_params": {},
        "request_content_type": "empty body (no request Content-Type required; server ignores body)",
        "response": "JSON quoted string — the new `LineGraphWidgetId` (Mongo `o…` id)",
        "permission": "authenticated user (any user can mint; the resulting widget is orphaned)",
        "notes": (
            "Mints a fresh widget with server defaults (LineGraphWidget.hs): "
            "title 'New Chart', timePeriod 3 Hour, updateInterval 60, one default "
            "YAxis, no parameters, maxStep 0, normalizeValue False, "
            "latestValueLine Just False, legendWithCurrentValue False. The fresh "
            "widget is NOT attached to a dashboard — attach via HMI panel config, "
            "or use `-import --new` for the two-step create+populate."
        ),
    },
    "get": {
        "endpoint": "GET /content/widgets/line-graph/widget/{widget_id}",
        "handler": "onping/Handler/Highcharts/LineGraphWidget.hs",
        "path_params": {"widget_id": "LineGraphWidgetId (Mongo `o…` id)"},
        "response": (
            "JSON LineGraphWidget — {title, timePeriod, timeUnit, updateInterval, "
            "yAxes, eventParameters, maxStep, normalizeValue, latestValueLine, "
            "legendWithCurrentValue, dashboardId?}. `dashboardId` is absent for "
            "orphaned widgets (not yet attached to a dashboard)."
        ),
        "permission": "authenticated user (no per-widget permission check on GET)",
        "notes": "Wire-level `pid` is a bare integer; Dhall record `{type, value}` is flattened.",
    },
    "post": {
        "endpoint": "POST /content/widgets/line-graph/widget/{widget_id}",
        "handler": "onping/Handler/Highcharts/LineGraphWidget.hs",
        "path_params": {"widget_id": "LineGraphWidgetId"},
        "request_content_type": "application/json (raw LineGraphWidget)",
        "response": "JSON LineGraphWidget (echo of the repserted body)",
        "permission": "authenticated user (permission checks live in the referenced-pid path via `-import`)",
        "notes": "Reference only — not wrapped by a skill. `-import` is the write path.",
    },
    "export": {
        "endpoint": "GET /content/widgets/line-graph/export/{widget_id}",
        "handler": "onping/Handler/Highcharts/LineGraphWidget.hs",
        "path_params": {"widget_id": "LineGraphWidgetId to export"},
        "response": (
            "Dhall ExportedLineGraphWidget; Content-Type "
            "text/x-dhall;charset=utf-8; Content-Disposition attachment"
        ),
        "permission": "authenticated user",
        "notes": (
            "Full widget: title/timePeriod/timeUnit/updateInterval/yAxes/"
            "eventParameters/maxStep/normalizeValue/latestValueLine/"
            "legendWithCurrentValue. The Dhall body is a valid input for "
            "/import/#id — the round trip is lossless."
        ),
    },
    "export-data": {
        "endpoint": "GET /content/widgets/line-graph/export-data-only/{widget_id}",
        "handler": "onping/Handler/Highcharts/ImportExport.hs",
        "path_params": {"widget_id": "LineGraphWidgetId whose pid bindings to export"},
        "response": (
            "Dhall [Field]; Content-Type application/vnd.plow.haskell-type+dhall. "
            "Empty widget yields `[] : List Field`."
        ),
        "permission": "authenticated user",
        "notes": (
            "Bare Dhall list, no wrapper. Each entry is "
            "{from: {onpingKey: {type, value}, description}, to: Optional {type, value}}. "
            "Distinct shape from /export — feeding to /import fails with a 400 "
            "Dhall type error."
        ),
    },
    "import": {
        "endpoint": "POST /content/widgets/line-graph/import/{widget_id}",
        "handler": "onping/Handler/Highcharts/LineGraphWidget.hs",
        "path_params": {"widget_id": "LineGraphWidgetId to overwrite (must exist)"},
        "request_content_type": "text/plain;charset=UTF-8 (Dhall ExportedLineGraphWidget body)",
        "response": (
            "Raw JSON LineGraphWidget on 200. No {status, data, …} envelope. "
            "Error path is HTTP 400 with {\"error\": \"<message>\"}."
        ),
        "permission": (
            "Read on every pid/vpid referenced in yAxes/eventParameters "
            "(LineGraphWidget.hs); widget-level Write is via the parent "
            "dashboard. 400 'Permission error for [<keys>]' if any pid is denied."
        ),
        "notes": (
            "The widget id must already exist (404 'LineGraph Not Found' if not). "
            "Use POST /config first to mint, then POST /import into the new id "
            "for a --new-style clone."
        ),
    },
    "import-data": {
        "endpoint": "POST /content/widgets/line-graph/import-data-only/{widget_id}",
        "handler": "onping/Handler/Highcharts/ImportExport.hs",
        "path_params": {"widget_id": "LineGraphWidgetId to remap pids on"},
        "request_content_type": "text/plain;charset=UTF-8 (Dhall [Field] body)",
        "response": (
            "Raw JSON LineGraphWidget on 200 (same shape as /import response)."
        ),
        "permission": "authenticated user; unknown-id → 404.",
        "notes": (
            "Rewrites yParam_pid / eventParam_pid where `from` matches; every other "
            "field is untouched. Unreachable `from` keys are no-ops server-side, "
            "not errors."
        ),
    },
    "permission": {
        "endpoint": "GET /content/widgets/line-graph/permission/{widget_id}",
        "handler": "onping/Handler/Highcharts/LineGraphWidget.hs",
        "path_params": {"widget_id": "LineGraphWidgetId to check"},
        "response": "JSON bool (true if the user has Write on the widget via its parent dashboard)",
        "permission": "authenticated user",
        "notes": "Reference only — not wrapped by a skill.",
    },
}
