"""Data-table (`/datatable/...`) reads, pure transforms, and verified writes.

A `TableSource` (onping-datatable-types) is:

    {tableId, tableName, tableLJSerial, tableGroupId,
     tableHeader: {tableHeaderColumns: {uuid: {columnHeaderId, columnHeaderNewOrDuplicate,
                                               columnHeaderName, columnHeaderSelector}},
                   tableHeaderColumnsPosition: {"<int>": uuid},
                   tableHeaderColumnsOrder: {uuid: ColumnOrder},
                   tableHeaderHiddenColumns: [uuid], tableHeaderFilters: [FilterRule]},
     tablePagination: {tablePaginationLimit, tablePaginationOffset} | null,
     tableDeleted, tableFrozenRows: [int], tableFrozenColumn: uuid | null,
     tableDimensions: {..., tableDimensionsCustomColumns: {uuid: int}}}

A column holds only a selector. Each row's cells hold the pointer as text —
"1234" (PID) or "4321 VPID" — or literal text in a Text column, or null.

Row values (content and pointers alike) follow the columns in ascending
position order, skipping InvalidTagSelector columns.

The transforms (`add_column`, `delete_column`, `set_cells`) are pure: they
return new values and never touch the server, so they are unit-tested offline.
"""

from __future__ import annotations

import copy
import uuid as _uuid
from typing import Any

from . import filters as _filters
from .lj_http import LJTableError, get_json, post_json
from .pointers import INVALID_SELECTOR, TEXT_SELECTOR, Pointer, parse_cell, try_parse_cell

NIL_UUID = "00000000-0000-0000-0000-000000000000"


# --------------------------------------------------------------------- reads

def list_sources(token: str, lj: Any = None) -> list[dict]:
    """Sources on one LJ, or (lj=None) on every LJ you can see."""
    if lj is None:
        data = get_json(token, "datatable_all")
    else:
        data = get_json(token, "datatable_list", lj=lj)
    if not isinstance(data, list):
        raise LJTableError(f"Expected a JSON array of TableSource, got {type(data).__name__}")
    return [s for s in data if isinstance(s, dict) and not s.get("tableDeleted")]


def find_source(token: str, lj: Any, table_id: str) -> dict:
    want = table_id.lower()
    sources = list_sources(token, lj)
    for s in sources:
        if str(s.get("tableId", "")).lower() == want:
            return s
    raise LJTableError(
        f"No data table {table_id} on LJ {lj} ({len(sources)} source(s) listed). "
        "Find it with onping-datatable-list --all."
    )


def _header(src: dict) -> dict:
    return src.get("tableHeader") or {}


def columns(src: dict) -> list[dict]:
    """The column grid in position order.

    Each entry: position, id, name, selector, hidden, and `index` — the column's
    index into a row's values (None for an InvalidTagSelector column, which the
    server leaves out of every row).
    """
    h = _header(src)
    cols = h.get("tableHeaderColumns") or {}
    hidden = {str(x).lower() for x in h.get("tableHeaderHiddenColumns") or []}
    out: list[dict] = []
    index = 0
    for pos, cid in sorted(((int(p), c) for p, c in (h.get("tableHeaderColumnsPosition") or {}).items())):
        col = cols.get(cid)
        if col is None:
            continue
        sel = col.get("columnHeaderSelector")
        entry = {
            "position": pos,
            "id": cid,
            "name": col.get("columnHeaderName"),
            "selector": sel,
            "hidden": cid.lower() in hidden,
            "index": None if sel == INVALID_SELECTOR else index,
        }
        if sel != INVALID_SELECTOR:
            index += 1
        out.append(entry)
    return out


def resolve_column(src: dict, ref: str) -> dict:
    """Find a column by position, UUID, or exact name (then case-insensitive name)."""
    cols = columns(src)
    ref = ref.strip()
    if ref.lstrip("-").isdigit():
        for c in cols:
            if c["position"] == int(ref):
                return c
        raise ValueError(f"no column at position {ref}")
    for c in cols:
        if c["id"].lower() == ref.lower():
            return c
    for exact in (True, False):
        hits = [c for c in cols
                if (c["name"] == ref if exact else str(c["name"]).lower() == ref.lower())]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"column name {ref!r} is ambiguous "
                             f"(positions {[c['position'] for c in hits]}); use the position or UUID")
    raise ValueError(f"no column matches {ref!r} (by position, UUID, or name)")


def query_body(src: dict, *, limit: int | None = None, offset: int = 0) -> dict:
    """The query/v3 body: the stored source with filters and order cleared.

    Stored filters would hide rows (a live table's IsNotBlank filter returned
    count 0), so they are cleared. `limit=None` sends null pagination, which
    returns every row in one response.
    """
    body = copy.deepcopy(src)
    h = body.setdefault("tableHeader", {})
    h["tableHeaderFilters"] = []
    h["tableHeaderColumnsOrder"] = {}
    body["tablePagination"] = (
        None if limit is None
        else {"tablePaginationLimit": limit, "tablePaginationOffset": offset}
    )
    return body


def join_rows(resp: dict) -> list[dict]:
    """Join content and pointers on tableRowId (the server does not order pointers)."""
    pointers = {r.get("tableRowId"): r.get("tableRowValues") or []
                for r in resp.get("queryResponsePointers") or []}
    rows = []
    for r in resp.get("queryResponseContent") or []:
        rid = r.get("tableRowId")
        rows.append({"rowId": rid, "values": r.get("tableRowValues") or [],
                     "pointers": pointers.get(rid)})
    return rows


def query(token: str, src: dict, *, limit: int | None = None, offset: int = 0) -> tuple[list[dict], int]:
    resp = post_json(token, "datatable_query", query_body(src, limit=limit, offset=offset),
                     lj=src["tableLJSerial"])
    if not isinstance(resp, dict):
        raise LJTableError(f"Expected a QueryResponse object, got {type(resp).__name__}")
    rows = join_rows(resp)
    missing = [r["rowId"] for r in rows if r["pointers"] is None]
    if missing:
        raise LJTableError(f"query/v3 returned content rows with no pointer row: {missing[:10]}")
    return rows, int(resp.get("queryResponseCount") or 0)


def query_all(token: str, src: dict) -> list[dict]:
    rows, count = query(token, src, limit=None)
    if len(rows) != count:
        raise LJTableError(f"query/v3 returned {len(rows)} rows but a count of {count}")
    return sorted(rows, key=lambda r: r["rowId"])


def row_cells(src: dict, row: dict) -> list[dict]:
    """One row as a unit: a cell per column, with its pointer text, parsed pointer, and value."""
    cells = []
    for c in columns(src):
        i = c["index"]
        raw = None if i is None or i >= len(row["pointers"]) else row["pointers"][i]
        value = None if i is None or i >= len(row["values"]) else row["values"][i]
        p = None if c["selector"] == TEXT_SELECTOR else try_parse_cell(raw)
        cells.append({
            "position": c["position"], "column": c["id"], "name": c["name"],
            "selector": c["selector"], "hidden": c["hidden"],
            "pointer": raw if c["selector"] != TEXT_SELECTOR else None,
            "pointerKind": p.kind if p else None, "pointerValue": p.value if p else None,
            "text": raw if c["selector"] == TEXT_SELECTOR else None,
            "value": value,
        })
    return cells


def cells_pointing_at(src: dict, rows: list[dict], target: Pointer) -> list[dict]:
    hits = []
    for row in rows:
        for cell in row_cells(src, row):
            if cell["pointerKind"] == target.kind and cell["pointerValue"] == target.value:
                hits.append({"rowId": row["rowId"], **cell})
    return hits


# ---------------------------------------------------------- pure transforms

def add_column(src: dict, name: str, selector: str, at: int | None = None) -> tuple[dict, str]:
    """Return (new source, new column id) with an empty column added.

    The column gets a fresh uuid4 and columnHeaderNewOrDuplicate = nil UUID,
    which the metadata/update diff turns into ALTER ADD COLUMN. `at` is the
    stored position the column takes; columns at or after it shift up by one.
    Default: after the last column.
    """
    if not name.strip():
        raise ValueError("a column name is required")
    if selector == INVALID_SELECTOR:
        raise ValueError("InvalidTagSelector is not a column type")
    existing = columns(src)
    if any(str(c["name"]) == name for c in existing):
        raise ValueError(f"a column named {name!r} already exists; names must stay unique "
                         "for --column NAME to resolve")
    new = copy.deepcopy(src)
    h = new.setdefault("tableHeader", {})
    cols = h.setdefault("tableHeaderColumns", {})
    positions = {int(p): c for p, c in (h.get("tableHeaderColumnsPosition") or {}).items()}
    base = min(positions) if positions else 1
    top = max(positions) + 1 if positions else base
    if at is None:
        at = top
    if not (base <= at <= top):
        raise ValueError(f"--at must be between {base} and {top}")
    cid = str(_uuid.uuid4())
    cols[cid] = {
        "columnHeaderId": cid,
        "columnHeaderNewOrDuplicate": NIL_UUID,
        "columnHeaderName": name,
        "columnHeaderSelector": selector,
    }
    shifted = {(p + 1 if p >= at else p): c for p, c in positions.items()}
    shifted[at] = cid
    h["tableHeaderColumnsPosition"] = {str(p): c for p, c in sorted(shifted.items())}
    return new, cid


def delete_column(src: dict, column_id: str, *, drop_filters: bool = False) -> dict:
    """Return a new source without the column.

    Removes it from columns, positions (re-packed contiguously from the
    existing lowest position), order, hidden, the dimensions' custom widths,
    and the frozen column. Refuses if a stored filter references the column,
    unless drop_filters.
    """
    new = copy.deepcopy(src)
    h = new.setdefault("tableHeader", {})
    cols = h.get("tableHeaderColumns") or {}
    key = next((k for k in cols if k.lower() == column_id.lower()), None)
    if key is None:
        raise ValueError(f"no column {column_id}")
    refs = _filters.rules_referencing(h.get("tableHeaderFilters") or [], key)
    if refs and not drop_filters:
        raise ValueError(
            f"{len(refs)} stored filter rule(s) reference this column; "
            "re-run with --drop-filters to remove those references too"
        )
    h["tableHeaderFilters"] = _filters.drop_column(h.get("tableHeaderFilters") or [], key)
    del cols[key]
    stored = {int(p): c for p, c in (h.get("tableHeaderColumnsPosition") or {}).items()}
    base = min(stored, default=1)
    positions = sorted((p, c) for p, c in stored.items() if c.lower() != key.lower())
    h["tableHeaderColumnsPosition"] = {str(base + i): c for i, (_, c) in enumerate(positions)}
    h["tableHeaderColumnsOrder"] = {k: v for k, v in (h.get("tableHeaderColumnsOrder") or {}).items()
                                    if k.lower() != key.lower()}
    h["tableHeaderHiddenColumns"] = [c for c in h.get("tableHeaderHiddenColumns") or []
                                     if c.lower() != key.lower()]
    dims = new.get("tableDimensions")
    if isinstance(dims, dict) and isinstance(dims.get("tableDimensionsCustomColumns"), dict):
        dims["tableDimensionsCustomColumns"] = {
            k: v for k, v in dims["tableDimensionsCustomColumns"].items() if k.lower() != key.lower()}
    if str(new.get("tableFrozenColumn") or "").lower() == key.lower():
        new["tableFrozenColumn"] = None
    return new


def check_cell(selector: str, value: Any) -> None:
    """Refuse a value the server would reject for this column type.

    A Text column takes any text. Every other column takes only pointer text.
    Callers decide intent (a --pid aimed at a Text column is refused by the
    cell-set script, since the server would store it as inert text).
    """
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"cell values are text or null, got {value!r}")
    if selector == TEXT_SELECTOR:
        return  # literal text; digits are fine (an ID column), and never resolve a PID
    parse_cell(value)  # raises the server's own message


def set_cells(src: dict, rows: list[dict], edits: list[tuple[int, str, Any]]) -> list[dict]:
    """Apply (rowId, columnId, newCellText|None) edits; return content/update rows.

    Each returned row carries its FULL pointer value list (the server requires
    every value, in position order), sorted by tableRowId. Only rows with at
    least one real change are returned.
    """
    cols = {c["id"].lower(): c for c in columns(src)}
    if any(c["index"] is None for c in cols.values()):
        raise ValueError(
            "this table has an InvalidTagSelector column; the server counts it when "
            "matching values to columns but leaves it out of every row, so a content "
            "update would misalign. Fix the column in the UI first.")
    by_id = {r["rowId"]: r for r in rows}
    changed: dict[int, list] = {}
    for row_id, column_id, value in edits:
        if row_id not in by_id:
            raise ValueError(f"no row {row_id}")
        col = cols.get(column_id.lower())
        if col is None:
            raise ValueError(f"no column {column_id}")
        check_cell(col["selector"], value)
        current = changed.get(row_id) or list(by_id[row_id]["pointers"])
        if len(current) != len(cols):
            raise ValueError(f"row {row_id} has {len(current)} values but the table has "
                             f"{len(cols)} columns; re-read the table and retry")
        current[col["index"]] = value
        changed[row_id] = current
    return [{"tableRowId": rid, "tableRowValues": vals}
            for rid, vals in sorted(changed.items())
            if vals != list(by_id[rid]["pointers"])]


def replace_pointer_edits(src: dict, rows: list[dict], old: Pointer, new: Pointer,
                          column_id: str | None = None) -> list[tuple[int, str, str]]:
    from .pointers import render_cell
    edits = []
    for hit in cells_pointing_at(src, rows, old):
        if column_id and hit["column"].lower() != column_id.lower():
            continue
        edits.append((hit["rowId"], hit["column"], render_cell(new)))
    return edits


# ------------------------------------------------------------ verified writes

def post_metadata(token: str, new_src: dict) -> None:
    post_json(token, "datatable_metadata_update", new_src, lj=new_src["tableLJSerial"])


def post_content(token: str, src: dict, rows: list[dict]) -> None:
    post_json(token, "datatable_content_update", [src["tableId"], rows], lj=src["tableLJSerial"])


def header_mismatches(expected: dict, actual: dict) -> list[str]:
    """Compare the parts of a header a column edit controls.

    Tolerates what the server legitimately rewrites: NewOrDuplicate comes back
    null, and positions may be renumbered (only the column order is compared).
    """
    problems = []
    exp = [(c["id"].lower(), c["name"], c["selector"]) for c in columns(expected)]
    act = [(c["id"].lower(), c["name"], c["selector"]) for c in columns(actual)]
    if [e[0] for e in exp] != [a[0] for a in act]:
        problems.append(f"column order differs: expected {[e[1] for e in exp]}, "
                        f"read back {[a[1] for a in act]}")
    act_by = {a[0]: a for a in act}
    for e in exp:
        a = act_by.get(e[0])
        if a is None:
            problems.append(f"column {e[1]!r} ({e[0]}) is missing after the write")
        elif a != e:
            problems.append(f"column {e[0]}: expected {e[1]!r}/{e[2]}, read back {a[1]!r}/{a[2]}")
    for a in act:
        if a[0] not in {e[0] for e in exp}:
            problems.append(f"unexpected column {a[1]!r} ({a[0]}) after the write")
    eh, ah = _header(expected), _header(actual)
    if sorted(map(str.lower, eh.get("tableHeaderHiddenColumns") or [])) != \
            sorted(map(str.lower, ah.get("tableHeaderHiddenColumns") or [])):
        problems.append("hidden columns differ after the write")
    if len(eh.get("tableHeaderFilters") or []) != len(ah.get("tableHeaderFilters") or []):
        problems.append("filter count differs after the write")
    return problems


def cell_mismatches(expected_rows: list[dict], actual_rows: list[dict]) -> list[str]:
    actual = {r["rowId"]: r["pointers"] for r in actual_rows}
    problems = []
    for r in expected_rows:
        got = actual.get(r["tableRowId"])
        if got != r["tableRowValues"]:
            problems.append(f"row {r['tableRowId']}: expected {r['tableRowValues']}, read back {got}")
    return problems
