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
        "writes": True,
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
        "writes": True,
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
    # --------------------------------------------- datatable: source lifecycle and rows
    "datatable_create": {
        "endpoint": "POST /datatable/source/create",
        "writes": True,
        "handler": f"{_DT} (postDataTableSourceCreateR)",
        "request": (
            "TableSource: tableId nil UUID (the server draws its own), tableName, tableLJSerial, "
            "tableGroupId, tableHeader with empty maps and tableHeaderFilters [], tablePagination "
            "{limit 25, offset 0}, tableDeleted false, zeroed tableDimensions, tableFrozenRows [], "
            "tableFrozenColumn null"
        ),
        "response": "JSON string - the new source UUID",
        "permission": "tableGroupId must be in the caller's OWNED groups",
        "notes": (
            "No {lj} in the path: the Lumberjack is tableLJSerial in the body. Audited (Create). "
            "A new source has NO columns; columns come from onping-datatable-column-add or an "
            "xlsx import."
        ),
    },
    "datatable_delete": {
        "endpoint": "POST /datatable/{lj}/source/delete",
        "writes": True,
        "handler": f"{_DT} (postDataTableSourceDeleteR)",
        "request": "JSON string - the source UUID",
        "response": "[]",
        "permission": "owned groups",
        "notes": (
            "Soft-deletes the store entry but DROPS the SQLite data table and decrements PID "
            "subscriptions. The server has no undo. Audited (Delete). Views of the source are "
            "not touched and keep pointing at it."
        ),
    },
    "datatable_content_add": {
        "endpoint": "POST /datatable/{lj}/source/content/add",
        "writes": True,
        "handler": f"{_DT} (postDataTableSourceContentAddR)",
        "request": '["<table uuid>", [[text|null, ...], ...]]  (rows positional, by column position)',
        "response": "[]",
        "permission": "owned groups",
        "notes": (
            "APPENDS rows. NOT audited. New row ids are not returned (server FIXME), so a skill "
            "finds its rows by re-reading and diffing. More values than columns -> "
            "InvalidNumberOfColumns; FEWER is unmeasured (live check). A non-text cell must parse "
            "as \"1234\" or \"4321 VPID\" (InvalidRowContent). Takes the regeneration lock "
            "(503 while held). Replaying a batch after a failure DUPLICATES rows: resume only "
            "after counting what landed (see datatable_rows.plan_resume)."
        ),
    },
    "datatable_content_delete": {
        "endpoint": "POST /datatable/{lj}/source/content/delete",
        "writes": True,
        "handler": f"{_DT} (postDataTableSourceContentDeleteR)",
        "request": '["<table uuid>", [rowId, ...]]',
        "response": "[]",
        "permission": "owned groups",
        "notes": "Deletes the listed row ids only. NOT audited; the skill's backup is the only trail.",
    },
    "datatable_content_delete_by_table": {
        "endpoint": "POST /datatable/{lj}/source/content/delete/by/table",
        "writes": True,
        "forbidden": True,
        "handler": f"{_DT} (postDataTableSourceContentDeleteByTableR)",
        "request": '["<table uuid>", withFilters: bool]',
        "response": "[]",
        "permission": "owned groups",
        "notes": (
            "FORBIDDEN: no skill calls it (user ruling 2026-11-05, delete-all-rows is deferred). "
            "withFilters false clears the stored filters and deletes EVERY row; true deletes the "
            "rows matching the stored filters. NOT audited. lj_http refuses to send it."
        ),
    },
    "datatable_column_upsert": {
        "endpoint": "POST /datatable/{lj}/source/column/upsert",
        "writes": True,
        "unused": True,
        "handler": f"{_DT} (postDataTableSourceColumnUpsertR)",
        "request": "ColumnUpsertRequest {columnUpsertRequestTableId, columnUpsertRequestColumnHeader, columnUpsertRequestColumnContent}",
        "response": "unmeasured",
        "permission": "owned groups",
        "notes": "Documented only; no skill uses it (column-add goes through metadata/update).",
    },
    "datatable_import": {
        "endpoint": "POST /datatable/{lj}/source/import",
        "writes": True,
        "multipart": True,
        "handler": f"{_DT} (postDataTableSourceImportFromCustomTableR)",
        "request": "multipart: f1 = the .xlsx file, f2 = the table UUID (Yesod auto-names, not 'file'/'tableId')",
        "response": "the TableSource",
        "permission": "owned groups",
        "notes": (
            "Sheet must be named Sheet1; row 1 holds text headers; row 2 infers each column's "
            "selector. APPENDS when run on a table that already has data. Triggers a metadata "
            "sync job. Audited (Update)."
        ),
        "timeout": 300,
    },
    "datatable_import_template": {
        "endpoint": "POST /datatable/{lj}/source/import/template",
        "writes": True,
        "multipart": True,
        "handler": f"{_DT} (postDataTableSourceImportFromTemplateR)",
        "request": "multipart: f1 = the .xlsx file, f2 = the table UUID",
        "response": "the TableSource",
        "permission": "owned groups",
        "notes": "Template headers must match the current headers; rows are appended. Audited (Update).",
        "timeout": 300,
    },
    "datatable_template": {
        "endpoint": "POST /datatable/{lj}/source/template/{name}",
        "returns": "bytes",
        "handler": f"{_DT} (postDataTableSourceTemplateR)",
        "request": "JSON string - the source UUID",
        "response": "an .xlsx template (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet)",
        "permission": "owned-or-member groups; refusal is HTTP 500 \"Permission Denied\"",
        "notes": "POST but read-only. {name} becomes the returned file name; end it in .xlsx.",
        "timeout": 300,
    },
    "datatable_export_dump": {
        "endpoint": "POST /datatable/{lj}/source/export/dump/{name}",
        "returns": "bytes",
        "handler": f"{_DT} (postDataTableSourceExportDumpR)",
        "request": "JSON string - the source UUID",
        "response": "an .xlsx dump of every row",
        "permission": "owned-or-member groups; refusal is HTTP 500 \"Permission Denied\"",
        "notes": "POST but read-only. {name} becomes the returned file name; end it in .xlsx.",
        "timeout": 300,
    },
    "datatable_sync_request": {
        "endpoint": "POST /datatable/{lj}/source/metadata/sync/request",
        "writes": True,
        "unused": True,
        "handler": f"{_DT} (postDataTableSourceMetadataSyncRequestR)",
        "request": "unmeasured",
        "response": "unmeasured",
        "permission": "the Lumberjack's group must be owned",
        "notes": "Source synchronization is deferred (user ruling 2026-11-05). Documented only.",
    },
    "datatable_sync_status": {
        "endpoint": "POST /datatable/{lj}/source/metadata/sync/status",
        "unused": True,
        "handler": f"{_DT} (postDataTableSourceMetadataSyncStatusR)",
        "request": "unmeasured",
        "response": "unmeasured",
        "permission": "unmeasured",
        "notes": "Source synchronization is deferred. Documented only.",
    },
    # ------------------------------------------------------------- datatable: widgets and views
    "datatable_view_all": {
        "endpoint": "GET /datatable/router/view/all",
        "handler": f"{_DT} (getAllDataTableViewsR)",
        "response": "JSON [TableView] across every routed Lumberjack",
        "permission": "views whose tableViewGroupId is in the caller's owned-or-member groups",
        "notes": "The only view list: there is no per-Lumberjack list route. Soft-deleted views are flagged tableViewDeleted.",
        "timeout": 300,
    },
    "datatable_widget_create": {
        "endpoint": "POST /datatable/widget/config/create",
        "writes": True,
        "handler": f"{_DT} (postDataTableWidgetCreateR)",
        "request": "null (the page sends no body)",
        "response": "JSON string - the new widget id",
        "permission": "NONE: anyone can create an empty widget",
        "notes": (
            "Creates a Mongo doc {tableViewId nil, ljSerial null, dashboardId null}. An empty "
            "widget that is never given a view is a leftover to clean up with widget/.../view/delete."
        ),
    },
    "datatable_widget_get": {
        "endpoint": "GET /datatable/widget/{widget}",
        "handler": f"{_DT} (getDataTableWidgetR)",
        "response": (
            "null | {dataTableWidgetTableViewId, dataTableWidgetLJSerial|null, "
            "dataTableWidgetDashboardId|null}"
        ),
        "permission": "an empty widget (null serial) has no check; else the view's group must be owned-or-member",
        "notes": "dataTableWidgetDashboardId is the dashboard that owns the widget; null means unclaimed.",
    },
    "datatable_view_create": {
        "endpoint": "POST /datatable/widget/{widget}/view/create",
        "writes": True,
        "handler": f"{_DT} (postDataTableViewCreateR)",
        "request": "the TableSource the view snapshots",
        "response": "JSON string - the new view UUID",
        "permission": "the SOURCE's group must be owned",
        "notes": (
            "Builds a TableView snapshot of the source and REPSERTS the widget to point at it "
            "(ljSerial set, dashboardId null). If the widget already named a view, that view is "
            "orphaned, not deleted. Audited (Create)."
        ),
    },
    "datatable_view_delete": {
        "endpoint": "POST /datatable/widget/{widget}/view/delete",
        "writes": True,
        "handler": f"{_DT} (postDataTableViewDeleteR)",
        "request": "null",
        "response": "[]",
        "permission": "an empty widget has no check; else the view's group must be owned",
        "notes": (
            "Deletes the widget doc and soft-deletes its view (source data untouched). A missing "
            "widget answers success. A dashboard card still naming the widget is left dangling. "
            "Audited."
        ),
    },
    "datatable_view_get": {
        "endpoint": "POST /datatable/{lj}/view/get",
        "handler": f"{_DT} (postDataTableViewR)",
        "request": "JSON string - the view UUID",
        "response": "the TableView",
        "permission": "owned-or-member groups",
        "notes": "POST but read-only.",
    },
    "datatable_view_query": {
        "endpoint": "POST /datatable/{lj}/view/content/query/v3",
        "handler": f"{_DT} (postDataTableViewContentQueryAndCountAndPointersR)",
        "request": "the TableView (its own filters, order, pagination apply)",
        "response": "{queryResponseContent, queryResponsePointers, queryResponseCount}",
        "permission": "owned-or-member groups",
        "notes": "POST but read-only. Same join rule as the source query: by tableRowId, never by index.",
    },
    "datatable_view_sync_status": {
        "endpoint": "POST /datatable/{lj}/view/sync/status",
        "handler": f"{_DT} (postDataTableViewIsInSyncWithSourceStatusR)",
        "request": "JSON string - the view UUID",
        "response": (
            '{"tag": "TableViewSynced"} | {"tag": "TableViewDeprecated"} | {"tag": "TableViewUnSynced", '
            '"contents": {columnsDeletedInSource, columnsAddedInSource, columnsUpdatedInSource}} '
            "(aeson default sum encoding; confirm live)"
        ),
        "permission": "owned-or-member groups",
        "notes": "POST but read-only.",
    },
    "datatable_view_sync": {
        "endpoint": "POST /datatable/{lj}/view/sync",
        "writes": True,
        "handler": f"{_DT} (postDataTableViewSyncWithSourceR)",
        "request": "JSON string - the view UUID",
        "response": "[]",
        "permission": "owned groups",
        "notes": "Carries source column changes into the view. Audited (Update) only when the view changed.",
    },
    "datatable_view_metadata_update": {
        "endpoint": "POST /datatable/{lj}/view/metadata/update",
        "writes": True,
        "handler": f"{_DT} (postDataTableViewMetadataUpdateR)",
        "request": "the full TableView (read-modify-write; partial bodies are unmeasured)",
        "response": "[]",
        "permission": "owned groups",
        "notes": (
            "The view's column SET is fixed: columns cannot be added or dropped here and unknown "
            "column entries are stripped. Position, order, hidden columns, filters, pagination, "
            "frozen state and dimensions change. Audited (Update)."
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
