"""Data Table views and widgets: parsing, pure edits that never change the column set, hashing,
read-back diffs, the widget-ownership check, and thin route wrappers.

A TableView is a snapshot of a source (`tableViewTableSourceId`) with its own header:

    {tableViewId, tableViewTableSourceId, tableViewName, tableViewLJSerial, tableViewGroupId,
     tableViewHeader: {same TableHeader as a source}, tableViewPagination, tableViewDeleted,
     tableViewFrozenRows, tableViewFrozenColumn, tableViewDimensions}

A widget is a Mongo doc {dataTableWidgetTableViewId, dataTableWidgetLJSerial,
dataTableWidgetDashboardId}; a dashboard card names the widget, never the view.

Every edit here is pure and returns a new view. None of them touches `tableHeaderColumns` (the
column set) or `tableHeaderFilters`: filter editing is out of scope for v1 and a view update must
send the stored filters back unchanged.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from . import datatable as dt
from .lj_http import LJTableError, get_json, post_json

REQUIRED = ("tableViewId", "tableViewTableSourceId", "tableViewLJSerial", "tableViewGroupId",
            "tableViewHeader", "tableViewDimensions")


# ------------------------------------------------------------------ parsing

def parse_view(doc: Any) -> dict:
    if not isinstance(doc, dict):
        raise LJTableError(f"Expected a TableView object, got {type(doc).__name__}")
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        raise LJTableError(f"TableView is missing {missing}")
    return doc


def as_table(view: dict) -> dict:
    """The view in TableSource shape, so `datatable.columns` / `resolve_column` read it."""
    return {"tableHeader": view.get("tableViewHeader") or {},
            "tablePagination": view.get("tableViewPagination"),
            "tableFrozenColumn": view.get("tableViewFrozenColumn")}


def columns(view: dict) -> list[dict]:
    return dt.columns(as_table(view))


def resolve_column(view: dict, ref: str) -> dict:
    return dt.resolve_column(as_table(view), ref)


def column_set(view: dict) -> frozenset[str]:
    return frozenset(k.lower() for k in (view.get("tableViewHeader") or {}).get("tableHeaderColumns") or {})


def filters_of(view: dict) -> list:
    return list((view.get("tableViewHeader") or {}).get("tableHeaderFilters") or [])


# ----------------------------------------------------------- pure view edits

def _header(new: dict) -> dict:
    return new.setdefault("tableViewHeader", {})


def set_hidden(view: dict, refs: list[str], hidden: bool) -> dict:
    new = copy.deepcopy(view)
    h = _header(new)
    current = list(h.get("tableHeaderHiddenColumns") or [])
    lowered = {c.lower() for c in current}
    for ref in refs:
        cid = resolve_column(view, ref)["id"]
        if hidden and cid.lower() not in lowered:
            current.append(cid)
            lowered.add(cid.lower())
        elif not hidden and cid.lower() in lowered:
            current = [c for c in current if c.lower() != cid.lower()]
            lowered.discard(cid.lower())
    h["tableHeaderHiddenColumns"] = current
    return new


def reorder(view: dict, refs: list[str]) -> dict:
    """Show the named columns first, in the given order; the rest follow in their current order.

    Only `tableHeaderColumnsPosition` changes (positions renumbered 1..n). The sort order
    (`tableHeaderColumnsOrder`) is a different thing and is left alone.
    """
    new = copy.deepcopy(view)
    firsts: list[str] = []
    for ref in refs:
        cid = resolve_column(view, ref)["id"]
        if cid.lower() in {f.lower() for f in firsts}:
            raise ValueError(f"column {ref!r} is named twice in --order")
        firsts.append(cid)
    rest = [c["id"] for c in columns(view) if c["id"].lower() not in {f.lower() for f in firsts}]
    _header(new)["tableHeaderColumnsPosition"] = {str(i): cid for i, cid in enumerate(firsts + rest, start=1)}
    return new


def set_page_size(view: dict, size: int) -> dict:
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ValueError(f"page size must be a positive integer, got {size!r}")
    new = copy.deepcopy(view)
    page = dict(new.get("tableViewPagination") or {"tablePaginationOffset": 0})
    page["tablePaginationLimit"] = size
    new["tableViewPagination"] = page
    return new


def set_frozen_column(view: dict, ref: str | None) -> dict:
    new = copy.deepcopy(view)
    new["tableViewFrozenColumn"] = None if ref is None else resolve_column(view, ref)["id"]
    return new


def preserved_problems(stored: dict, new: dict) -> list[str]:
    """What a view-update must never change: the column set, the filters, the dimensions, and the
    identity fields. A non-empty list means the transform is wrong; send nothing."""
    problems = []
    if column_set(stored) != column_set(new):
        problems.append("the column set changed")
    if (stored.get("tableViewHeader") or {}).get("tableHeaderColumns") != \
            (new.get("tableViewHeader") or {}).get("tableHeaderColumns"):
        problems.append("a column definition changed")
    if filters_of(stored) != filters_of(new):
        problems.append("the filters changed")
    if stored.get("tableViewDimensions") != new.get("tableViewDimensions"):
        problems.append("the dimensions changed")
    for k in ("tableViewId", "tableViewTableSourceId", "tableViewName", "tableViewLJSerial",
              "tableViewGroupId", "tableViewDeleted", "tableViewFrozenRows"):
        if stored.get(k) != new.get(k):
            problems.append(f"{k} changed")
    return problems


# ------------------------------------------------------------ hash and diff

def view_hash(view: dict) -> str:
    """Stable hash of a whole view, for --expect-hash on a preview."""
    canon = json.dumps(view, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def _norm_positions(view: dict) -> list[str]:
    return [c["id"].lower() for c in columns(view)]


def view_mismatches(expected: dict, actual: dict) -> list[str]:
    """Compare what was sent to what was read back. Any difference is a failure: a dropped field,
    a changed filter, a moved column. Column ORDER is compared by the position-sorted id list, so a
    renumbered but equal order is fine."""
    problems: list[str] = []
    for k in expected:
        if k not in actual:
            problems.append(f"{k} is missing after the write")
    if column_set(expected) != column_set(actual):
        problems.append("column set differs after the write")
    if _norm_positions(expected) != _norm_positions(actual):
        problems.append("column order differs after the write")
    eh, ah = expected.get("tableViewHeader") or {}, actual.get("tableViewHeader") or {}
    if sorted(map(str.lower, eh.get("tableHeaderHiddenColumns") or [])) != \
            sorted(map(str.lower, ah.get("tableHeaderHiddenColumns") or [])):
        problems.append("hidden columns differ after the write")
    if eh.get("tableHeaderFilters") != ah.get("tableHeaderFilters"):
        problems.append("filters differ after the write")
    if eh.get("tableHeaderColumnsOrder") != ah.get("tableHeaderColumnsOrder"):
        problems.append("sort order differs after the write")
    if eh.get("tableHeaderColumns") != ah.get("tableHeaderColumns"):
        problems.append("column definitions differ after the write")
    for k in ("tableViewPagination", "tableViewFrozenRows", "tableViewFrozenColumn",
              "tableViewDimensions", "tableViewName", "tableViewGroupId", "tableViewLJSerial",
              "tableViewTableSourceId", "tableViewDeleted"):
        if k in expected and expected.get(k) != actual.get(k):
            problems.append(f"{k} differs after the write")
    return problems


# --------------------------------------------------- widget ownership / copies

def widget_state(widget: dict | None, dashboard_id: str | None) -> str:
    """Where a widget stands for a dashboard that wants to hold it:

    missing   no such widget (the read answered null);
    empty     created, no view yet (ljSerial null): safe to fill and place;
    unclaimed has a view, dashboardId null: a save of this dashboard claims it in place;
    own       dashboardId equals `dashboard_id`;
    foreign   dashboardId is another dashboard's: a save would COPY it (a new view and widget).
    """
    if widget is None:
        return "missing"
    if widget.get("dataTableWidgetLJSerial") is None:
        return "empty"
    owner = widget.get("dataTableWidgetDashboardId")
    if owner is None:
        return "unclaimed"
    if dashboard_id is not None and str(owner).lower() == str(dashboard_id).lower():
        return "own"
    return "foreign"


def duplication_failures(before_views: list[dict], after_views: list[dict],
                         expected_new: list[str] | None = None) -> list[str]:
    """Live views in `after_views` that were not live before and are not in `expected_new`.

    A save or copy that makes a view nobody asked for (a copy-on-save fork of a foreign widget)
    is a FAILURE; the caller exits non-zero on any line returned.
    """
    want = {x.lower() for x in expected_new or []}
    live_before = {v["tableViewId"].lower() for v in before_views if not v.get("tableViewDeleted")}
    problems = []
    for v in after_views:
        vid = v["tableViewId"].lower()
        if v.get("tableViewDeleted") or vid in live_before or vid in want:
            continue
        problems.append(f"unexpected new view {v['tableViewId']} ({v.get('tableViewName')!r}) "
                        f"on source {v.get('tableViewTableSourceId')}")
    return problems


def sync_state(status: Any) -> str:
    """'synced' | 'deprecated' | 'unsynced' from a sync/status answer."""
    tag = status.get("tag") if isinstance(status, dict) else status
    table = {"TableViewSynced": "synced", "TableViewDeprecated": "deprecated",
             "TableViewUnSynced": "unsynced"}
    if tag not in table:
        raise LJTableError(f"Unrecognised view sync status: {status!r}")
    return table[tag]


# --------------------------------------------------------------- POST / GET

def all_views(token: str) -> list[dict]:
    data = get_json(token, "datatable_view_all")
    if not isinstance(data, list):
        raise LJTableError(f"Expected a JSON array of TableView, got {type(data).__name__}")
    return [v for v in data if isinstance(v, dict)]


def read_view(token: str, lj: Any, view_id: str) -> dict:
    return parse_view(post_json(token, "datatable_view_get", view_id, lj=lj))


def read_widget(token: str, widget_id: str) -> dict | None:
    out = get_json(token, "datatable_widget_get", widget=widget_id)
    if out is not None and not isinstance(out, dict):
        raise LJTableError(f"Expected a widget object or null, got {type(out).__name__}")
    return out


def create_widget(token: str) -> str:
    out = post_json(token, "datatable_widget_create", None)
    if not isinstance(out, str):
        raise LJTableError(f"Expected the new widget id, got {out!r}")
    return out


def create_view(token: str, widget_id: str, src: dict) -> str:
    out = post_json(token, "datatable_view_create", src, widget=widget_id)
    if not isinstance(out, str):
        raise LJTableError(f"Expected the new view UUID, got {out!r}")
    return out


def delete_widget_view(token: str, widget_id: str) -> None:
    post_json(token, "datatable_view_delete", None, widget=widget_id)


def read_sync_status(token: str, lj: Any, view_id: str) -> Any:
    return post_json(token, "datatable_view_sync_status", view_id, lj=lj)


def post_sync(token: str, lj: Any, view_id: str) -> None:
    post_json(token, "datatable_view_sync", view_id, lj=lj)


def post_view_update(token: str, view: dict) -> None:
    post_json(token, "datatable_view_metadata_update", view, lj=view["tableViewLJSerial"])
