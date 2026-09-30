"""Decode a `custom_table_widget_audit` row into a postable CustomTableWidget.

The audit table does not store the widget in the shape the API accepts, so a
decode step sits between recovery and restore. Four encodings differ, and each one
below was found by getting it wrong against real data first. Each therefore gets
an assertion rather than a comment.

TRAP 1 — the `s` prefix has exactly two homes.
  `encodeStringWithSPrefix = Text.cons 's'` (ColumnSerialization.hs), and
  the inverse fails on a missing prefix (:263-268). Per
  CustomTableWidgetAudit.hs only `headers` and each cell's `desc` are
  encoded; `title` and `type` persist through a bare `SomePersistField` and are
  stored RAW. Decoding `type` as prefixed turns `customTable` into `ustomTable`.
  That is not hypothetical — it was the first bug in the real decoder.

TRAP 2 — `dashboard` is `MongoIdUtf8NoO`.
  Hex of the ASCII id with the leading `o` removed. A widget posted with the raw
  hex names an unresolvable parent, and a widget whose parent will not resolve is
  unwritable through the API (Permissions.hs). Fail rather than pass it on.

TRAP 3 — six `CellData` fields cannot round-trip.
  `PostgresCellData` models 16 of the 22 fields; `fromPostgresCellData`
  (PostgresCellData.hs) hardcodes the other six to `Nothing`. They are
  display toggles. Row and column indices, every PID, and conditional formatting
  all survive. Emitted as null and documented, so a reviewer never has to wonder
  whether the skill lost them or the schema did.

TRAP 4 — sorting must be null.
  `indexCustomTableBySortingInformation` (TableSort.hs) re-sorts the table and
  rewrites every cell row index when the value carries both a column and a type.
  The handler persists `Nothing` anyway (Table.hs), so null is both safe and
  faithful.
"""

from __future__ import annotations

import json
from typing import Any

from .routes import WIDGET_KEYS  # noqa: F401 - re-exported for callers

# TRAP 3: dropped by PostgresCellData, emitted as null.
DROPPED_CELL_FIELDS = (
    "cellDataShowcompanyid",
    "cellDataShowcompany",
    "cellDataShowsiteid",
    "cellDataShowsite",
    "cellDataShowlocid",
    "cellDataShowsourceid",
)

# postgres cell key -> live JSON cell key. The 16 fields PostgresCellData carries.
CELL_KEY_MAP = {
    "row": "cellDataRow",
    "col": "cellDataCol",
    "desc": "cellDataDesc",
    "pid": "cellDataPid",
    "status": "cellDataStatus",
    "vpid": "cellDataVpid",
    "vstatus": "cellDataVstatus",
    "formatting": "cellDataFormatting",
    "showlocation": "cellDataShowlocation",
    "showname": "cellDataShowname",
    "showpid": "cellDataShowpid",
    "showunit": "cellDataShowunit",
    "showwriteable": "cellDataShowwriteable",
    "showlastupdate": "cellDataShowlastupdate",
    "showlastupdatetime": "cellDataShowlastupdatetime",
    "hideresult": "cellDataHideresult",
}

# The only legitimate value of the raw-stored `type` column, besides null. Asserted
# after decode as the tripwire for a re-introduced trap-1 bug.
EXPECTED_TYPE = "customTable"


class DecodeError(Exception):
    """Raised when an audit row cannot be decoded faithfully."""


def strip_s_prefix(value: str, *, what: str) -> str:
    """TRAP 1. Remove the single literal 's'. Fails on a missing prefix.

    Mirrors `decodeStringWithSPrefix`, which returns Left on both an empty string
    and a wrong first character.
    """
    if not isinstance(value, str) or not value:
        raise DecodeError(f"{what}: expected a non-empty S-prefixed string, got {value!r}")
    if value[0] != "s":
        raise DecodeError(
            f"{what}: no 's' prefix on {value[:24]!r}. Either the column is not "
            "S-prefix encoded, or the row predates that encoding."
        )
    return value[1:]


def decode_dashboard(value: Any) -> str | None:
    """TRAP 2. `MongoIdUtf8NoO` -> the o-prefixed id the API wants."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise DecodeError(f"dashboard: expected a string, got {type(value).__name__}")
    if value.startswith("\\x"):
        try:
            text = bytes.fromhex(value[2:]).decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise DecodeError(f"dashboard: could not hex-decode {value[:24]!r}: {exc}") from exc
    else:
        text = value
    body = text[1:] if text.startswith("o") else text
    if len(body) != 24 or any(c not in "0123456789abcdefABCDEF" for c in body):
        raise DecodeError(
            f"dashboard: decoded to {text!r}, which is not a mongo object id. "
            "Posting this would name an unresolvable parent and make the widget "
            "unwritable."
        )
    return "o" + body.lower()


def _as_list(column: Any, *, what: str) -> list:
    """Audit columns arrive as JSON text; accept a parsed list too."""
    if isinstance(column, list):
        return column
    if isinstance(column, str):
        try:
            parsed = json.loads(column)
        except json.JSONDecodeError as exc:
            raise DecodeError(f"{what}: not valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise DecodeError(f"{what}: expected a JSON array, got {type(parsed).__name__}")
        return parsed
    if column is None:
        return []
    raise DecodeError(f"{what}: expected JSON text or a list, got {type(column).__name__}")


def decode_cells(column: Any) -> list[dict]:
    """Decode the cells column into live-shape cell objects."""
    out = []
    for i, pc in enumerate(_as_list(column, what="cells")):
        if not isinstance(pc, dict):
            raise DecodeError(f"cells[{i}]: expected an object, got {type(pc).__name__}")
        cell: dict[str, Any] = {}
        for pg_key, live_key in CELL_KEY_MAP.items():
            value = pc.get(pg_key)
            if pg_key == "desc" and value is not None:
                value = strip_s_prefix(value, what=f"cells[{i}].desc")  # TRAP 1
            cell[live_key] = value
        for key in DROPPED_CELL_FIELDS:  # TRAP 3
            cell[key] = None
        out.append(cell)
    return out


def decode_audit_row(row: dict) -> dict:
    """Decode one audit row into the widget shape `POST /content/ctable/json` takes.

    `row` carries the audit columns as returned by the database: `title`,
    `headers`, `cells`, `type`, `zoom`, `dashboard`, and the sorting columns.
    """
    for required in ("headers", "cells"):
        if required not in row:
            raise DecodeError(f"audit row is missing the {required!r} column")

    headers = [
        strip_s_prefix(h, what=f"headers[{i}]")  # TRAP 1
        for i, h in enumerate(_as_list(row.get("headers"), what="headers"))
    ]

    # TRAP 1, the other half: `title` and `type` are stored RAW. Do NOT strip.
    title = row.get("title") or ""
    widget_type = row.get("type")
    if widget_type is not None and widget_type != EXPECTED_TYPE:
        raise DecodeError(
            f"type decoded to {widget_type!r}, expected null or {EXPECTED_TYPE!r}. "
            "A value like 'ustomTable' means an S-prefix strip was wrongly applied "
            "to a raw-stored column."
        )

    return {
        "customTableWidgetTitle": title,
        "customTableWidgetHeaders": headers,
        "customTableWidgetCells": decode_cells(row.get("cells")),
        "customTableWidgetType": widget_type,
        "customTableWidgetZoomLevel": row.get("zoom"),
        "customTableWidgetDashboard": decode_dashboard(row.get("dashboard")),  # TRAP 2
        # TRAP 4: always null, whatever the row stored.
        "customTableSortingInformation": None,
        "customTablePreferredSortingInformation": None,
    }


def widget_summary(widget: dict) -> dict:
    """Row/column/cell counts and the row-index span, for operator output."""
    cells = widget.get("customTableWidgetCells") or []
    rows = sorted({c.get("cellDataRow") for c in cells if c.get("cellDataRow") is not None})
    return {
        "rows": len(rows),
        "max_row_index": rows[-1] if rows else None,
        "row_gaps": [r for r in range(rows[-1] + 1) if r not in set(rows)] if rows else [],
        "columns": len(widget.get("customTableWidgetHeaders") or []),
        "cells": len(cells),
        "dashboard": widget.get("customTableWidgetDashboard"),
        "type": widget.get("customTableWidgetType"),
    }


def compare_key_sets(widget: dict, live: dict) -> list[str]:
    """Report key-set differences against a live widget. Empty means parity.

    The regression guard for the decoder: a live `GET /content/ctable/json`
    response is the authority on what keys must be present, and a missing cell key
    is silently dropped data rather than an error at post time.
    """
    problems = []
    want_top, got_top = set(live), set(widget)
    for k in sorted(want_top - got_top):
        problems.append(f"missing top-level key: {k}")
    for k in sorted(got_top - want_top):
        problems.append(f"unexpected top-level key: {k}")

    live_cells = live.get("customTableWidgetCells") or []
    got_cells = widget.get("customTableWidgetCells") or []
    if live_cells and got_cells:
        want_cell, got_cell = set(live_cells[0]), set(got_cells[0])
        for k in sorted(want_cell - got_cell):
            problems.append(f"missing cell key: {k}")
        for k in sorted(got_cell - want_cell):
            problems.append(f"unexpected cell key: {k}")
    return problems


def cell_tuples(widget: dict) -> list[tuple]:
    """Comparable identity of every cell, for readback verification."""
    return sorted(
        (
            c.get("cellDataRow"),
            c.get("cellDataCol"),
            c.get("cellDataPid"),
            c.get("cellDataVpid"),
            c.get("cellDataDesc"),
        )
        for c in widget.get("customTableWidgetCells") or []
    )
