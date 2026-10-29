"""Curated route definitions for the OnPing Lumberjack data-table and log-table skills.

This module is the single source of truth for the `onping-datatable-*` and
`onping-logtable-*` primitive skills. Each entry in `ROUTES` describes one route:

  - `endpoint`             — HTTP method + path, with `{name}` placeholders
  - `handler`              — the Yesod handler in onping (traceability)
  - `request`              — the JSON body the handler consumes (POST only)
  - `response`             — the success body shape
  - `permission`           — the group check the handler enforces
  - `notes`                — anything non-obvious about the route

Schemas are HAND-CURATED from reading the Haskell handlers in
`onping/Handler/OnpingDataTable/Service.hs` and
`onping/Handler/OnpingLogTable/Service.hs`, which proxy through Haxl onto the
per-Lumberjack datatable and logtable apps. When routes change, re-verify
against the recorded `handler` and update.

A DATA TABLE here is the Lumberjack `/datatable/...` feature, NOT a custom
table (`/ctable/...`). A data-table column holds only a selector; each row's
cells hold the PID as text ("1234" or "4321 VPID"). A log-table column carries
its PID as a key, and every column edit is a new schema version.

ROUTING is by Lumberjack serial. There is no get-one route for either kind:
find one source by filtering `source/list` (or `router/source/all`).

ERRORS: every app error arrives as `{"error": "<text>"}`. Permission denied is
HTTP 500 `{"error": "Permission Denied"}` (`sendErrorResponseString`). A
Lumberjack with no routing for the kind answers 404 `{"error": "Routing index
could not be found.\\n"}`. A data-table write during a regeneration answers 503
(`RegenerationInProgress`).

VERIFIED LIVE against onping.plowtech.net on 2026-10-09, read-only: both
`router/source/all` routes, both `source/list` routes, datatable
`content/query/v3`, and logtable `content/query/v2`.
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 60

_DT = "onping/Handler/OnpingDataTable/Service.hs"
_LT = "onping/Handler/OnpingLogTable/Service.hs"

ROUTES: dict[str, dict] = {
    # ---------------------------------------------------------------- datatable
    "datatable_all": {
        "endpoint": "GET /datatable/router/source/all",
        "handler": f"{_DT} (getAllDataTableSourcesR)",
        "response": "JSON [TableSource] across every routed Lumberjack",
        "permission": "sources whose tableGroupId is in the caller's owned-or-member groups",
        "notes": "Filtered server-side by group; a source you cannot see is simply absent.",
        "timeout": 300,
    },
    "datatable_list": {
        "endpoint": "GET /datatable/{lj}/source/list",
        "handler": f"{_DT} (getDataTableSourceListR)",
        "response": "JSON [TableSource] on one Lumberjack",
        "permission": "owned-or-member groups",
        "notes": (
            "No routing for the LJ -> 404 {\"error\": \"Routing index could not be found.\\n\"}."
        ),
    },
    "datatable_query": {
        "endpoint": "POST /datatable/{lj}/source/content/query/v3",
        "handler": f"{_DT} (postDataTableSourceContentQueryAndCountAndPointersR)",
        "request": "the TableSource; its header filters, order, and tablePagination are applied",
        "response": (
            "{queryResponseContent: [TableRow], queryResponsePointers: [TableRow], "
            "queryResponseCount: int}; TableRow = {tableRowId, tableRowValues}"
        ),
        "permission": "owned-or-member groups",
        "notes": (
            "POST but read-only. tablePagination null returns every row. Content holds "
            "rendered values; pointers hold the stored cell text (\"1234\", \"4321 VPID\", "
            "or literal text). Pointers come from `WHERE rowId IN (...)` with no ORDER BY, "
            "so join content and pointers on tableRowId, never by index. Both exclude "
            "InvalidTagSelector columns and include hidden columns, in position order. The "
            "stored filters apply: clear tableHeaderFilters to see every row."
        ),
    },
    "datatable_content_update": {
        "endpoint": "POST /datatable/{lj}/source/content/update",
        "handler": f"{_DT} (postDataTableSourceContentUpdateR)",
        "request": '["<table uuid>", [{"tableRowId": n, "tableRowValues": [text|null, ...]}]]',
        "response": "[]",
        "permission": "owned groups",
        "notes": (
            "Each row's FULL value list, in position order; its length must equal the "
            "stored row (RowUpdateColumnsNumberMismatch). A non-text cell must parse as "
            "\"1234\" or \"4321 VPID\" (InvalidRowContent); text cells are free text; null "
            "clears. The app zips the rows it reads back (unordered IN query) with the "
            "rows sent, to keep PID-occurrence counts, so send rows sorted by tableRowId. "
            "Every update regenerates the table: 503 while a regeneration holds the lock."
        ),
    },
    "datatable_metadata_update": {
        "endpoint": "POST /datatable/{lj}/source/metadata/update",
        "handler": f"{_DT} (postDataTableSourceMetadataUpdateR)",
        "request": "the full TableSource",
        "response": "[]",
        "permission": "owned groups",
        "notes": (
            "Diffs old and new tableHeaderColumns. columnHeaderNewOrDuplicate = nil UUID "
            "-> ALTER ADD COLUMN (stored with NewOrDuplicate reset to null); another UUID "
            "-> duplicate that column; null with a known id -> plain update; null with an "
            "unknown id -> silently ignored. A stored column absent from the body -> DROP "
            "COLUMN, and its data is gone. Text <-> non-text selector changes are rejected."
        ),
    },
    # ----------------------------------------------------------------- logtable
    "logtable_all": {
        "endpoint": "GET /logtable/router/source/all",
        "handler": f"{_LT} (getAllLogTableSourcesR)",
        "response": "JSON [LogTableSource] across every routed Lumberjack",
        "permission": "owned-or-member groups",
        "notes": (
            "Only sources with logTableSourceSchemaVersion > 0. A freshly created "
            "version-0 source is invisible here; use the per-LJ list. Slow: about "
            "60 s and 30+ MB on 2026-10-09 (every schema version of every source)."
        ),
        "timeout": 300,
    },
    "logtable_list": {
        "endpoint": "GET /logtable/{lj}/source/list",
        "handler": f"{_LT} (getLogTableSourceListR)",
        "response": "JSON [LogTableSource] on one Lumberjack, any version, not deleted",
        "permission": "owned-or-member groups",
        "notes": "Schemas are listed newest first; always select a schema by logSchemaVersion.",
    },
    "logtable_create": {
        "endpoint": "POST /logtable/{lj}/source/create",
        "handler": f"{_LT} (postLogTableSourceCreateR)",
        "request": (
            "LogTableSource with logTableSourceId = nil UUID, "
            "logTableSourceSchemaVersion = 0, logTableSourceSchemas = []"
        ),
        "response": "JSON string — the new source UUID",
        "permission": "the Lumberjack's group must be in the caller's owned groups",
        "notes": (
            "Non-empty schemas -> InvalidLogTableSourceCreation. The new source has no "
            "schema and records nothing until a version-1 schema/upgrade."
        ),
    },
    "logtable_upgrade": {
        "endpoint": "POST /logtable/{lj}/source/schema/upgrade",
        "handler": f"{_LT} (postLogTableSourceSchemaUpgradeR)",
        "request": "the LogTableSource with version = stored + 1 and the new schema in its schemas",
        "response": "the stored LogTableSource",
        "permission": "owned groups",
        "notes": (
            "Requires sent version == stored version + 1 "
            "(InvalidLogTableSourceUpgradeSchemaVersion). Picks the sent schema whose "
            "logSchemaVersion equals the sent version (TableSchemaNotFound) and checks "
            "isValidSchema: a column keyed by schemaHeaderEventSource with "
            "LastUpdateDateTimeTagSelector (InvalidLogTableSchemaFormat). Stores the SENT "
            "record with schemas = new : stored schemas, so name, group, deleted, and "
            "requiresRestore must be copied from the stored source. Creates a new, EMPTY "
            "SQLite table for the version; earlier rows stay in the earlier version."
        ),
    },
    "logtable_delete": {
        "endpoint": "POST /logtable/{lj}/source/delete",
        "handler": f"{_LT} (postLogTableSourceDeleteR)",
        "request": 'JSON string — the source UUID',
        "response": "[]",
        "permission": "owned groups",
        "notes": "Soft delete: sets logTableSourceDeleted, so the source leaves source/list.",
    },
    "logtable_query": {
        "endpoint": "POST /logtable/{lj}/source/content/query/v2",
        "handler": f"{_LT} (postLogTableSourceContentQueryAndCountR)",
        "request": (
            "the LogTableSource with logTableSourceSchemaVersion = the version to read, "
            "and that version's schema carrying pagination, order, and filters"
        ),
        "response": "{queryResponseContent: [TableRow], queryResponseCount: int}",
        "permission": "owned-or-member groups",
        "notes": (
            "Projects non-hidden, non-Text columns in position order. A DateTime filter "
            "compiles to strftime('%Y-%m-%d %H:%M', col) <op> ?, so send minute-precision "
            "\"YYYY-MM-DD HH:MM\". Stored timestamps are \"YYYY-MM-DD HH:MM:SS\" UTC."
        ),
    },
}
