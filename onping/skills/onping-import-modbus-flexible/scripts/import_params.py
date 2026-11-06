# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "openpyxl"]
# ///
"""Import an edited modbus-flexible tag spreadsheet into one OnPing location.

The write counterpart of onping-export-modbus-flexible. The server route is
`POST /modbus/flexible/import/params`, a multipart form with `f1` = the XLSX
and `f2` = the location refId.

The server first refuses the import with HTTP 403 unless the caller owns one
of the location's groups (this script does not check ownership). It then
requires that the sheet's populated PIDs are exactly the location's current
PIDs, discards the PID column and rebuilds every tag from the Index column,
so a tag's identity is its Index:

  - update:      a row whose Index is a current tag's Index, carrying that PID;
  - create:      a blank-PID row with a new Index (the server assigns a PID);
  - PID change:  a populated row whose Index is not its PID's current Index;
                 its PID leaves the location and the row lands on another PID.

This script reproduces the server's parse rules and checks locally, refuses
the sheets the server would accept wrongly (duplicate Index, duplicate PID,
blank PID on a current Index), previews the plan, and with --yes uploads and
reads the result back by re-export. Any failure, including a read-back
mismatch, exits 1.

Source of truth (server modules; re-read if behaviour drifts):
  - Handler.ModbusFlexible.ImportExport  (postImportModbusFlexibleParametersR,
                                          checkPids, the column parsers)
  - Handler.Xlsx.Sheet / Handler.Xlsx.Cell (blank-cell filter, row count,
                                          cell type rules)
  - Handler.ModbusFlexible.Service       (convertToExtendedConfig,
                                          updateModbusFlexibleLocationParameters)
  - SingleWell.Modbus.Flexible.AvailableIndexing (ModbusFlexibleIndex families)
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import os
import sys
from dataclasses import dataclass, field

import requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _token_input import shapes, token_source  # noqa: E402

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - uv installs the dep
    print("openpyxl is required (declared in the uv script header)", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 60

IMPORT_PATH = "/modbus/flexible/import/params"
EXPORT_PATH = "/modbus/flexible/export/params/{loc}/{filename}"

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

SHEET_NAME = "Sheet1"
HEADER_ROW = 2
FIRST_DATA_ROW = 3
HEADERS = [
    "PID",
    "Index",
    "Description",
    "Read/Write",
    "Data Type",
    "On Change",
    "Local Only",
]

INDEX_FAMILIES = frozenset(
    {
        "SpiritIndex",
        "IdecIndex",
        "IdecMicroSmartIndex",
        "FergusonIndex",
        "AutoPilotIndex",
        "SCADAPackIndex",
        "AMIAnalyzerIndex",
        "HarrierPlusIndex",
        "MicrologixModbusIndex",
        "TotalFlowModbusIndex",
        "Scanner2000Index",
        "GePLCIndex",
        "EpicLiftSystemsIndex",
        "ProstarPWMV2Index",
        "RocModbusIndex",
        "ControlWaveIndex",
        "NovusDigiRailIndex",
        "AIDNP5AIndex",
        "Rosemount1000Index",
        "Rosemount8700Index",
        "ADAM4055Index",
        "ADAM4117Index",
        "FrenicIndex",
        "SiemensS7Index",
    }
)
# Stored by the server in the legacy IdecIndex form, so a read-back cannot be
# matched to the row by Index. Refused; add such tags in the OnPing web page.
REFUSED_FAMILIES = frozenset({"IdecMicroSmartIndex"})

READ_WRITE = {"readonly": "ReadOnly", "readwrite": "ReadWrite"}
DATA_TYPES = {
    name.lower(): name
    for name in (
        "Word8",
        "Word16",
        "Word32",
        "Word64",
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "Float",
        "Float16",
        "Double",
        "Text",
        "Undefined",
    )
}

EXIT_OK = 0
EXIT_FAIL = 1


class CellError(ValueError):
    pass


class Abort(Exception):
    """A failure already reported on stderr; main() turns it into exit 1."""


# ---------------------------------------------------------------- sheet model


@dataclass
class Row:
    sheet_row: int
    pid: int | None
    index: object
    index_key: str
    family: str
    description: str
    description_numeric: bool
    read_write: str
    data_type: str | None
    on_change: float | None
    local_only: bool


def _is_blank(value) -> bool:
    """The server drops cells whose value is missing, "" or a single space."""
    return value is None or value == "" or value == " "


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize(obj):
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def canonical_index(obj) -> str:
    """Key-sorted, integral-normalized JSON text of an Index value."""
    return json.dumps(_normalize(obj), sort_keys=True, separators=(",", ":"))


def _parse_pid(value) -> int | None:
    if _is_blank(value):
        return None
    if not _is_number(value):
        raise CellError(f"PID must be a number cell, got {value!r}")
    if not float(value).is_integer() or value <= 0:
        raise CellError(f"PID must be a positive whole number, got {value!r}")
    return int(value)


def _parse_index(value) -> tuple[object, str, str]:
    if _is_blank(value):
        raise CellError("Index is blank")
    if not isinstance(value, str):
        raise CellError(f"Index must be a text cell holding JSON, got {value!r}")
    try:
        obj = json.loads(value)
    except json.JSONDecodeError as e:
        raise CellError(f"Index is not valid JSON ({e.msg})") from None
    if not isinstance(obj, dict) or "tag" not in obj or "contents" not in obj:
        raise CellError('Index must be a JSON object with "tag" and "contents"')
    family = obj["tag"]
    if family not in INDEX_FAMILIES:
        raise CellError(f"Index tag {family!r} is not a modbus-flexible Index family")
    return obj, canonical_index(obj), family


def _parse_description(value) -> tuple[str, bool]:
    if _is_blank(value):
        return "", False
    if isinstance(value, str):
        return value, False
    if _is_number(value):
        f = float(value)
        return (str(int(f)) if f.is_integer() else repr(f)), True
    raise CellError(f"Description must be text or a number, got {value!r}")


def _parse_read_write(value) -> str:
    if _is_blank(value):
        raise CellError("Read/Write is blank")
    if isinstance(value, str) and value.lower() in READ_WRITE:
        return READ_WRITE[value.lower()]
    raise CellError(f"Read/Write must be ReadOnly or ReadWrite, got {value!r}")


def _parse_data_type(value) -> str | None:
    if _is_blank(value):
        return None
    if isinstance(value, str) and value.lower() in DATA_TYPES:
        return DATA_TYPES[value.lower()]
    raise CellError(
        f"Data Type must be one of {sorted(DATA_TYPES.values())}, got {value!r}"
    )


def _parse_on_change(value) -> float | None:
    if _is_blank(value):
        return None
    if _is_number(value):
        return float(value)
    raise CellError(f"On Change must be a number cell, got {value!r}")


def _parse_local_only(value) -> bool:
    if _is_blank(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    if _is_number(value) and value in (0, 1):
        return bool(value)
    raise CellError(f"Local Only must be true or false, got {value!r}")


def parse_sheet(xlsx_bytes: bytes) -> tuple[list[Row], list[str]]:
    """Parse a modbus-flexible sheet the way the server does.

    Returns (rows, errors). Errors carry sheet row numbers.
    """
    try:
        wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - any unreadable file
        return [], [f"cannot read the file as XLSX: {e}"]
    if SHEET_NAME not in wb.sheetnames:
        names = wb.sheetnames
        wb.close()
        return [], [f"no sheet named {SHEET_NAME!r} (found {names}); the server reads only {SHEET_NAME!r}"]
    raw = [list(r) for r in wb[SHEET_NAME].iter_rows(values_only=True)]
    wb.close()

    # Last row with any non-blank cell, in any column (the server's row count).
    last = 0
    for i, cells in enumerate(raw, start=1):
        if any(not _is_blank(c) for c in cells):
            last = i

    header = raw[HEADER_ROW - 1] if len(raw) >= HEADER_ROW else []
    header = [("" if c is None else str(c).strip()) for c in header][: len(HEADERS)]
    header += [""] * (len(HEADERS) - len(header))
    if [h.lower() for h in header] != [h.lower() for h in HEADERS]:
        return [], [
            f"row {HEADER_ROW} must name the columns {HEADERS} in order; found {header}"
        ]

    rows: list[Row] = []
    errors: list[str] = []
    for n in range(FIRST_DATA_ROW, last + 1):
        cells = raw[n - 1] + [None] * len(HEADERS)
        if all(_is_blank(c) for c in cells):
            errors.append(
                f"row {n}: blank row inside the data; the server fails the whole sheet on it"
            )
            continue
        row_errors: list[str] = []

        def take(fn, value, _errs=row_errors):
            try:
                return fn(value)
            except CellError as e:
                _errs.append(str(e))
                return None

        pid = take(_parse_pid, cells[0])
        parsed_index = take(_parse_index, cells[1])
        desc = take(_parse_description, cells[2])
        rw = take(_parse_read_write, cells[3])
        dtype = take(_parse_data_type, cells[4])
        on_change = take(_parse_on_change, cells[5])
        local_only = take(_parse_local_only, cells[6])
        if row_errors:
            errors.extend(f"row {n}: {e}" for e in row_errors)
            continue
        index, key, family = parsed_index
        rows.append(
            Row(
                sheet_row=n,
                pid=pid,
                index=index,
                index_key=key,
                family=family,
                description=desc[0],
                description_numeric=desc[1],
                read_write=rw,
                data_type=dtype,
                on_change=on_change,
                local_only=local_only,
            )
        )
    return rows, errors


# ---------------------------------------------------------------- planning


@dataclass
class Plan:
    updates: list[tuple[Row, Row]] = field(default_factory=list)  # (sheet, current)
    creates: list[Row] = field(default_factory=list)
    replacements: list[tuple[Row, Row | None]] = field(default_factory=list)
    leaving: list[Row] = field(default_factory=list)  # current tags that leave
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def needs_pid_flag(self) -> bool:
        return bool(self.replacements)


FIELDS = ("description", "read_write", "on_change", "local_only")
FIELD_LABELS = {
    "description": "Description",
    "read_write": "Read/Write",
    "on_change": "On Change",
    "local_only": "Local Only",
}


def _same(field_name: str, sent: Row, got: Row) -> bool:
    a, b = getattr(sent, field_name), getattr(got, field_name)
    if field_name == "on_change":
        if a is None or b is None:
            return a is None and b is None
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if field_name == "description" and sent.description_numeric and a != b:
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9)
        except ValueError:
            return False
    return a == b


def field_diffs(sent: Row, got: Row) -> list[str]:
    return [
        f"{FIELD_LABELS[f]} {getattr(got, f)!r} -> {getattr(sent, f)!r}"
        for f in FIELDS
        if not _same(f, sent, got)
    ]


def make_plan(sheet: list[Row], current: list[Row], allow_pid_change: bool) -> Plan:
    plan = Plan()
    current_by_key = {r.index_key: r for r in current}
    current_by_pid = {r.pid: r for r in current if r.pid is not None}
    current_pids = sorted(current_by_pid)

    if not sheet:
        plan.blockers.append("the sheet has no data rows")

    seen_key: dict[str, int] = {}
    seen_pid: dict[int, int] = {}
    for r in sheet:
        if r.index_key in seen_key:
            plan.blockers.append(
                f"row {r.sheet_row}: duplicate Index (same as row {seen_key[r.index_key]}); "
                "the server would keep the upper row and drop this one without an error"
            )
        else:
            seen_key[r.index_key] = r.sheet_row
        if r.pid is not None:
            if r.pid in seen_pid:
                plan.blockers.append(
                    f"row {r.sheet_row}: duplicate PID {r.pid} (same as row {seen_pid[r.pid]})"
                )
            else:
                seen_pid[r.pid] = r.sheet_row
        if r.family in REFUSED_FAMILIES:
            plan.blockers.append(
                f"row {r.sheet_row}: {r.family} rows are not supported; the server stores "
                "them in the IdecIndex form, so the result cannot be read back by Index"
            )

    sheet_pids = sorted(seen_pid)
    missing = sorted(set(current_pids) - set(sheet_pids))
    unknown = sorted(set(sheet_pids) - set(current_pids))
    if missing:
        plan.blockers.append(
            f"current PIDs missing from the sheet: {missing}; the import cannot delete "
            "tags, so start from a fresh export"
        )
    if unknown:
        plan.blockers.append(
            f"PIDs not on the location: {unknown}; leave the PID blank to create a tag"
        )

    for r in sheet:
        cur = current_by_key.get(r.index_key)
        if r.pid is None:
            if cur is None:
                plan.creates.append(r)
            else:
                plan.blockers.append(
                    f"row {r.sheet_row}: blank PID, but its Index belongs to current PID "
                    f"{cur.pid}, so this is not a create; put {cur.pid} in the row to "
                    "update that tag"
                )
            continue
        if r.pid not in current_by_pid:
            continue  # reported as unknown above
        if cur is not None and cur.pid == r.pid:
            plan.updates.append((r, cur))
            if r.data_type and cur.data_type and r.data_type != cur.data_type:
                plan.notes.append(
                    f"row {r.sheet_row} PID {r.pid}: Data Type {r.data_type} will be ignored; "
                    f"the server derives {cur.data_type} from the Index"
                )
        else:
            plan.replacements.append((r, cur))

    sheet_keys = {r.index_key for r in sheet}
    plan.leaving = [c for c in current if c.index_key not in sheet_keys]

    if plan.replacements and not allow_pid_change:
        nums = [str(r.sheet_row) for r, _ in plan.replacements]
        label = "row " + nums[0] if len(nums) == 1 else "rows " + ", ".join(nums)
        plan.blockers.append(
            f"{label} change which PID a tag has; re-run with --allow-pid-change "
            "if that is meant"
        )
    return plan


def print_plan(plan: Plan, loc: int, path: str, n_rows: int, n_current: int) -> None:
    print(f"Location:      {loc}")
    print(f"Spreadsheet:   {os.path.abspath(path)}")
    print(f"Current tags:  {n_current}")
    print(
        f"Sheet rows:    {n_rows}  ({len(plan.updates)} updates, "
        f"{len(plan.creates)} creates, {len(plan.replacements)} PID changes)"
    )
    changed = [(r, c, field_diffs(r, c)) for r, c in plan.updates]
    changed = [x for x in changed if x[2]]
    if changed:
        print("\nField changes:")
        for r, _c, diffs in changed:
            print(f"  row {r.sheet_row} PID {r.pid}: " + "; ".join(diffs))
    if plan.creates:
        print("\nCreates (the server assigns each a PID):")
        for r in plan.creates:
            print(f"  row {r.sheet_row}: {r.index_key}  {r.description!r}")
    if plan.replacements:
        print("\nPID changes:")
        for r, cur in plan.replacements:
            target = f"current PID {cur.pid}" if cur else "a PID assigned by the server"
            print(f"  row {r.sheet_row}: PID {r.pid} -> {target}  ({r.index_key})")
    if plan.leaving:
        print("\nPIDs leaving the location (their history stays on the old PID):")
        for c in plan.leaving:
            print(f"  PID {c.pid}: {c.index_key}")
    if plan.notes:
        print("\nNotes:")
        for n in plan.notes:
            print(f"  - {n}")
    if plan.blockers:
        print("\nBlocked:", file=sys.stderr)
        for b in plan.blockers:
            print(f"  - {b}", file=sys.stderr)


# ---------------------------------------------------------------- HTTP


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _looks_like_auth_page(resp) -> bool:
    if resp.history and ("/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")):
        return True
    return resp.content.lstrip()[:5].lower() in (b"<!doc", b"<html")


def fetch_export(token: str, loc: int) -> bytes:
    url = BASE_URL + EXPORT_PATH.format(loc=loc, filename="current.xlsx")
    try:
        resp = requests.get(
            url, headers=_headers(token), allow_redirects=True, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        print(f"Export request failed: {e}", file=sys.stderr)
        raise Abort()
    if not (200 <= resp.status_code < 300):
        print(f"HTTP {resp.status_code} exporting location {loc}", file=sys.stderr)
        print(resp.text[:1000], file=sys.stderr)
        raise Abort()
    if _looks_like_auth_page(resp):
        print(
            "Expected XLSX from the export but got an HTML page; the access token may be expired.",
            file=sys.stderr,
        )
        raise Abort()
    return resp.content


def read_current(token: str, loc: int, what: str) -> tuple[bytes, list[Row]]:
    body = fetch_export(token, loc)
    rows, errors = parse_sheet(body)
    if errors:
        print(f"Could not read the {what} export of location {loc}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise Abort()
    return body, rows


def upload(token: str, loc: int, path: str, xlsx_bytes: bytes):
    """POST the sheet. Field names are f1 (file) and f2 (location), not the
    handler's "File"/"Location" labels, which the server refuses with
    FormFailure."""
    files = {"f1": (os.path.basename(path), xlsx_bytes, XLSX_CONTENT_TYPE)}
    data = {"f2": str(loc)}
    try:
        return requests.post(
            BASE_URL + IMPORT_PATH,
            headers=_headers(token),
            files=files,
            data=data,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        print(f"Upload request failed: {e}", file=sys.stderr)
        raise Abort()


def _server_text(resp) -> str:
    try:
        body = resp.json()
        return body if isinstance(body, str) else json.dumps(body)
    except ValueError:
        return resp.text[:2000]


# ---------------------------------------------------------------- read-back


def compare(sheet: list[Row], plan: Plan, after: list[Row]) -> tuple[list[str], list[tuple[Row, int]], list[str]]:
    """Return (mismatches, assigned (row, pid), notes)."""
    after_by_key = {r.index_key: r for r in after}
    update_rows = {id(r) for r, _ in plan.updates}
    mismatches: list[str] = []
    assigned: list[tuple[Row, int]] = []
    notes: list[str] = []
    for r in sheet:
        got = after_by_key.get(r.index_key)
        if got is None:
            mismatches.append(f"row {r.sheet_row}: Index not found after import: {r.index_key}")
            continue
        if id(r) in update_rows:
            if got.pid != r.pid:
                mismatches.append(f"row {r.sheet_row}: PID {r.pid} came back as {got.pid}")
        else:
            assigned.append((r, got.pid))
        differing = [f for f in FIELDS if not _same(f, r, got)]
        if differing:
            mismatches.append(
                f"row {r.sheet_row} PID {got.pid}: "
                + "; ".join(
                    f"{FIELD_LABELS[f]} sent {getattr(r, f)!r}, read back {getattr(got, f)!r}"
                    for f in differing
                )
            )
        if r.data_type and got.data_type and r.data_type != got.data_type:
            notes.append(
                f"row {r.sheet_row} PID {got.pid}: Data Type is {got.data_type}, derived by the server"
            )
    sheet_keys = {r.index_key for r in sheet}
    for g in after:
        if g.index_key not in sheet_keys:
            mismatches.append(f"unexpected tag after import: PID {g.pid} {g.index_key}")
    return mismatches, assigned, notes


# ---------------------------------------------------------------- main


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except Abort:
        return EXIT_FAIL


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(
        description="Import an edited modbus-flexible tag spreadsheet into one OnPing "
        "location. Previews by default; writes only with --yes.",
    )
    p.add_argument("location_id", type=shapes.int_arg, help="location refId (LocationIdRef)")
    p.add_argument("spreadsheet", help="path to the edited .xlsx")
    p.add_argument("--yes", action="store_true", help="upload; without it, preview only")
    p.add_argument("--dry-run", action="store_true", help="preview only; wins over --yes")
    p.add_argument(
        "--allow-pid-change",
        action="store_true",
        help="allow rows whose Index change moves a tag to a different PID",
    )
    p.add_argument(
        "--backup",
        metavar="PATH",
        help="where --yes saves the pre-import export "
        "(default ./modbus-flexible-<location>-<UTC>.backup.xlsx)",
    )
    args = token_source.parse(p, argv, is_id=shapes.is_int)

    if not os.path.exists(args.spreadsheet):
        print(f"File not found: {args.spreadsheet}", file=sys.stderr)
        return EXIT_FAIL
    with open(args.spreadsheet, "rb") as f:
        xlsx_bytes = f.read()

    sheet, errors = parse_sheet(xlsx_bytes)
    if errors:
        print("The sheet does not parse the way the server needs:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return EXIT_FAIL

    before_bytes, current = read_current(args.access_token, args.location_id, "current")
    plan = make_plan(sheet, current, args.allow_pid_change)
    print_plan(plan, args.location_id, args.spreadsheet, len(sheet), len(current))

    if args.dry_run or not args.yes:
        print("\n[dry-run] not uploading." if args.dry_run else "\nPreview only. Re-run with --yes to upload.")
        if plan.blockers:
            print("A --yes run would be refused (see Blocked above).", file=sys.stderr)
            return EXIT_FAIL
        return EXIT_OK

    if plan.blockers:
        print("\nRefusing to upload.", file=sys.stderr)
        return EXIT_FAIL

    backup = args.backup or f"./modbus-flexible-{args.location_id}-{_utc_stamp()}.backup.xlsx"
    with open(backup, "wb") as f:
        f.write(before_bytes)
    print(f"\nBackup:        {os.path.abspath(backup)}")

    resp = upload(args.access_token, args.location_id, args.spreadsheet, xlsx_bytes)
    if not (200 <= resp.status_code < 300):
        print(f"HTTP {resp.status_code} from the import; nothing was confirmed written.", file=sys.stderr)
        print(f"Server: {_server_text(resp)}", file=sys.stderr)
        print(f"The pre-import export is at {os.path.abspath(backup)}.", file=sys.stderr)
        return EXIT_FAIL
    if resp.content and _looks_like_auth_page(resp):
        print(
            "The import answered with an HTML page; the access token may be expired. "
            "Re-export to see whether anything changed.",
            file=sys.stderr,
        )
        return EXIT_FAIL
    print(f"Import:        HTTP {resp.status_code}")

    _after_bytes, after = read_current(args.access_token, args.location_id, "post-import")
    mismatches, assigned, notes = compare(sheet, plan, after)
    if assigned:
        print("\nPIDs assigned by the server:")
        for r, pid in assigned:
            print(f"  row {r.sheet_row}: PID {pid}  ({r.index_key})")
    for n in notes:
        print(f"  note: {n}")
    if mismatches:
        print("\nRead-back mismatch:", file=sys.stderr)
        for m in mismatches:
            print(f"  - {m}", file=sys.stderr)
        print(f"The pre-import export is at {os.path.abspath(backup)}.", file=sys.stderr)
        return EXIT_FAIL
    print(f"\nRead-back:     OK ({len(after)} tags match the sheet)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
