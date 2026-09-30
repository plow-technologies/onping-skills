"""Curated route definitions for the OnPing custom-table widget endpoints.

Single source of truth for the `onping-ctable-*` skill tree. Each entry in
`ROUTES` describes one `/content/ctable/*` route:

  - `endpoint`   — HTTP method + path
  - `handler`    — `file:line` of the handler in the monorepo (traceability)
  - `query`      — query parameter name -> description
  - `response`   — the response body shape
  - `notes`      — anything non-obvious about the route

Schemas are HAND-CURATED from reading the Haskell handlers in
`onping/Handler/Tables/CustomTable/Table.hs`. When routes change, re-verify
against the recorded `handler` location and update the matching entry.

FOUR GOTCHAS drive the skill design, each verified against a live server:

1. **`cTableId` is a QUERY parameter, never a path segment.** The export route
   takes a filename in its path, not the table id. Putting the id in the path
   returns `400 "No table id found"`.

2. **A refusal arrives as HTTP 200.** `postCustomTableJsonR` returns the bare
   JSON string `"insufficient permissions"` with a success status
   (`Table.hs`). Only an echoed `{"ctable":…,"cid":…}` object is a real
   success, so callers MUST inspect the body and not the status alone.

3. **The write is a whole-document repsert, not a patch.** The chain is
   `repsertCustomTableWidget` -> `repsertAndAudit` -> `DB.repsert` ->
   `DB.save collection (keyDoc ++ valueDoc)`. The `_id` comes from the caller,
   so the write replaces every field and every cell at that exact ObjectId.
   There is no merge step.

4. **The body cap is 8 MiB for the JSON route alone** (`Foundation.hs`).
   Every other OnPing route carries a different figure, so the cap must be
   checked locally rather than assumed from another skill.

Permission is NOT read from the widget. `checkCustomTableUserPermissions`
(`Permissions.hs`) reads `customTableWidgetDashboard`, fetches that
dashboard, and tests `editDashboardPermission`. A widget naming no dashboard
yields `False False` and is unwritable through the API — which is why
`onping-ctable-import` refuses a null dashboard field.
"""

from __future__ import annotations

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 300

# POST /content/ctable/json body cap, from Foundation.hs. This route only.
MAX_BODY_BYTES = 8 * 1024 * 1024

# Warn at this fraction of the cap on export, so a caller learns that a later
# re-import can be rejected for size before they depend on it.
CAP_WARN_FRACTION = 0.75

# The eight CustomTableWidget JSON keys (CustomTableWidget.hs).
WIDGET_KEYS = (
    "customTableWidgetTitle",
    "customTableWidgetHeaders",
    "customTableWidgetCells",
    "customTableWidgetType",
    "customTableWidgetZoomLevel",
    "customTableWidgetDashboard",
    "customTableSortingInformation",
    "customTablePreferredSortingInformation",
)

# Parsed with `.:` rather than `.:?`, so the key must be present.
REQUIRED_WIDGET_KEYS = (
    "customTableWidgetTitle",
    "customTableWidgetHeaders",
    "customTableWidgetCells",
    "customTableWidgetType",
)

ROUTES = {
    "get_json": {
        "endpoint": "GET /content/ctable/json",
        "handler": "Handler/Tables/CustomTable/Table.hs",
        "query": {"cTableId": "the widget's o-prefixed mongo id"},
        "response": "the full CustomTableWidget as JSON, or the literal null",
        "notes": (
            "Read-only. Returns `null` (not a 404) when no widget exists at the "
            "id, so a caller must test the body."
        ),
    },
    "post_json": {
        "endpoint": "POST /content/ctable/json",
        "handler": "Handler/Tables/CustomTable/Table.hs",
        "query": {},
        "request_body": '{"ctable": <CustomTableWidget>, "cid": {"cTableId": "<id>"}}',
        "response": "the same envelope echoed back, OR the bare string on refusal",
        "notes": (
            "MUTATING. Full-document repsert preserving the caller's ObjectId. "
            'Refusal is `"insufficient permissions"` at HTTP 200. Body cap 8 MiB.'
        ),
    },
    "exists": {
        "endpoint": "GET /does/content/ctable/json/exist",
        "handler": "Handler/Tables/CustomTable/Table.hs",
        "query": {"cTableId": "the widget's o-prefixed mongo id"},
        "response": "the JSON boolean true or false",
        "notes": "Cheaper than get_json when only existence matters.",
    },
    "export_xlsx": {
        "endpoint": "GET /content/ctable/export/{filename}",
        "handler": "Handler/Tables/CustomTable/Table.hs",
        "query": {"cTableId": "the widget's o-prefixed mongo id"},
        "response": "XLSX bytes",
        "notes": (
            "The path segment is the DOWNLOAD FILENAME, not the table id. Lossy: "
            "carries only PID/text per cell, dropping title, zoom and sorting. "
            "Not a faithful restore source — use get_json for that."
        ),
    },
    "table_data": {
        "endpoint": "GET /api/customtabledata/get",
        "handler": "onping/config/routes",
        "query": {"cTableId": "the widget's o-prefixed mongo id"},
        "response": '{"parameters": [ ... ]} with resolved live values',
        "notes": (
            "Read-only. Used by onping-ctable-import --verify-live to confirm "
            "restored PIDs resolve to current values, not merely that they exist."
        ),
    },
}


def normalize_ctable_id(raw: str) -> str:
    """Return the o-prefixed form of a custom-table id.

    OnPing HTTP routes want `o` + 24 hex characters. The postgres audit tables
    store the same id without the `o` (see `_audit_db.ids`). Accepting both here
    means a caller can paste either form.
    """
    s = raw.strip()
    body = s[1:] if s.startswith("o") else s
    if len(body) != 24 or any(c not in "0123456789abcdefABCDEF" for c in body):
        raise ValueError(
            f"not a mongo object id: {raw!r} "
            "(expected 24 hex characters, optionally o-prefixed)"
        )
    return "o" + body.lower()
