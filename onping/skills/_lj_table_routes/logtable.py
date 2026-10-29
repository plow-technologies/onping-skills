"""Log-table (`/logtable/...`) reads, pure schema transforms, and verified writes.

A `LogTableSource` (onping-logtable-types) is:

    {logTableSourceId, logTableSourceName, logTableSourceLJSerial, logTableSourceGroupId,
     logTableSourceSchemaVersion, logTableSourceSchemas: [LogSchema],
     logTableSourceDeleted, logTableSourceRequiresRestore}

    LogSchema = {logSchemaVersion,
                 logSchemaHeader: {schemaHeaderEventSource: <PID int>,
                                   schemaHeaderColumns: {uuid: {columnSchemaId, columnSchemaKey,
                                                                columnSchemaName, columnSchemaSelector}},
                                   schemaHeaderColumnsPosition: {"<int>": uuid},
                                   schemaHeaderColumnsOrder, schemaHeaderHiddenColumns,
                                   schemaHeaderFilters},
                 logSchemaPagination | null, logSchemaFrozenRows, logSchemaFrozenColumn | null,
                 logSchemaDimensions}

Each column carries its PID as `columnSchemaKey` (a bare int, or
`{"keyType": "VPID", "keyValue": n}`). `schemaHeaderEventSource` is the
trigger PID: a row is recorded when it updates. It is a PID, never a VPID.

`schema/upgrade` is the only column-edit route. It requires version = stored
+ 1, stores the SENT record (so the stored name, group, deleted, and
requiresRestore are copied here), and starts a new, EMPTY table for the new
version. Schemas are listed newest first: always select by logSchemaVersion.
"""

from __future__ import annotations

import copy
import datetime as dt
import uuid as _uuid
from typing import Any, Callable

from . import filters as _filters
from .lj_http import LJTableError, get_json, post_json
from .pointers import (
    EVENT_SELECTOR,
    INVALID_SELECTOR,
    LOGTABLE_SELECTORS,
    TEXT_SELECTOR,
    Pointer,
    parse_key,
    render_key,
)

NIL_UUID = "00000000-0000-0000-0000-000000000000"
EVENT_ORDER = "ColumnOrderLexicographicDESC"
_STORED_FIELDS = ("logTableSourceName", "logTableSourceGroupId", "logTableSourceLJSerial",
                  "logTableSourceDeleted", "logTableSourceRequiresRestore")


# --------------------------------------------------------------------- reads

def list_sources(token: str, lj: Any = None) -> list[dict]:
    """Sources on one LJ (any version), or (lj=None) every LJ (version > 0 only)."""
    if lj is None:
        data = get_json(token, "logtable_all")
    else:
        data = get_json(token, "logtable_list", lj=lj)
    if not isinstance(data, list):
        raise LJTableError(f"Expected a JSON array of LogTableSource, got {type(data).__name__}")
    return [s for s in data if isinstance(s, dict) and not s.get("logTableSourceDeleted")]


def find_source(token: str, lj: Any, table_id: str) -> dict:
    want = table_id.lower()
    sources = list_sources(token, lj)
    for s in sources:
        if str(s.get("logTableSourceId", "")).lower() == want:
            return s
    raise LJTableError(
        f"No log table {table_id} on LJ {lj} ({len(sources)} source(s) listed). "
        "Find it with onping-logtable-list."
    )


def versions(src: dict) -> list[int]:
    return sorted(s.get("logSchemaVersion") for s in src.get("logTableSourceSchemas") or [])


def schema(src: dict, version: int | None = None) -> dict:
    """The schema for `version` (default: the source's current version), by logSchemaVersion."""
    v = src.get("logTableSourceSchemaVersion") if version is None else version
    for s in src.get("logTableSourceSchemas") or []:
        if s.get("logSchemaVersion") == v:
            return s
    if not src.get("logTableSourceSchemas"):
        raise ValueError("this source has no schema yet (version 0); it records nothing "
                         "until a version-1 schema/upgrade")
    raise ValueError(f"no schema version {v}; this source has versions {versions(src)}")


def columns(sch: dict) -> list[dict]:
    """The column grid in position order: position, id, name, key, selector, event, hidden."""
    h = sch.get("logSchemaHeader") or {}
    cols = h.get("schemaHeaderColumns") or {}
    hidden = {str(x).lower() for x in h.get("schemaHeaderHiddenColumns") or []}
    event = h.get("schemaHeaderEventSource")
    out = []
    for pos, cid in sorted((int(p), c) for p, c in (h.get("schemaHeaderColumnsPosition") or {}).items()):
        col = cols.get(cid)
        if col is None:
            continue
        key = parse_key(col.get("columnSchemaKey"))
        sel = col.get("columnSchemaSelector")
        out.append({
            "position": pos, "id": cid, "name": col.get("columnSchemaName"),
            "key": key, "selector": sel, "hidden": cid.lower() in hidden,
            "event": key == Pointer("PID", event) and sel == EVENT_SELECTOR,
        })
    return out


def event_column(sch: dict) -> dict | None:
    return next((c for c in columns(sch) if c["event"]), None)


def resolve_column(sch: dict, ref: str | None = None, pointer: Pointer | None = None) -> dict:
    """Find one column by position, UUID, exact name, or (pointer) its key."""
    cols = columns(sch)
    if pointer is not None:
        hits = [c for c in cols if c["key"] == pointer]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ValueError(f"no column is keyed by {pointer}")
        raise ValueError(f"{len(hits)} columns are keyed by {pointer} (positions "
                         f"{[c['position'] for c in hits]}); pick one with --column")
    if ref is None:
        raise ValueError("give --column or --pid/--vpid to choose a column")
    ref = ref.strip()
    if ref.lstrip("-").isdigit():
        for c in cols:
            if c["position"] == int(ref):
                return c
        raise ValueError(f"no column at position {ref}")
    for c in cols:
        if c["id"].lower() == ref.lower():
            return c
    hits = [c for c in cols if c["name"] == ref] or \
        [c for c in cols if str(c["name"]).lower() == ref.lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise ValueError(f"column name {ref!r} is ambiguous; use the position or UUID")
    raise ValueError(f"no column matches {ref!r} (by position, UUID, or name)")


# ---------------------------------------------------------- validation

def validate_schema(sch: dict) -> list[str]:
    """Mirror the server's isValidSchema, plus the consistency the UI assumes."""
    errors = []
    h = sch.get("logSchemaHeader") or {}
    cols = h.get("schemaHeaderColumns") or {}
    positions = h.get("schemaHeaderColumnsPosition") or {}
    event = h.get("schemaHeaderEventSource")
    if not isinstance(event, int) or isinstance(event, bool):
        errors.append(f"schemaHeaderEventSource must be a PID integer, got {event!r}")
    elif not any(parse_key(c.get("columnSchemaKey")) == Pointer("PID", event)
                 and c.get("columnSchemaSelector") == EVENT_SELECTOR for c in cols.values()):
        errors.append(f"no column keyed by event PID {event} with {EVENT_SELECTOR}; "
                      "the server rejects this as InvalidLogTableSchemaFormat")
    placed = list(positions.values())
    if len(set(c.lower() for c in placed)) != len(placed):
        errors.append("a column appears at more than one position")
    if set(c.lower() for c in placed) != set(c.lower() for c in cols):
        missing = set(c.lower() for c in cols) - set(c.lower() for c in placed)
        extra = set(c.lower() for c in placed) - set(c.lower() for c in cols)
        errors.append(f"positions and columns disagree (unplaced: {sorted(missing)}, "
                      f"unknown: {sorted(extra)})")
    try:
        nums = sorted(int(p) for p in positions)
    except ValueError:
        nums = []
        errors.append("a position key is not an integer")
    if nums and nums != list(range(len(nums))):
        errors.append(f"positions must run 0..{len(nums) - 1} without gaps, got {nums}")
    for cid, c in cols.items():
        if c.get("columnSchemaId", cid).lower() != cid.lower():
            errors.append(f"column {cid} carries columnSchemaId {c.get('columnSchemaId')}")
        sel = c.get("columnSchemaSelector")
        if sel in (TEXT_SELECTOR, INVALID_SELECTOR) or sel not in LOGTABLE_SELECTORS:
            errors.append(f"column {c.get('columnSchemaName')!r}: selector {sel} is not "
                          "allowed in a log table")
        try:
            parse_key(c.get("columnSchemaKey"))
        except ValueError as e:
            errors.append(f"column {c.get('columnSchemaName')!r}: {e}")
    return errors


# ---------------------------------------------------------- pure transforms

def _repack(h: dict) -> None:
    ordered = [c for _, c in sorted((int(p), c) for p, c in (h.get("schemaHeaderColumnsPosition") or {}).items())]
    h["schemaHeaderColumnsPosition"] = {str(i): c for i, c in enumerate(ordered)}


def next_version(stored: dict, mutate: Callable[[dict], Any]) -> tuple[dict, dict, Any]:
    """Build the schema/upgrade body for one edit.

    Deep-copies the current schema, applies `mutate(schema)` in place,
    re-packs positions 0..n-1, and sets version v+1. The body copies the
    stored record (name, group, deleted, requiresRestore) and lists the new
    schema first. Column UUIDs the edit did not touch are kept.

    Returns (body, new schema, whatever `mutate` returned).
    """
    v = stored.get("logTableSourceSchemaVersion")
    if not isinstance(v, int):
        raise ValueError(f"logTableSourceSchemaVersion is {v!r}, not an integer")
    new = copy.deepcopy(schema(stored))
    result = mutate(new)
    _repack(new["logSchemaHeader"])
    new["logSchemaVersion"] = v + 1
    errors = validate_schema(new)
    if errors:
        raise ValueError("the edited schema is invalid:\n  - " + "\n  - ".join(errors))
    body = copy.deepcopy(stored)
    body["logTableSourceSchemaVersion"] = v + 1
    body["logTableSourceSchemas"] = [new] + copy.deepcopy(stored.get("logTableSourceSchemas") or [])
    return body, new, result


def add_column(sch: dict, pointer: Pointer, name: str, selector: str = "ResultTagSelector",
               at: int | None = None) -> str:
    """Mutator: add a column keyed by `pointer`. Returns the new column UUID."""
    if not name.strip():
        raise ValueError("a column name is required")
    if selector not in LOGTABLE_SELECTORS:
        raise ValueError(f"selector {selector} is not allowed in a log table")
    h = sch["logSchemaHeader"]
    if any(c["name"] == name for c in columns(sch)):
        raise ValueError(f"a column named {name!r} already exists")
    if any(c["key"] == pointer and c["selector"] == selector for c in columns(sch)):
        raise ValueError(f"a {selector} column keyed by {pointer} already exists")
    _repack(h)
    n = len(h["schemaHeaderColumnsPosition"])
    at = n if at is None else at
    if not 0 <= at <= n:
        raise ValueError(f"--at must be between 0 and {n}")
    cid = str(_uuid.uuid4())
    h["schemaHeaderColumns"][cid] = {"columnSchemaId": cid, "columnSchemaKey": render_key(pointer),
                                     "columnSchemaName": name, "columnSchemaSelector": selector}
    ordered = [c for _, c in sorted((int(p), c) for p, c in h["schemaHeaderColumnsPosition"].items())]
    ordered.insert(at, cid)
    h["schemaHeaderColumnsPosition"] = {str(i): c for i, c in enumerate(ordered)}
    return cid


def delete_column(sch: dict, column_id: str, *, drop_filters: bool = False) -> None:
    """Mutator: remove a column from every place the schema names it. Refuses the event column."""
    h = sch["logSchemaHeader"]
    key = next((k for k in h.get("schemaHeaderColumns") or {} if k.lower() == column_id.lower()), None)
    if key is None:
        raise ValueError(f"no column {column_id}")
    col = next(c for c in columns(sch) if c["id"] == key)
    if col["event"]:
        raise ValueError("this is the event (trigger) column; a log table must keep one. "
                         "Move the trigger with onping-logtable-column-set first")
    refs = _filters.rules_referencing(h.get("schemaHeaderFilters") or [], key)
    if refs and not drop_filters:
        raise ValueError(f"{len(refs)} stored filter rule(s) reference this column; "
                         "re-run with --drop-filters to remove those references too")
    h["schemaHeaderFilters"] = _filters.drop_column(h.get("schemaHeaderFilters") or [], key)
    del h["schemaHeaderColumns"][key]
    h["schemaHeaderColumnsPosition"] = {p: c for p, c in (h.get("schemaHeaderColumnsPosition") or {}).items()
                                        if c.lower() != key.lower()}
    h["schemaHeaderColumnsOrder"] = {k: v for k, v in (h.get("schemaHeaderColumnsOrder") or {}).items()
                                     if k.lower() != key.lower()}
    h["schemaHeaderHiddenColumns"] = [c for c in h.get("schemaHeaderHiddenColumns") or []
                                      if c.lower() != key.lower()]
    dims = sch.get("logSchemaDimensions")
    if isinstance(dims, dict) and isinstance(dims.get("tableDimensionsCustomColumns"), dict):
        dims["tableDimensionsCustomColumns"] = {k: v for k, v in dims["tableDimensionsCustomColumns"].items()
                                                if k.lower() != key.lower()}
    if str(sch.get("logSchemaFrozenColumn") or "").lower() == key.lower():
        sch["logSchemaFrozenColumn"] = None


def set_column(sch: dict, column_id: str, *, pointer: Pointer | None = None,
               selector: str | None = None, name: str | None = None) -> list[str]:
    """Mutator: change a column's key, selector, and/or name; its UUID is kept.

    Changing the event column's key moves `schemaHeaderEventSource` with it
    (the trigger must be a PID). Returns a list of human notes.
    """
    h = sch["logSchemaHeader"]
    key = next((k for k in h.get("schemaHeaderColumns") or {} if k.lower() == column_id.lower()), None)
    if key is None:
        raise ValueError(f"no column {column_id}")
    is_event = next(c for c in columns(sch) if c["id"] == key)["event"]
    col = h["schemaHeaderColumns"][key]
    notes = []
    if pointer is None and selector is None and name is None:
        raise ValueError("nothing to change: give --pid/--vpid, --selector, and/or --name")
    if selector is not None:
        if selector not in LOGTABLE_SELECTORS:
            raise ValueError(f"selector {selector} is not allowed in a log table")
        if is_event and selector != EVENT_SELECTOR:
            raise ValueError("the event column must keep LastUpdateDateTime; add a new event "
                             "column and move the trigger instead")
        col["columnSchemaSelector"] = selector
    if name is not None:
        if not name.strip():
            raise ValueError("the column name cannot be empty")
        if any(c["name"] == name and c["id"] != key for c in columns(sch)):
            raise ValueError(f"another column is already named {name!r}")
        col["columnSchemaName"] = name
    if pointer is not None:
        if is_event:
            if pointer.kind != "PID":
                raise ValueError("the event (trigger) source must be a PID, not a VPID")
            h["schemaHeaderEventSource"] = pointer.value
            notes.append(f"the trigger moves to PID {pointer.value} (schemaHeaderEventSource)")
        col["columnSchemaKey"] = render_key(pointer)
    return notes


def empty_schema(event_pid: int, event_name: str = "eventDateTime", version: int = 1) -> tuple[dict, str]:
    """The frontend's empty schema, with its event column keyed by `event_pid`."""
    cid = str(_uuid.uuid4())
    return {
        "logSchemaVersion": version,
        "logSchemaHeader": {
            "schemaHeaderEventSource": event_pid,
            "schemaHeaderColumns": {cid: {"columnSchemaId": cid, "columnSchemaKey": event_pid,
                                          "columnSchemaName": event_name,
                                          "columnSchemaSelector": EVENT_SELECTOR}},
            "schemaHeaderColumnsPosition": {"0": cid},
            "schemaHeaderColumnsOrder": {cid: EVENT_ORDER},
            "schemaHeaderHiddenColumns": [],
            "schemaHeaderFilters": [],
        },
        "logSchemaPagination": {"tablePaginationLimit": 25, "tablePaginationOffset": 0},
        "logSchemaFrozenRows": [],
        "logSchemaFrozenColumn": None,
        "logSchemaDimensions": {
            "tableDimensionsCellWidth": 0, "tableDimensionsCellHeight": 0,
            "tableDimensionsHeaderXPadding": 0, "tableDimensionsHeaderYPadding": 0,
            "tableDimensionsCellXPadding": 0, "tableDimensionsCellYPadding": 0,
            "tableDimensionsCustomColumns": {},
        },
    }, cid


def create_body(lj: int, name: str, group: str) -> dict:
    return {
        "logTableSourceId": NIL_UUID, "logTableSourceName": name,
        "logTableSourceLJSerial": lj, "logTableSourceGroupId": group,
        "logTableSourceSchemaVersion": 0, "logTableSourceSchemas": [],
        "logTableSourceDeleted": False, "logTableSourceRequiresRestore": False,
    }


def first_version_body(created: dict, new_schema: dict) -> dict:
    body = copy.deepcopy(created)
    body["logTableSourceSchemaVersion"] = new_schema["logSchemaVersion"]
    body["logTableSourceSchemas"] = [new_schema] + list(created.get("logTableSourceSchemas") or [])
    return body


# ------------------------------------------------------------ verified writes

def post_upgrade(token: str, body: dict) -> Any:
    return post_json(token, "logtable_upgrade", body, lj=body["logTableSourceLJSerial"])


def upgrade_mismatches(body: dict, actual: dict) -> list[str]:
    """Compare a re-listed source with the body that was sent."""
    problems = []
    for f in _STORED_FIELDS + ("logTableSourceSchemaVersion",):
        if body.get(f) != actual.get(f):
            problems.append(f"{f}: sent {body.get(f)!r}, read back {actual.get(f)!r}")
    try:
        want, got = schema(body), schema(actual)
    except ValueError as e:
        return problems + [str(e)]
    wh, gh = want["logSchemaHeader"], got["logSchemaHeader"]
    if wh.get("schemaHeaderEventSource") != gh.get("schemaHeaderEventSource"):
        problems.append(f"event source: sent {wh.get('schemaHeaderEventSource')}, "
                        f"read back {gh.get('schemaHeaderEventSource')}")
    wc = [(c["id"].lower(), c["name"], c["key"], c["selector"]) for c in columns(want)]
    gc = [(c["id"].lower(), c["name"], c["key"], c["selector"]) for c in columns(got)]
    if wc != gc:
        problems.append("columns differ (id, name, key, selector, position order):\n"
                        f"    sent      {[(c[1], str(c[2]), c[3]) for c in wc]}\n"
                        f"    read back {[(c[1], str(c[2]), c[3]) for c in gc]}")
    if versions(actual) != versions(body):
        problems.append(f"schema versions: sent {versions(body)}, read back {versions(actual)}")
    return problems


def _minute(ts: str, *, shift: int) -> str:
    """Normalise a UTC time to "YYYY-MM-DD HH:MM", shifted by `shift` minutes."""
    text = ts.strip().replace("T", " ").removesuffix("Z")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            t = dt.datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"cannot read {ts!r} as a UTC time; use YYYY-MM-DD[ HH:MM[:SS]]")
    return (t.replace(second=0) + dt.timedelta(minutes=shift)).strftime("%Y-%m-%d %H:%M")


def _datetime_filter(column_id: str, op: str, value: str) -> dict:
    return {"tag": "SingleFilterRule", "contents": {
        "singleFilterColumnRef": column_id,
        "singleFilterConcatenationOperator": "FilterConcatenationAND",
        "singleFilterOperator": op,
        "singleFilterInputValue": value,
        "singleFilterInputType": "FilterInputTypeDateTime",
    }}


def query_body(src: dict, *, version: int | None = None, limit: int = 10, offset: int = 0,
               since: str | None = None, until: str | None = None) -> tuple[dict, list[dict]]:
    """The content/query/v2 body for one schema version, newest first.

    Clears hidden columns (hidden columns are not projected) and the stored
    filters, orders by the event column descending, and adds minute-precision
    `--since` / `--until` filters on the event column (both inclusive).
    Returns (body, the columns each row's values follow).
    """
    sch = copy.deepcopy(schema(src, version))
    ev = event_column(sch)
    if ev is None:
        raise ValueError("schema has no event column")
    h = sch["logSchemaHeader"]
    h["schemaHeaderHiddenColumns"] = []
    h["schemaHeaderColumnsOrder"] = {ev["id"]: EVENT_ORDER}
    rules = []
    if since:
        rules.append(_datetime_filter(ev["id"], "FilterIsAbove", _minute(since, shift=-1)))
    if until:
        rules.append(_datetime_filter(ev["id"], "FilterIsBelow", _minute(until, shift=+1)))
    h["schemaHeaderFilters"] = rules
    sch["logSchemaPagination"] = {"tablePaginationLimit": limit, "tablePaginationOffset": offset}
    body = copy.deepcopy(src)
    body["logTableSourceSchemaVersion"] = sch["logSchemaVersion"]
    body["logTableSourceSchemas"] = [sch]
    projected = [c for c in columns(sch) if c["selector"] not in (TEXT_SELECTOR, INVALID_SELECTOR)]
    return body, projected


def query_rows(token: str, src: dict, **kw: Any) -> tuple[list[dict], int, list[dict]]:
    body, cols = query_body(src, **kw)
    resp = post_json(token, "logtable_query", body, lj=src["logTableSourceLJSerial"])
    if not isinstance(resp, dict):
        raise LJTableError(f"Expected a QueryResponse object, got {type(resp).__name__}")
    names = [c["name"] for c in cols]
    labels = [n if names.count(n) == 1 else f"{n}@{c['position']}" for n, c in zip(names, cols)]
    rows = []
    for r in resp.get("queryResponseContent") or []:
        vals = r.get("tableRowValues") or []
        if len(vals) != len(cols):
            raise LJTableError(f"row {r.get('tableRowId')} has {len(vals)} values for "
                               f"{len(cols)} columns; the projection changed under us")
        rows.append({"rowId": r.get("tableRowId"), "values": dict(zip(labels, vals))})
    return rows, int(resp.get("queryResponseCount") or 0), cols
