"""Curated route definitions for OnPing HMI import/export/list/delete endpoints.

This module is the single source of truth for the on-disk HMI skill tree. Each
entry in `ROUTES` describes one `/hmi/*` route used by an `onping-hmi-*` skill:

  - `endpoint`             — HTTP method + path with `{uuid}` placeholder
  - `handler`              — `file:line` of the handler in onping (traceability)
  - `path_params`          — placeholder name -> human description (or {} if none)
  - `request_content_type` — Content-Type the handler consumes (POST/PUT only)
  - `response`             — the response body shape / Content-Type
  - `permission`           — the OnPing permission the handler enforces
  - `notes`                — anything non-obvious about the route

Schemas are HAND-CURATED from reading the Haskell handlers in
`onping/Handler/Hmi/HmiViewer.hs`. When routes change,
re-verify against the recorded `handler` location and update the matching entry.
All `onping-hmi-*` scripts read from this dict; nothing else should redefine
routes inline.

TWO GOTCHAS drive the skill design:

1. **There is no `/hmi/copy` route.** OnPing exposes copy only internally (in the
   dashboard-copy flow), never as a public route. To clone an HMI you must
   `parse` the Dhall to JSON, rewrite `dashId` to a fresh UUID, and `upsert` —
   this is exactly what `onping-hmi-import --new` does.

2. **`/hmi/upsert` consumes a RAW `HmiDashboard` JSON** (not the
   `HmiUpsertRequest {username, dashboard}` wrapper). The handler does
   `requireInsecureJsonBody :: HmiDashboard` and wraps it with the caller's
   username server-side. Same `dashId` overwrites; a different `dashId` creates.

DHALL-vs-JSON KEY NAMING (verified live 2026-07-02): the exported/imported Dhall
uses record fields prefixed with an underscore (`_dashId`, `_dashName`, …), but
the JSON returned by `/hmi/parse` and `/hmi/{uuid}` and consumed by
`/hmi/upsert` uses UNPREFIXED keys (`dashId`, `dashName`, `dashComponents`,
`dashSettings`, `dashAlertConfig`, `dashLastUpdate`, `dashDeleted`). The import
skill reads and rewrites the JSON `dashId`, never the Dhall `_dashId`.

DELETE is a SOFT delete: `DELETE /hmi/delete/{uuid}` sets `dashDeleted = true`;
`GET /hmi/{uuid}` still returns the (flagged) record afterward.

AUTH: `Authorization: Bearer <token>` from `onping-login` works on every `/hmi/*`
route. The `!` route prefix in onping's `config/routes` only skips the default
group-membership authorization check — it does not disable authentication.
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 60

ROUTES: dict[str, dict] = {
    "list": {
        "endpoint": "GET /hmi/list",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {},
        "response": "JSON [HmiInfo] — {hmiInfoName, hmiInfoUuid, hmiInfoDashboardName (nullable), hmiInfoPanelName}",
        "permission": "authenticated user (returns the HMIs embedded in dashboard panels the user can see)",
        "notes": "Scoped to HMIs placed on dashboard panels. A freshly-upserted HMI that is not on a panel does NOT appear here.",
    },
    "export": {
        "endpoint": "GET /hmi/export/{uuid}",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {"uuid": "HMI dashboard UUID to export"},
        "response": "Dhall HmiDashboard; Content-Type text/x-dhall;charset=utf-8; Content-Disposition filename=\"hmi.dhall\"",
        "permission": "Write on the HMI UUID",
        "notes": "Full dashboard: _dashId, _dashName, _dashComponents, _dashSettings, _dashAlertConfig, _dashLastUpdate, _dashDeleted.",
    },
    "export-data": {
        "endpoint": "GET /hmi/export-data/{uuid}",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {"uuid": "HMI dashboard UUID whose data bindings to export"},
        "response": "Dhall [DataImport]; Content-Type text/x-dhall;charset=utf-8; Content-Disposition filename=\"hmi-data.dhall\"",
        "permission": "Write on the HMI UUID",
        "notes": "Data-binding mappings only ({from: {onpingKey, description}, to: Maybe onpingKey}), not the layout.",
    },
    "parse": {
        "endpoint": "POST /hmi/parse/{uuid}",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {"uuid": "IGNORED except for auth — pass the nil UUID 00000000-0000-0000-0000-000000000000"},
        "request_content_type": "text/plain;charset=UTF-8 (Dhall HmiDashboard body)",
        "response": "JSON HmiDashboard (unprefixed keys: dashId, dashName, …)",
        "permission": "authenticated user only (no per-HMI permission check)",
        "notes": "Read-only. Type-checks the Dhall server-side and returns canonical JSON. The Dhall->JSON bridge for import; the uuid in the path is not used by the handler body.",
    },
    "upsert": {
        "endpoint": "POST /hmi/upsert",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {},
        "request_content_type": "application/json (RAW HmiDashboard, not the HmiUpsertRequest wrapper)",
        "response": "JSON HmiDashboard (the created/updated dashboard)",
        "permission": "Write on the dashboard's dashId",
        "notes": "Same dashId overwrites in place; a different dashId creates a new HMI. Server wraps the body into HmiUpsertRequest{username,dashboard}.",
    },
    "import-data": {
        "endpoint": "POST /hmi/import-data/{uuid}",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {"uuid": "target HMI dashboard UUID whose data bindings to replace"},
        "request_content_type": "text/plain;charset=UTF-8 (Dhall [DataImport] body)",
        "response": "JSON HmiDashboard (with the data bindings applied)",
        "permission": "Write on the target HMI UUID",
        "notes": "Applies data-binding mappings to an existing HMI; does not change layout.",
    },
    "delete": {
        "endpoint": "DELETE /hmi/delete/{uuid}",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {"uuid": "HMI dashboard UUID to delete"},
        "response": "JSON (200 with []) on success",
        "permission": "Delete on the HMI UUID",
        "notes": "SOFT delete — sets dashDeleted=true; GET /hmi/{uuid} still returns the flagged record afterward.",
    },
    # ── reference-only routes (not wrapped by a v1 skill) ──
    "get": {
        "endpoint": "GET /hmi/{uuid}",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {"uuid": "HMI dashboard UUID to retrieve"},
        "response": "JSON HmiDashboard (unprefixed keys)",
        "permission": "authenticated user",
        "notes": "Reference: used by delete's --dry-run existence probe. Same JSON shape as parse output.",
    },
    "permissions": {
        "endpoint": "GET /hmi/permissions/{uuid}",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "path_params": {"uuid": "HMI dashboard UUID to check"},
        "response": "JSON bool (true if the user has Write on the HMI)",
        "permission": "authenticated user",
        "notes": "Reference only.",
    },
}
