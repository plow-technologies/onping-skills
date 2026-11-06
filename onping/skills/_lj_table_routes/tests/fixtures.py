"""Synthetic TableSource / LogTableSource fixtures in the live wire shapes.

The shapes follow live reads from 2026-10-09 (data-table positions start at
1, log-table positions at 0, schemas listed newest first). Every PID, UUID,
and group id here is made up.
"""

from __future__ import annotations

import copy
import io
import json
import re
import uuid as _uuid

GROUP = "o000000000000000000000001"

C_TEXT = "11111111-1111-4111-8111-111111111111"
C_RES1 = "22222222-2222-4222-8222-222222222222"
C_RES2 = "33333333-3333-4333-8333-333333333333"
C_TIME = "44444444-4444-4444-8444-444444444444"


def datatable() -> dict:
    return copy.deepcopy({
        "tableId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "tableName": "Synthetic Data Table",
        "tableLJSerial": 9999,
        "tableGroupId": GROUP,
        "tableDeleted": False,
        "tableFrozenRows": [],
        "tableFrozenColumn": C_RES2,
        "tablePagination": {"tablePaginationLimit": 10, "tablePaginationOffset": 0},
        "tableDimensions": {
            "tableDimensionsCellWidth": 0, "tableDimensionsCellHeight": 0,
            "tableDimensionsHeaderXPadding": 0, "tableDimensionsHeaderYPadding": 0,
            "tableDimensionsCellXPadding": 0, "tableDimensionsCellYPadding": 0,
            "tableDimensionsCustomColumns": {C_TEXT: 150, C_RES2: 200},
        },
        "tableHeader": {
            "tableHeaderColumns": {
                C_TEXT: {"columnHeaderId": C_TEXT, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Well", "columnHeaderSelector": "TextTagSelector"},
                C_RES1: {"columnHeaderId": C_RES1, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Casing", "columnHeaderSelector": "ResultTagSelector"},
                C_RES2: {"columnHeaderId": C_RES2, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Tubing", "columnHeaderSelector": "ResultTagSelector"},
                C_TIME: {"columnHeaderId": C_TIME, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Updated",
                         "columnHeaderSelector": "LastUpdateDateTimeTagSelector"},
            },
            # Deliberately stored out of order, as the live JSON is ("1","10","11",...).
            "tableHeaderColumnsPosition": {"3": C_RES2, "1": C_TEXT, "4": C_TIME, "2": C_RES1},
            "tableHeaderColumnsOrder": {C_RES2: "ColumnOrderNumericDESC"},
            "tableHeaderHiddenColumns": [C_RES2],
            "tableHeaderFilters": [],
        },
    })


def datatable_rows() -> list[dict]:
    return [
        {"rowId": 1, "values": ["Alpha 1H", "101.5", "55.0", "2026-10-01 00:00:00"],
         "pointers": ["Alpha 1H", "500001", "500002", "500001"]},
        {"rowId": 2, "values": ["Bravo 2H", "99.0", "7.5", "2026-10-01 00:00:00"],
         "pointers": ["Bravo 2H", "500011", "77 VPID", "500011"]},
        {"rowId": 3, "values": [None, None, None, None],
         "pointers": [None, None, None, None]},
    ]


def single_filter(column: str) -> dict:
    return {"tag": "SingleFilterRule", "contents": {
        "singleFilterColumnRef": column,
        "singleFilterConcatenationOperator": "FilterConcatenationAND",
        "singleFilterOperator": "FilterIsNotBlank",
        "singleFilterInputValue": "",
        "singleFilterInputType": "FilterInputTypeNumber",
    }}


def group_filter(*columns: str) -> dict:
    return {"tag": "GroupFilterRule", "contents": {
        "groupFilterConcatenationOperator": "FilterConcatenationOR",
        "groupFilterSubFilters": [single_filter(c)["contents"] for c in columns],
    }}


L_EVENT = "55555555-5555-4555-8555-555555555555"
L_FLOW = "66666666-6666-4666-8666-666666666666"
L_VP = "77777777-7777-4777-8777-777777777777"


def _schema(version: int, cols: dict, positions: dict) -> dict:
    return {
        "logSchemaVersion": version,
        "logSchemaHeader": {
            "schemaHeaderEventSource": 600001,
            "schemaHeaderColumns": cols,
            "schemaHeaderColumnsPosition": positions,
            "schemaHeaderColumnsOrder": {L_EVENT: "ColumnOrderLexicographicDESC"},
            "schemaHeaderHiddenColumns": [L_VP],
            "schemaHeaderFilters": [],
        },
        "logSchemaPagination": None,
        "logSchemaFrozenRows": [],
        "logSchemaFrozenColumn": None,
        "logSchemaDimensions": {
            "tableDimensionsCellWidth": 0, "tableDimensionsCellHeight": 0,
            "tableDimensionsHeaderXPadding": 0, "tableDimensionsHeaderYPadding": 0,
            "tableDimensionsCellXPadding": 0, "tableDimensionsCellYPadding": 0,
            "tableDimensionsCustomColumns": {L_FLOW: 120},
        },
    }


def logtable() -> dict:
    event = {"columnSchemaId": L_EVENT, "columnSchemaKey": 600001,
             "columnSchemaName": "eventDateTime", "columnSchemaSelector": "LastUpdateDateTimeTagSelector"}
    flow = {"columnSchemaId": L_FLOW, "columnSchemaKey": 600002,
            "columnSchemaName": "flow", "columnSchemaSelector": "ResultTagSelector"}
    vp = {"columnSchemaId": L_VP, "columnSchemaKey": {"keyType": "VPID", "keyValue": 88},
          "columnSchemaName": "message", "columnSchemaSelector": "ResultTagSelector"}
    v2 = _schema(2, {L_EVENT: event, L_FLOW: flow, L_VP: vp},
                 {"0": L_EVENT, "1": L_FLOW, "2": L_VP})
    v1 = _schema(1, {L_EVENT: copy.deepcopy(event), L_FLOW: copy.deepcopy(flow)},
                 {"0": L_EVENT, "1": L_FLOW})
    return copy.deepcopy({
        "logTableSourceId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "logTableSourceName": "Synthetic Log Table",
        "logTableSourceLJSerial": 9999,
        "logTableSourceGroupId": GROUP,
        "logTableSourceSchemaVersion": 2,
        "logTableSourceSchemas": [v2, v1],  # newest first, as listed live
        "logTableSourceDeleted": False,
        "logTableSourceRequiresRestore": False,
    })


# =============================================================== fake Lumberjack
#
# An in-memory stand-in for the OnPing data-table routes, installed over `requests.request` so a
# skill's real code path (lj_http, pacing, 429, multipart) runs against it. Derived from reading the
# Haskell handlers; behaviours marked UNMEASURED are switches, not facts.


NIL = "00000000-0000-0000-0000-000000000000"
OTHER_GROUP = "o000000000000000000000002"
XLSX = "PK\x03\x04".encode("latin-1")


def view_from_source(src: dict, view_id: str | None = None) -> dict:
    """A TableView snapshot of a TableSource, as view/create builds it."""
    return copy.deepcopy({
        "tableViewId": view_id or str(_uuid.uuid4()),
        "tableViewTableSourceId": src["tableId"],
        "tableViewName": src["tableName"],
        "tableViewLJSerial": src["tableLJSerial"],
        "tableViewGroupId": src["tableGroupId"],
        "tableViewHeader": src["tableHeader"],
        "tableViewPagination": src.get("tablePagination"),
        "tableViewDeleted": False,
        "tableViewFrozenRows": src.get("tableFrozenRows") or [],
        "tableViewFrozenColumn": src.get("tableFrozenColumn"),
        "tableViewDimensions": src["tableDimensions"],
    })


def make_xlsx(headers: list[str], rows: list[list], sheet: str = "Sheet1") -> bytes:
    """A real .xlsx (needs openpyxl; tests that call it should importorskip)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status: int, text: str = "", content: bytes | None = None, url: str = ""):
        self.status_code = status
        self.text = text
        self.content = content if content is not None else text.encode()
        self.history: list = []
        self.url = url

    def json(self):
        return json.loads(self.text)


class FakeLumberjack:
    """One Lumberjack (`lj`) plus the widget collection.

    State: `sources` {uuid: TableSource}, `cells` {uuid: [{"rowId", "cells": {col: text|None}}]},
    `views` {uuid: TableView}, `widgets` {id: {...}}. Everything a skill sent is in `calls`.

    Switches (set them before the skill runs):
      deny_writes / deny_reads   500 Permission Denied (also: a source in OTHER_GROUP is denied)
      fail_next(status, ...)     answer the next matching write with `status` and apply NOTHING
      apply_then_fail_next(...)  apply the next matching write, THEN answer an error (the ambiguous
                                 failure that makes a blind resend duplicate rows)
      drop_add_index             silently drop that row of the next content/add
      duplicate_add_index        silently store that row of the next content/add twice
      short_rows                 "reject" (default) or "pad": a content/add row with fewer values
      rate_limit_after           answer 429 to every write after this many writes
      view_drop_fields           top-level view keys reset to empty on view/metadata/update
      view_ignore_update         accept view/metadata/update and change nothing
      routed                     False: every route answers 404 "Routing index could not be found"
    """

    def __init__(self, *, lj: int = 9999, token: str = "test-token", owned=(GROUP,), member=()):
        from _lj_table_routes.routes import BASE_URL, ROUTES
        self._base, self._routes = BASE_URL, ROUTES
        self.lj, self.token = lj, token
        self.owned, self.member = set(owned), set(member)
        self.routed = True
        self.sources: dict[str, dict] = {}
        self.cells: dict[str, list[dict]] = {}
        self.views: dict[str, dict] = {}
        self.widgets: dict[str, dict] = {}
        self.calls: list[tuple[str, str, object]] = []
        self.forbidden_calls: list[tuple[str, object]] = []
        self.sleeps: list[float] = []
        self.write_count = 0
        self.deny_writes = self.deny_reads = False
        self.short_rows = "reject"
        self.drop_add_index: int | None = None
        self.duplicate_add_index: int | None = None
        self.rate_limit_after: int | None = None
        self.view_drop_fields: set[str] = set()
        self.view_ignore_update = False
        self.import_preset: list[list] | None = None
        self._inject: list[dict] = []
        self._next_row = 1
        self._patterns = [
            (re.compile("^" + re.sub(r"\{[a-z]+\}", "([^/]+)", spec["endpoint"].split(" ", 1)[1]) + "$"),
             spec["endpoint"].split(" ", 1)[0], key,
             re.findall(r"\{([a-z]+)\}", spec["endpoint"]))
            for key, spec in ROUTES.items() if key.startswith("datatable_")
        ]

    # ------------------------------------------------------------ test setup
    def install(self, monkeypatch) -> "FakeLumberjack":
        from _lj_table_routes import lj_http, pace
        monkeypatch.setattr(lj_http.requests, "request", self.request)
        monkeypatch.setattr(pace, "sleep", lambda s: self.sleeps.append(s))
        pace.reset()
        return self

    def add_source(self, src: dict | None = None, rows: list[list] | None = None) -> dict:
        src = copy.deepcopy(src or datatable())
        src["tableLJSerial"] = self.lj
        self.sources[src["tableId"]] = src
        self.cells[src["tableId"]] = []
        for pointers in rows if rows is not None else [r["pointers"] for r in datatable_rows()]:
            self._append(src["tableId"], pointers)
        return copy.deepcopy(src)

    def add_widget(self, view_id=NIL, lj=None, dashboard_id=None) -> str:
        wid = "w" + _uuid.uuid4().hex[:23]
        self.widgets[wid] = {"dataTableWidgetTableViewId": view_id, "dataTableWidgetLJSerial": lj,
                             "dataTableWidgetDashboardId": dashboard_id}
        return wid

    def add_view(self, source_id: str, widget_dashboard_id=None, place: bool = True) -> tuple[dict, str | None]:
        view = view_from_source(self.sources[source_id])
        self.views[view["tableViewId"]] = view
        wid = self.add_widget(view["tableViewId"], self.lj, widget_dashboard_id) if place else None
        return copy.deepcopy(view), wid

    def fail_next(self, status: int, error: str = "RegenerationInProgress", times: int = 1,
                  route: str | None = None) -> None:
        self._inject.append({"status": status, "error": error, "times": times, "route": route, "apply": False})

    def apply_then_fail_next(self, status: int = 500, error: str = "boom", times: int = 1,
                             route: str | None = None) -> None:
        self._inject.append({"status": status, "error": error, "times": times, "route": route, "apply": True})

    def save_card(self, dashboard_id: str, widget_id: str, insert: str = "repsert") -> str:
        """The server's copy-on-save for a data-table card (read from SaveDashboardEmbeddedKeys.hs,
        NOT yet measured live). Returns the widget id the saved card ends up naming."""
        w = self.widgets[widget_id]
        if w["dataTableWidgetLJSerial"] is None:
            w["dataTableWidgetDashboardId"] = dashboard_id
            return widget_id
        owner = w["dataTableWidgetDashboardId"]
        if insert == "repsert" and owner is None:
            w["dataTableWidgetDashboardId"] = dashboard_id
            return widget_id
        if insert == "repsert" and owner == dashboard_id:
            return widget_id
        view = copy.deepcopy(self.views[w["dataTableWidgetTableViewId"]])
        view["tableViewId"] = str(_uuid.uuid4())
        self.views[view["tableViewId"]] = view
        return self.add_widget(view["tableViewId"], w["dataTableWidgetLJSerial"], dashboard_id)

    # ---------------------------------------------------------- inspection
    def rows(self, table_id: str) -> list[dict]:
        """The table as the query returns it: [{rowId, values, pointers}], pointers in position order."""
        src = self.sources[table_id]
        order = self._order(src)
        return [{"rowId": r["rowId"], "pointers": [r["cells"].get(c) for c in order],
                 "values": [self._render(src, c, r["cells"].get(c)) for c in order]}
                for r in self.cells[table_id]]

    def writes(self) -> list[tuple[str, object]]:
        return [(k, b) for (m, k, b) in self.calls if self._routes[k].get("writes")]

    def keys(self) -> list[str]:
        return [k for (_m, k, _b) in self.calls]

    # ------------------------------------------------------------ internals
    @staticmethod
    def _order(src: dict) -> list[str]:
        h = src["tableHeader"]
        return [c for _p, c in sorted((int(p), c) for p, c in h["tableHeaderColumnsPosition"].items())
                if h["tableHeaderColumns"][c]["columnHeaderSelector"] != "InvalidTagSelector"]

    @staticmethod
    def _render(src: dict, col: str, text):
        if text is None:
            return None
        sel = src["tableHeader"]["tableHeaderColumns"][col]["columnHeaderSelector"]
        return text if sel == "TextTagSelector" else f"val({text})"

    def _append(self, table_id: str, pointers: list) -> int:
        order = self._order(self.sources[table_id])
        rid, self._next_row = self._next_row, self._next_row + 1
        self.cells[table_id].append({"rowId": rid, "cells": dict(zip(order, pointers))})
        return rid

    def _ok(self, payload=None) -> FakeResponse:
        return FakeResponse(200, json.dumps([] if payload is None else payload))

    @staticmethod
    def _err(status: int, msg: str) -> FakeResponse:
        return FakeResponse(status, json.dumps({"error": msg}))

    def _denied(self) -> FakeResponse:
        return self._err(500, "Permission Denied")

    def _may_write(self, group: str) -> bool:
        return not self.deny_writes and group in self.owned

    def _may_read(self, group: str) -> bool:
        return not self.deny_reads and (group in self.owned or group in self.member)

    # ---------------------------------------------------------------- entry
    def request(self, method, url, headers=None, data=None, files=None, allow_redirects=True, timeout=None):
        path = url[len(self._base):] if url.startswith(self._base) else url
        headers = headers or {}
        if headers.get("Authorization") != f"Bearer {self.token}":
            return FakeResponse(401, "Unauthorized")
        key, params = None, {}
        for rx, m, k, names in self._patterns:
            hit = rx.match(path)
            if hit and m == method:
                key, params = k, dict(zip(names, hit.groups()))
                break
        if key is None:
            return FakeResponse(404, json.dumps({"error": f"no such route {method} {path}"}))
        spec = self._routes[key]
        body = None
        if spec.get("multipart"):
            body = {"files": files or {}, "data": data or {}}
        elif method == "POST":
            body = json.loads(data) if data else None
        self.calls.append((method, key, body))
        if spec.get("forbidden"):
            self.forbidden_calls.append((key, body))
        if not self.routed and "lj" in params:
            return self._err(404, "Routing index could not be found.\n")
        if "lj" in params and int(params["lj"]) != self.lj:
            return self._err(404, "Routing index could not be found.\n")
        pending = None
        if spec.get("writes"):
            self.write_count += 1
            if self.rate_limit_after is not None and self.write_count > self.rate_limit_after:
                return FakeResponse(429, "Too Many Requests")
            for inj in self._inject:
                if inj["times"] > 0 and (inj["route"] is None or inj["route"] == key):
                    inj["times"] -= 1
                    if not inj["apply"]:
                        return self._err(inj["status"], inj["error"])
                    pending = inj
                    break
        resp = getattr(self, "_" + key)(body, **params)
        if pending is not None and resp.status_code == 200:
            return self._err(pending["status"], pending["error"])
        return resp

    # --------------------------------------------------------- source routes
    def _group(self, table_id):
        s = self.sources.get(table_id)
        return None if s is None else s["tableGroupId"]

    def _datatable_all(self, _b):
        return self._ok([s for s in self.sources.values() if self._may_read(s["tableGroupId"])])

    def _datatable_list(self, _b, lj):
        return self._datatable_all(_b)

    def _datatable_create(self, body):
        if not self._may_write(body.get("tableGroupId")):
            return self._denied()
        if int(body["tableLJSerial"]) != self.lj:
            return self._err(404, "Routing index could not be found.\n")
        src = copy.deepcopy(body)
        src["tableId"] = str(_uuid.uuid4())
        self.sources[src["tableId"]] = src
        self.cells[src["tableId"]] = []
        return self._ok(src["tableId"])

    def _datatable_delete(self, body, lj):
        g = self._group(body)
        if g is None or not self._may_write(g):
            return self._denied()
        self.sources[body]["tableDeleted"] = True
        self.cells[body] = []
        return self._ok()

    def _datatable_query(self, body, lj):
        return self._query(body["tableId"], body.get("tablePagination"))

    def _query(self, table_id, page):
        g = self._group(table_id)
        if g is None or not self._may_read(g):
            return self._denied()
        rows = self.rows(table_id)
        total = len(rows)
        if page:
            off, lim = page.get("tablePaginationOffset", 0), page["tablePaginationLimit"]
            rows = rows[off:off + lim]
        return self._ok({
            "queryResponseContent": [{"tableRowId": r["rowId"], "tableRowValues": r["values"]} for r in rows],
            # reversed on purpose: the real server does not order pointers
            "queryResponsePointers": [{"tableRowId": r["rowId"], "tableRowValues": r["pointers"]}
                                      for r in reversed(rows)],
            "queryResponseCount": total})

    def _datatable_content_add(self, body, lj):
        from _lj_table_routes import datatable as dt
        table_id, rows = body
        g = self._group(table_id)
        if g is None or not self._may_write(g):
            return self._denied()
        src = self.sources[table_id]
        cols = self._order(src)
        staged = []
        for row in rows:
            if len(row) > len(cols):
                return self._err(400, "InvalidNumberOfColumns")
            if len(row) < len(cols):
                if self.short_rows == "reject":
                    return self._err(400, "InvalidNumberOfColumns")
                row = list(row) + [None] * (len(cols) - len(row))
            for c, cell in zip(cols, row):
                try:
                    dt.check_cell(src["tableHeader"]["tableHeaderColumns"][c]["columnHeaderSelector"], cell)
                except ValueError as e:
                    return self._err(400, f"InvalidRowContent: {e}")
            staged.append(row)
        drop, dup = self.drop_add_index, self.duplicate_add_index
        self.drop_add_index = self.duplicate_add_index = None
        for i, row in enumerate(staged):
            if i == drop:
                continue
            self._append(table_id, row)
            if i == dup:
                self._append(table_id, row)
        return self._ok()

    def _datatable_content_update(self, body, lj):
        table_id, rows = body
        g = self._group(table_id)
        if g is None or not self._may_write(g):
            return self._denied()
        cols = self._order(self.sources[table_id])
        by = {r["rowId"]: r for r in self.cells[table_id]}
        for r in rows:
            if len(r["tableRowValues"]) != len(cols):
                return self._err(400, "RowUpdateColumnsNumberMismatch")
            if r["tableRowId"] in by:
                by[r["tableRowId"]]["cells"] = dict(zip(cols, r["tableRowValues"]))
        return self._ok()

    def _datatable_content_delete(self, body, lj):
        table_id, ids = body
        g = self._group(table_id)
        if g is None or not self._may_write(g):
            return self._denied()
        gone = set(ids)
        self.cells[table_id] = [r for r in self.cells[table_id] if r["rowId"] not in gone]
        return self._ok()

    def _datatable_content_delete_by_table(self, body, lj):
        table_id, with_filters = body
        g = self._group(table_id)
        if g is None or not self._may_write(g):
            return self._denied()
        if not with_filters:
            self.cells[table_id] = []  # the real route clears the filters and deletes EVERY row
        return self._ok()

    def _datatable_metadata_update(self, body, lj):
        table_id = body["tableId"]
        g = self._group(table_id)
        if g is None or not self._may_write(g):
            return self._denied()
        stored = self.sources[table_id]
        old_cols = stored["tableHeader"]["tableHeaderColumns"]
        new_cols = body["tableHeader"]["tableHeaderColumns"]
        old_order = self._order(stored)
        for rows in self.cells[table_id]:
            rows["cells"] = {c: v for c, v in rows["cells"].items() if c in new_cols}
        incoming = copy.deepcopy(body)
        for cid, col in incoming["tableHeader"]["tableHeaderColumns"].items():
            col["columnHeaderNewOrDuplicate"] = None
        stored.update({k: incoming[k] for k in incoming if k not in ("tableId", "tableLJSerial", "tableGroupId")})
        for cid in new_cols:
            if cid not in old_cols:
                for r in self.cells[table_id]:
                    r["cells"].setdefault(cid, None)
        del old_order
        return self._ok()

    def _datatable_import(self, body, lj):
        return self._import(body, template=False)

    def _datatable_import_template(self, body, lj):
        return self._import(body, template=True)

    def _import(self, body, *, template):
        parts, form = body["files"], body["data"]
        if set(parts) != {"f1"} or set(form) != {"f2"}:
            return self._err(400, "Form Missing: Failed to get file from form submission.")
        table_id = form["f2"]
        g = self._group(table_id)
        if g is None or not self._may_write(g):
            return self._denied()
        rows = self.import_preset
        if rows is None:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(parts["f1"][1]))
            if "Sheet1" not in wb.sheetnames:
                return self._err(400, "Sheet1 not found")
            rows = [list(r) for r in wb["Sheet1"].iter_rows(min_row=2, values_only=True)]
        for row in rows:
            self._append(table_id, [None if c is None else str(c) for c in row])
        return self._ok(self.sources[table_id])

    def _datatable_template(self, body, lj, name):
        g = self._group(body)
        if g is None or not self._may_read(g):
            return self._denied()
        return FakeResponse(200, content=XLSX + b"template")

    def _datatable_export_dump(self, body, lj, name):
        g = self._group(body)
        if g is None or not self._may_read(g):
            return self._denied()
        return FakeResponse(200, content=XLSX + json.dumps(self.rows(body)).encode())

    # ---------------------------------------------------- widget / view routes
    def _datatable_view_all(self, _b):
        return self._ok([v for v in self.views.values() if self._may_read(v["tableViewGroupId"])])

    def _datatable_widget_create(self, _b):
        return self._ok(self.add_widget())

    def _datatable_widget_get(self, _b, widget):
        w = self.widgets.get(widget)
        if w is None:
            return FakeResponse(200, "null")
        if w["dataTableWidgetLJSerial"] is not None:
            v = self.views.get(w["dataTableWidgetTableViewId"])
            if v is None or not self._may_read(v["tableViewGroupId"]):
                return self._denied()
        return self._ok(w)

    def _datatable_view_create(self, body, widget):
        g = self._group(body["tableId"])
        if g is None or not self._may_write(g):
            return self._denied()
        w = self.widgets.get(widget)
        if w is None:
            return self._err(404, "widget not found")
        view = view_from_source(self.sources[body["tableId"]])
        self.views[view["tableViewId"]] = view
        w.update({"dataTableWidgetTableViewId": view["tableViewId"],
                  "dataTableWidgetLJSerial": body["tableLJSerial"], "dataTableWidgetDashboardId": None})
        return self._ok(view["tableViewId"])

    def _datatable_view_delete(self, _b, widget):
        w = self.widgets.get(widget)
        if w is None:
            return self._ok()
        if w["dataTableWidgetLJSerial"] is not None:
            v = self.views.get(w["dataTableWidgetTableViewId"])
            if v is None or not self._may_write(v["tableViewGroupId"]):
                return self._denied()
            v["tableViewDeleted"] = True
        del self.widgets[widget]
        return self._ok()

    def _view_for(self, view_id, write):
        v = self.views.get(view_id)
        if v is None:
            return None, self._err(404, "TableViewNotFound")
        ok = self._may_write(v["tableViewGroupId"]) if write else self._may_read(v["tableViewGroupId"])
        return (v, None) if ok else (None, self._denied())

    def _datatable_view_get(self, body, lj):
        v, err = self._view_for(body, False)
        return err or self._ok(v)

    def _datatable_view_query(self, body, lj):
        v, err = self._view_for(body["tableViewId"], False)
        return err or self._query(v["tableViewTableSourceId"], body.get("tableViewPagination"))

    def _status(self, v):
        src = self.sources.get(v["tableViewTableSourceId"])
        if src is None or src.get("tableDeleted"):
            return {"tag": "TableViewDeprecated"}
        vc, sc = v["tableViewHeader"]["tableHeaderColumns"], src["tableHeader"]["tableHeaderColumns"]
        deleted = [vc[c] for c in vc if c not in sc]
        added = [sc[c] for c in sc if c not in vc]
        updated = [[sc[c], vc[c]] for c in sc if c in vc and sc[c] != vc[c]]
        if not (deleted or added or updated):
            return {"tag": "TableViewSynced"}
        return {"tag": "TableViewUnSynced", "contents": {
            "columnsDeletedInSource": deleted, "columnsAddedInSource": added,
            "columnsUpdatedInSource": updated}}

    def _datatable_view_sync_status(self, body, lj):
        v, err = self._view_for(body, False)
        return err or self._ok(self._status(v))

    def _datatable_view_sync(self, body, lj):
        v, err = self._view_for(body, True)
        if err:
            return err
        src = self.sources[v["tableViewTableSourceId"]]
        vh, sh = v["tableViewHeader"], src["tableHeader"]
        vh["tableHeaderColumns"] = copy.deepcopy(sh["tableHeaderColumns"])
        vh["tableHeaderColumnsPosition"] = copy.deepcopy(sh["tableHeaderColumnsPosition"])
        return self._ok()

    def _datatable_view_metadata_update(self, body, lj):
        v, err = self._view_for(body["tableViewId"], True)
        if err:
            return err
        if self.view_ignore_update:
            return self._ok()
        keep = set(v["tableViewHeader"]["tableHeaderColumns"])
        new = copy.deepcopy(body)
        h = new["tableViewHeader"]
        h["tableHeaderColumns"] = v["tableViewHeader"]["tableHeaderColumns"]  # column set is fixed
        h["tableHeaderColumnsPosition"] = {p: c for p, c in h["tableHeaderColumnsPosition"].items() if c in keep}
        h["tableHeaderHiddenColumns"] = [c for c in h["tableHeaderHiddenColumns"] if c in keep]
        for k in self.view_drop_fields:
            new[k] = [] if isinstance(new.get(k), list) else None
        self.views[v["tableViewId"]] = new
        return self._ok()

    # documented-only routes
    def _datatable_column_upsert(self, body, lj):
        return self._err(501, "not modelled")

    def _datatable_sync_request(self, body, lj):
        return self._err(501, "not modelled")

    def _datatable_sync_status(self, body, lj):
        return self._err(501, "not modelled")
