"""Row-level helpers for the data-table row, import and export skills.

Pure functions plus three thin POST wrappers. Nothing here prints or exits.

A row is a list of cell texts in column-position order (what `content/add` takes and what the
query's `pointers` hold): "1234", "4321 VPID", free text in a Text column, or None.

Adding rows is not idempotent: the server appends and does not return the new row ids, so
replaying a batch after a failure duplicates it. `plan_resume` therefore decides what is left by
comparing the table against a baseline taken before the first batch (`make_state`), never by
trusting a batch counter.
"""

from __future__ import annotations

import collections
import hashlib
import json
from typing import Any, Iterable

from . import datatable as dt
from .lj_http import LJTableError, post_bytes, post_json, post_multipart
from .pointers import INVALID_SELECTOR

BATCH_SIZE = 100
BATCH_CEILING = 100  # the user's ruling; raise only after a live limit check says it is safe
STATE_KIND = "datatable-rows-add-state"
BACKUP_KIND = "datatable-rows"


# ------------------------------------------------------------ column mapping

def writable_columns(src: dict) -> list[dict]:
    """The columns a row has a value for, in position order.

    A table with an InvalidTagSelector column is refused: the server leaves that column out of
    every row but counts it when matching values to columns, so positional rows would misalign.
    """
    cols = dt.columns(src)
    if any(c["selector"] == INVALID_SELECTOR for c in cols):
        raise ValueError(
            "this table has an InvalidTagSelector column; the server counts it when matching "
            "values to columns but leaves it out of every row, so positional rows would misalign. "
            "Fix the column in the UI first.")
    if not cols:
        raise ValueError(
            "this table has no columns yet (a new source has none). Add columns with "
            "onping-datatable-column-add, or import an xlsx, before adding rows.")
    return cols


def header_map(src: dict, headers: Iterable[str]) -> list[dict]:
    """Map file headers to columns by name (exact, then case-insensitive). Returns the column per header.

    Refuses an unknown header, a header named twice, an ambiguous column name, and a table column
    that no header covers (a short row would be padded or rejected by the server, which is unmeasured).
    """
    cols = writable_columns(src)
    out: list[dict] = []
    seen: set[str] = set()
    for h in headers:
        try:
            col = dt.resolve_column(src, str(h))
        except ValueError as e:
            raise ValueError(f"header {h!r}: {e}") from e
        if col["id"].lower() in seen:
            raise ValueError(f"header {h!r} names column {col['name']!r}, which an earlier header already covers")
        seen.add(col["id"].lower())
        out.append(col)
    missing = [c["name"] for c in cols if c["id"].lower() not in seen]
    if missing:
        raise ValueError(f"the file has no column for table column(s) {missing}; every column needs a header "
                         "(leave a cell empty for null)")
    return out


def build_rows(src: dict, headers: list[str], records: list[list[Any]]) -> list[list[str | None]]:
    """File records (cell lists in header order) -> positional rows, every cell checked.

    Empty strings and None become null. Errors name the 1-based record number and the column.
    """
    mapped = header_map(src, headers)
    order = sorted(range(len(mapped)), key=lambda i: mapped[i]["position"])
    rows: list[list[str | None]] = []
    for n, rec in enumerate(records, start=1):
        if len(rec) != len(mapped):
            raise ValueError(f"record {n} has {len(rec)} cells but the file has {len(mapped)} headers")
        row: list[str | None] = []
        for i in order:
            cell = rec[i]
            text = None if cell is None or str(cell).strip() == "" else str(cell).strip()
            try:
                dt.check_cell(mapped[i]["selector"], text)
            except ValueError as e:
                raise ValueError(f"record {n}, column {mapped[i]['name']!r}: {e}") from e
            row.append(text)
        rows.append(row)
    return rows


def check_rows(src: dict, rows: list[list[Any]]) -> None:
    """Validate already-positional rows: width equals the column count and every cell passes."""
    cols = writable_columns(src)
    for n, row in enumerate(rows, start=1):
        if len(row) != len(cols):
            raise ValueError(f"row {n} has {len(row)} values but the table has {len(cols)} columns")
        for c, cell in zip(cols, row):
            try:
                dt.check_cell(c["selector"], cell)
            except ValueError as e:
                raise ValueError(f"row {n}, column {c['name']!r}: {e}") from e


# ----------------------------------------------------------------- batching

def split_batches(rows: list[list[Any]], size: int = BATCH_SIZE) -> list[list[list[Any]]]:
    if not 1 <= size <= BATCH_CEILING:
        raise ValueError(f"batch size must be 1..{BATCH_CEILING}, got {size}")
    return [rows[i:i + size] for i in range(0, len(rows), size)]


# ------------------------------------------------------------ snapshots/diffs

def signature(pointers: list[Any] | None) -> tuple:
    return tuple(pointers or ())


def row_ids(rows: list[dict]) -> list[int]:
    return sorted(r["rowId"] for r in rows)


def new_rows(before: list[dict], after: list[dict]) -> list[dict]:
    """Rows in `after` whose id was not in `before`, in id order."""
    known = {r["rowId"] for r in before}
    return sorted((r for r in after if r["rowId"] not in known), key=lambda r: r["rowId"])


def rows_hash(rows: list[dict]) -> str:
    """Stable hash of (rowId, pointers) pairs, for --expect-hash on a delete preview."""
    canon = json.dumps([[r["rowId"], r["pointers"]] for r in sorted(rows, key=lambda r: r["rowId"])],
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def add_mismatches(before: list[dict], after: list[dict], sent: list[list[Any]]) -> list[str]:
    """Compare a read-back to what one add sent. Empty list = exactly the sent rows landed, once.

    Existing rows must be unchanged (same ids and cells), and the new rows must equal the sent
    rows as a multiset (row ids are not returned by the server, so order is not compared).
    """
    problems: list[str] = []
    after_by = {r["rowId"]: r for r in after}
    for r in before:
        got = after_by.get(r["rowId"])
        if got is None:
            problems.append(f"existing row {r['rowId']} is gone after the add")
        elif signature(got["pointers"]) != signature(r["pointers"]):
            problems.append(f"existing row {r['rowId']} changed after the add")
    landed = collections.Counter(signature(r["pointers"]) for r in new_rows(before, after))
    want = collections.Counter(signature(r) for r in sent)
    if len(after) - len(before) != len(sent):
        problems.append(f"expected {len(sent)} new row(s), the table grew by {len(after) - len(before)}")
    for sig, n in (want - landed).items():
        problems.append(f"{n} sent row(s) did not land: {list(sig)}")
    for sig, n in (landed - want).items():
        problems.append(f"{n} unexpected new row(s) (duplicate or foreign): {list(sig)}")
    return problems


def delete_mismatches(before: list[dict], after: list[dict], ids: list[int]) -> list[str]:
    """Compare a read-back to a delete by id: exactly `ids` gone, every other row untouched."""
    problems: list[str] = []
    gone = set(ids)
    before_by = {r["rowId"]: r for r in before}
    after_by = {r["rowId"]: r for r in after}
    for i in sorted(gone & set(after_by)):
        problems.append(f"row {i} is still present after the delete")
    for i, r in sorted(before_by.items()):
        if i in gone:
            continue
        got = after_by.get(i)
        if got is None:
            problems.append(f"row {i} was not on the delete list but is gone")
        elif signature(got["pointers"]) != signature(r["pointers"]):
            problems.append(f"row {i} was not on the delete list but changed")
    for i in sorted(set(after_by) - set(before_by)):
        problems.append(f"unexpected new row {i} appeared during the delete")
    return problems


# ------------------------------------------------------------------- resume

def make_state(src: dict, baseline: list[dict], rows: list[list[Any]]) -> dict:
    """The resume file for one add run: the table, the rows it had before the first batch, and every
    row the run intends to add. Written BEFORE the first POST."""
    return {
        "kind": STATE_KIND, "tableId": src["tableId"], "lj": src["tableLJSerial"],
        "tableName": src.get("tableName"),
        "baselineRowIds": row_ids(baseline), "baselineHash": rows_hash(baseline),
        "rows": [list(r) for r in rows],
    }


def load_state(doc: Any, src: dict) -> dict:
    """Validate a parsed resume file against the table it is about to be applied to."""
    if not isinstance(doc, dict) or doc.get("kind") != STATE_KIND:
        raise ValueError("not a rows-add resume file")
    if str(doc.get("tableId", "")).lower() != str(src["tableId"]).lower() or doc.get("lj") != src["tableLJSerial"]:
        raise ValueError(f"the resume file is for table {doc.get('tableId')} on LJ {doc.get('lj')}, "
                         f"not {src['tableId']} on LJ {src['tableLJSerial']}")
    if not isinstance(doc.get("rows"), list) or not isinstance(doc.get("baselineRowIds"), list):
        raise ValueError("the resume file is missing rows or baselineRowIds")
    return doc


def plan_resume(state: dict, current: list[dict]) -> dict:
    """Decide what an interrupted add still has to send, without duplicating anything.

    New rows (ids not in the baseline) are matched against the intended rows as a multiset:
      - `done`    intended rows already present, by index into state["rows"];
      - `pending` intended rows not yet present (index, row), in file order;
      - `foreign` new rows that match no intended row (another writer, or a duplicate already
                  made): a non-empty list means STOP, the table needs a human look;
      - `lost`    baseline row ids no longer present (also STOP).
    """
    base = set(state["baselineRowIds"])
    present = {r["rowId"] for r in current}
    lost = sorted(base - present)
    landed = collections.Counter(signature(r["pointers"]) for r in current if r["rowId"] not in base)
    done: list[int] = []
    pending: list[tuple[int, list[Any]]] = []
    for i, row in enumerate(state["rows"]):
        sig = signature(row)
        if landed[sig] > 0:
            landed[sig] -= 1
            done.append(i)
        else:
            pending.append((i, row))
    foreign = [list(sig) for sig, n in landed.items() for _ in range(n)]
    return {"done": done, "pending": pending, "foreign": foreign, "lost": lost,
            "safe": not foreign and not lost}


# -------------------------------------------------------------- backup shape

def backup_doc(src: dict, rows: list[dict]) -> dict:
    """The row backup, in the shape rows-add can re-add: columns in position order, then each row's
    stored cells. Row ids are kept for the record but are not reused on re-add."""
    cols = writable_columns(src)
    return {
        "kind": BACKUP_KIND, "tableId": src["tableId"], "lj": src["tableLJSerial"],
        "tableName": src.get("tableName"),
        "columns": [{"id": c["id"], "name": c["name"], "selector": c["selector"], "position": c["position"]}
                    for c in cols],
        "rows": [{"rowId": r["rowId"], "cells": list(r["pointers"])}
                 for r in sorted(rows, key=lambda r: r["rowId"])],
    }


def rows_from_backup(doc: dict, src: dict) -> list[list[Any]]:
    """Positional rows from a backup, after checking its columns still match the table."""
    if not isinstance(doc, dict) or doc.get("kind") != BACKUP_KIND:
        raise ValueError("not a data-table rows backup")
    have = [(c["id"].lower(), c["selector"]) for c in writable_columns(src)]
    want = [(str(c["id"]).lower(), c["selector"]) for c in doc.get("columns") or []]
    if have != want:
        raise ValueError("the backup's columns differ from the table's current columns; re-add by hand")
    return [list(r["cells"]) for r in doc.get("rows") or []]


# ---------------------------------------------------------------- POST thin

def post_add(token: str, src: dict, batch: list[list[Any]]) -> None:
    post_json(token, "datatable_content_add", [src["tableId"], batch], lj=src["tableLJSerial"])


def post_delete(token: str, src: dict, ids: list[int]) -> None:
    if not ids:
        raise LJTableError("refusing to send a delete with no row ids")
    post_json(token, "datatable_content_delete", [src["tableId"], sorted(ids)], lj=src["tableLJSerial"])


def post_create(token: str, body: dict) -> str:
    out = post_json(token, "datatable_create", body)
    if not isinstance(out, str):
        raise LJTableError(f"Expected the new table UUID, got {out!r}")
    return out


def create_body(name: str, lj: int, group: str) -> dict:
    """The create body the Configure page sends: empty header, page size 25, nothing else set."""
    return {
        "tableId": dt.NIL_UUID, "tableName": name, "tableLJSerial": lj, "tableGroupId": group,
        "tableHeader": {"tableHeaderColumns": {}, "tableHeaderColumnsPosition": {},
                        "tableHeaderColumnsOrder": {}, "tableHeaderHiddenColumns": [],
                        "tableHeaderFilters": []},
        "tablePagination": {"tablePaginationLimit": 25, "tablePaginationOffset": 0},
        "tableDeleted": False, "tableFrozenRows": [], "tableFrozenColumn": None,
        "tableDimensions": {"tableDimensionsCellWidth": 0, "tableDimensionsCellHeight": 0,
                            "tableDimensionsHeaderXPadding": 0, "tableDimensionsHeaderYPadding": 0,
                            "tableDimensionsCellXPadding": 0, "tableDimensionsCellYPadding": 0,
                            "tableDimensionsCustomColumns": {}},
    }


# ------------------------------------------------------------ import / export

XLSX_MAGIC = b"PK\x03\x04"


def export_file(token: str, src: dict, name: str, *, template: bool = False) -> bytes:
    """The source as an .xlsx: every row (dump) or just the header row (template)."""
    route = "datatable_template" if template else "datatable_export_dump"
    data = post_bytes(token, route, src["tableId"], lj=src["tableLJSerial"], name=name)
    if not data.startswith(XLSX_MAGIC):
        raise LJTableError(f"{route} did not return an .xlsx file ({len(data)} bytes)")
    return data


def import_file(token: str, src: dict, content: bytes, filename: str, *, template: bool = False) -> Any:
    """Upload an .xlsx. Multipart parts are the Yesod auto-names f1 (file) and f2 (table UUID)."""
    if not content.startswith(XLSX_MAGIC):
        raise ValueError("not an .xlsx file")
    route = "datatable_import_template" if template else "datatable_import"
    return post_multipart(token, route, {"f2": src["tableId"]}, ("f1", filename, content),
                          lj=src["tableLJSerial"])
