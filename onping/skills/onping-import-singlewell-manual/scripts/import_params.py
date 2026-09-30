# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "openpyxl"]
# ///
"""Upload (round-trip) a singlewell-manual parameter spreadsheet to OnPing.

Unlike the mqtt-json import, this endpoint can BOTH author new parameters and
update existing ones. `POST /v2/singlewellmanual/import/params` is a multipart
form that reconciles the location's manual parameter set from the sheet:

  - a row with a BLANK `Pid` cell CREATES a new parameter (server assigns the Pid);
  - a row with a populated `Pid` UPDATES that existing parameter.

The server drops blank-Pid rows from its coverage comparison (`mapMaybe manPid`),
so the precondition is only that every EXISTING Pid still appears in the sheet
(`oldPids == newPids` over populated rows). Omitting an existing Pid is a hard
error — the import CANNOT delete. So the safe workflow is:

    export current (onping-export-singlewell-manual)
      -> edit rows and/or append blank-Pid rows
      -> re-upload here

MUTATES live OnPing state only with --yes. Without --yes (or with --dry-run) the
skill validates the file against the live location and prints a preview, never
POSTing.

Source of truth (re-verify if these drift):
  - Handler:  onping/Handler/SingleWellManual/ImportExportV2.hs
              (postImportManualParametersV2R); checkPids :129; parser :163/:203
  - Route:    onping/config/routes (ImportManualParametersV2R POST)
  - Types:    SingleWell.Manual.Types (ManualValue, takeBytes)
  - Export:   GET /v2/singlewellmanual/export/params/{loc}/{filename} (read side)
  - Frontend: OnpingFetch/OnpingFetch_ImportParameters.res
              (multipart field names f1 = file, f2 = location int)
"""

from __future__ import annotations

import argparse
import io
import os
import sys

import requests

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - uv installs the dep
    print("openpyxl is required (declared in the uv script header)", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 60

IMPORT_PATH = "/v2/singlewellmanual/import/params"
EXPORT_PATH = "/v2/singlewellmanual/export/params/{loc}/{filename}"

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# The 5 columns, in order, per ImportExportV2.hs (pidCol=1 .. valCol=5). Row 1 is
# a "Parameters" title, row 2 holds these headers, data starts at row 3.
EXPECTED_HEADERS = ["Pid", "Parameter ID", "Description", "Type", "Value"]

# The value-type tags read by getTypeTagFromCell, mapped to their byte cap (or
# None for the numeric / NaN tags). ASCII-only applies to Ascii24Tag.
TYPE_BYTE_CAP = {
    "DoubleTag": None,
    "NaNTag": None,
    "Ascii24Tag": 24,
    "Utf8_24Tag": 24,
    "Utf8_40Tag": 40,
    "Utf8_184Tag": 184,
}
VALID_TYPES = set(TYPE_BYTE_CAP)


def _cell_str(value) -> str:
    """Normalize an openpyxl cell value to a trimmed string."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value).strip()


def _is_int(raw: str) -> bool:
    try:
        int(float(raw))
        return True
    except ValueError:
        return False


def _is_number(raw: str) -> bool:
    try:
        float(raw)
        return True
    except ValueError:
        return False


def _load_rows(xlsx_bytes: bytes) -> tuple[list[str], list[list[str]]]:
    """Return (header_row, data_rows) as strings.

    Row 1 is the "Parameters" title, row 2 is the column header, data begins at
    row 3 (matching the handler's `firstParamRow = 3`).
    """
    wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb["Sheet1"] if "Sheet1" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(rows) < 2:
        return [], []
    header = [_cell_str(c) for c in rows[1]][: len(EXPECTED_HEADERS)]
    data = []
    for raw_row in rows[2:]:
        cells = [_cell_str(c) for c in raw_row]
        cells = (cells + [""] * len(EXPECTED_HEADERS))[: len(EXPECTED_HEADERS)]
        if all(c == "" for c in cells):
            continue  # skip fully blank trailing rows
        data.append(cells)
    return header, data


def _validate(header: list[str], data: list[list[str]]) -> list[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    errors: list[str] = []
    if header != EXPECTED_HEADERS:
        errors.append(
            "Header row (sheet row 2) does not match the 5 expected columns.\n"
            f"  expected: {EXPECTED_HEADERS}\n"
            f"  found:    {header}"
        )
        # Header mismatch means column positions are untrustworthy; stop here.
        return errors

    seen_param_ids: dict[str, int] = {}
    for i, row in enumerate(data):
        sheet_row = i + 3  # 1-based; title=1, header=2, data from 3
        pid, param_id, _desc, vtype, val = row

        if pid != "" and not _is_int(pid):
            errors.append(f"row {sheet_row}: Pid '{pid}' is not an integer")

        if param_id == "" or not _is_int(param_id):
            errors.append(
                f"row {sheet_row}: Parameter ID '{param_id}' is not an integer"
            )
        else:
            key = str(int(float(param_id)))
            if key in seen_param_ids:
                errors.append(
                    f"row {sheet_row}: duplicate Parameter ID {key} "
                    f"(first seen at row {seen_param_ids[key]}) — "
                    "each Parameter ID must be unique"
                )
            else:
                seen_param_ids[key] = sheet_row

        if vtype not in VALID_TYPES:
            errors.append(
                f"row {sheet_row}: Type '{vtype}' is not one of "
                f"{sorted(VALID_TYPES)}"
            )
            continue

        # Value validation depends on the type tag.
        if vtype == "DoubleTag":
            if not _is_number(val):
                errors.append(
                    f"row {sheet_row}: DoubleTag Value '{val}' is not numeric"
                )
        elif vtype == "NaNTag":
            pass  # Value cell is ignored server-side.
        else:  # the string tags
            cap = TYPE_BYTE_CAP[vtype]
            if vtype == "Ascii24Tag" and not val.isascii():
                errors.append(
                    f"row {sheet_row}: Ascii24Tag Value '{val}' contains "
                    "non-ASCII characters"
                )
            nbytes = len(val.encode("utf-8"))
            if cap is not None and nbytes > cap:
                # The server silently truncates (takeBytes); warn, don't block.
                errors.append(
                    f"row {sheet_row}: WARNING {vtype} Value is {nbytes} bytes "
                    f"(> {cap}); the server will truncate it to {cap} bytes"
                )
    return errors


def _sheet_pids(data: list[list[str]]) -> set[int]:
    pids: set[int] = set()
    for row in data:
        pid = row[0]
        if pid != "" and _is_int(pid):
            pids.add(int(float(pid)))
    return pids


def _fetch_existing_pids(token: str, loc: int) -> set[int]:
    """Fetch the location's current params via the V2 export route; return Pids.

    Uses the exact same 5-column XLSX projection the server round-trips, so the
    local coverage check matches the server's `oldPids == newPids`.
    """
    url = BASE_URL + EXPORT_PATH.format(loc=loc, filename="current.xlsx")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(
            url, headers=headers, allow_redirects=True, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        print(f"Failed to fetch existing params: {e}", file=sys.stderr)
        sys.exit(1)

    if not (200 <= resp.status_code < 300):
        print(
            f"HTTP {resp.status_code} fetching existing params from {url}\n"
            f"{resp.text[:500]}",
            file=sys.stderr,
        )
        sys.exit(1)

    body = resp.content
    if body.lstrip()[:5].lower() in (b"<!doc", b"<html"):
        print(
            "Expected XLSX when fetching existing params but got HTML — "
            "the access token may be expired.",
            file=sys.stderr,
        )
        sys.exit(1)

    _header, data = _load_rows(body)
    return _sheet_pids(data)


def _upload(token: str, loc: int, path: str, xlsx_bytes: bytes) -> None:
    url = BASE_URL + IMPORT_PATH
    headers = {"Authorization": f"Bearer {token}"}
    # The handler uses `runFormPostNoToken $ renderDivs $ (,) <$> fileAFormReq
    # "File" <*> areq intField "Location"`. Those strings are LABELS; Yesod's
    # renderDivs auto-generates the actual field NAMES `f1`, `f2` in field
    # order. The frontend (OnpingFetch_ImportParameters.res) posts exactly
    # `f1` = file blob, `f2` = location int. Sending "File"/"Location" yields a
    # 400 "FormFailure". Field order: file first, then location.
    files = {"f1": (os.path.basename(path), xlsx_bytes, XLSX_CONTENT_TYPE)}
    data = {"f2": str(loc)}
    try:
        resp = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        print(f"Upload request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if 200 <= resp.status_code < 300:
        # The handler returns 204 with a success message on success.
        print(f"OK — imported spreadsheet for location {loc} (HTTP {resp.status_code}).")
        body = resp.text.strip()
        if body:
            print(body[:500])
        print(
            "Re-export (onping-export-singlewell-manual) to see any "
            "server-assigned Pids for newly created rows."
        )
        return

    # Surface the server error verbatim (e.g. the missing-Pid / duplicate message).
    print(f"HTTP {resp.status_code} from {url}", file=sys.stderr)
    print(resp.text[:1000], file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Upload/round-trip a singlewell-manual parameter spreadsheet "
        "to OnPing (create and/or update). MUTATING — requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("location_id", type=int, help="location refId (LocationIdRef)")
    p.add_argument("spreadsheet", help="path to the .xlsx to upload")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + preview only; never POST (wins over --yes)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="perform the upload (POST). Without it, preview only.",
    )
    args = p.parse_args()

    if not os.path.exists(args.spreadsheet):
        print(f"File not found: {args.spreadsheet}", file=sys.stderr)
        sys.exit(1)

    with open(args.spreadsheet, "rb") as f:
        xlsx_bytes = f.read()

    header, data = _load_rows(xlsx_bytes)

    # 1. Format validation (columns, type tags, numeric/ASCII/byte-cap, dup altId).
    errors = _validate(header, data)
    # Byte-cap WARNINGs don't block the upload; everything else does.
    hard_errors = [e for e in errors if "WARNING" not in e]

    # 2. Classify rows.
    updates = sum(1 for r in data if r[0] != "")
    creates = sum(1 for r in data if r[0] == "")

    # 3. Coverage precondition (mirrors the server's oldPids == newPids).
    existing = _fetch_existing_pids(args.access_token, args.location_id)
    imported = _sheet_pids(data)
    missing = sorted(existing - imported)  # existing Pid dropped -> delete attempt
    unknown = sorted(imported - existing)  # populated Pid that doesn't exist yet

    # ---- Preview ----
    print(f"Location:      {args.location_id}")
    print(f"Spreadsheet:   {os.path.abspath(args.spreadsheet)}")
    print(f"Rows:          {len(data)}  ({updates} updates, {creates} creates)")
    print(f"Existing Pids: {len(existing)}")
    if missing:
        print(f"MISSING Pids:  {missing}  (import cannot delete)")
    if unknown:
        print(f"UNKNOWN Pids:  {unknown}  (populated Pid not on the location)")
    if not missing and not unknown:
        print("Coverage:      OK (existing Pids covered; no unknown Pids)")

    if errors:
        print("\nValidation notes:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)

    # ---- Decide ----
    blocked = bool(hard_errors) or bool(missing) or bool(unknown)

    if args.dry_run or not args.yes:
        if args.dry_run:
            print("\n[dry-run] not uploading.")
        else:
            print("\nPreview only. Re-run with --yes to upload.")
        if blocked:
            print("NOTE: upload is currently BLOCKED (see notes above).", file=sys.stderr)
        return

    # ---- Upload path (--yes) ----
    if blocked:
        if missing:
            print(
                "\nRefusing to upload: the spreadsheet is missing existing Pids "
                f"{missing}. The import cannot delete parameters — start from a "
                "fresh export (onping-export-singlewell-manual) so every current "
                "parameter is present.",
                file=sys.stderr,
            )
        if unknown:
            print(
                "\nRefusing to upload: rows carry Pids that do not exist on the "
                f"location {unknown}. Leave the Pid blank to create a new "
                "parameter, or fix the Pid.",
                file=sys.stderr,
            )
        if hard_errors:
            print(
                "\nRefusing to upload: fix the validation errors above first.",
                file=sys.stderr,
            )
        sys.exit(1)

    _upload(args.access_token, args.location_id, args.spreadsheet, xlsx_bytes)


if __name__ == "__main__":
    main()
