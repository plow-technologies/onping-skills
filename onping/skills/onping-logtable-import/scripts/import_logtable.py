# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "openpyxl"]
# ///
"""Upload a multiple-rows-header log-table XLSX to OnPing.

Route: POST /logtable/#LJSerial/source/import/template/multiple-rows-header
Body:  multipart form
         f1 = XLSX bytes
         f2 = target log-table source's TableId (UUID as a text string)

The XLSX has EXACTLY 4 header rows in order:
    row 1: `event`             (column 1 only; other cells blank)
    row 2: `name: <label>`     (every column)
    row 3: `tag: dateTime`     (column 1 — the trigger column)
           `tag: result`       (every other column)
    row 4: `source: <PID>`     (every column; PID must be an integer)

Every row-4 cell must be `source: <integer>`. Non-integer sources — including
`TODO`-style placeholders — are rejected server-side with
`Invalid PID or VPID format for: <value>. input does not start with a digit`
(observed live on a test Lumberjack on 2026-07-10). The pre-flight reproduces this
check locally and blocks the upload rather than paying for a full multipart
round-trip only to see the 400.

The skill requires an existing log-table source; it does NOT create sources.
Source creation belongs to a separate wrapper for
POST /logtable/#LJSerial/source/create.

MUTATES live OnPing state only with --yes. Without --yes (or with --dry-run)
the skill runs local pre-flight validation and prints a preview, never POSTing.
`--dry-run` wins if both are passed.

Source of truth (re-verify if these drift):
  - Handler:    onping/Handler/OnpingLogTable/Service.hs
                (postLogTableSourceImportFromTemplateMultipleRowsHeaderR)
  - Form defn:  onping/Handler/OnpingLogTable/Service.hs
                — `renderDivs $ (,) <$> fileAFormReq "File" <*> areq textField "TableId"`
                — the form comment says: `"File"` / `"TableId"` are LABELS;
                  the actual multipart field NAMES are Yesod's auto-generated
                  `f1` (file) and `f2` (TableId text), in field order.
                  Posting `File`/`TableId` yields `400 FormFailure`.
  - Frontend:   OnpingFetch/OnpingFetch_OnpingLogTable.res
                (`importLogTableSourceFromTemplateMultipleRowsHeader` — builds
                the same multipart body with `mkFileFormData(blob, tableUUID)`)
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import uuid as _uuid
from typing import List, Optional, Tuple

import requests

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - uv installs the dep
    print("openpyxl is required (declared in the uv script header)", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 60

IMPORT_PATH = "/logtable/{serial}/source/import/template/multiple-rows-header"

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

EVENT_MARKER = "event"
NAME_PREFIX = "name:"
TAG_PREFIX = "tag:"
SOURCE_PREFIX = "source:"
TAG_DATETIME = "tag: dateTime"
TAG_RESULT = "tag: result"


def _cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value).strip()


def _load_header_rows(xlsx_bytes: bytes) -> List[List[str]]:
    """Return the first 4 rows as lists of strings.

    The log-table template is defined by rows 1..4; any additional rows are
    ignored by the server-side parser (there's no per-row data in a fresh
    template, only the four header rows).
    """
    wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows: List[List[str]] = []
    for i, raw_row in enumerate(ws.iter_rows(values_only=True)):
        if i >= 4:
            break
        rows.append([_cell_str(c) for c in raw_row])
    wb.close()
    return rows


def _row(rows: List[List[str]], idx: int) -> List[str]:
    return rows[idx] if idx < len(rows) else []


def _trim_trailing_blanks(row: List[str]) -> List[str]:
    end = len(row)
    while end > 0 and row[end - 1] == "":
        end -= 1
    return row[:end]


def _validate(
    rows: List[List[str]],
) -> Tuple[List[str], List[str], int]:
    """Return (errors, warnings, column_count).

    Errors block a `--yes` upload. Warnings do not (e.g. `source: TODO`).
    Column count is the max non-blank column across rows 2..4 (row 1 has
    only column 1 populated, so isn't used for width).
    """
    errors: List[str] = []
    warnings: List[str] = []

    if len(rows) < 4:
        errors.append(
            f"expected at least 4 header rows (event / name: / tag: / source:), "
            f"found {len(rows)}"
        )
        return errors, warnings, 0

    r1 = _row(rows, 0)
    r2 = _trim_trailing_blanks(_row(rows, 1))
    r3 = _trim_trailing_blanks(_row(rows, 2))
    r4 = _trim_trailing_blanks(_row(rows, 3))

    # 1. Row 1 col 1 is exactly the `event` marker.
    if not r1 or r1[0] != EVENT_MARKER:
        errors.append(
            f"row 1 col 1: expected `{EVENT_MARKER}`, found "
            f"`{r1[0] if r1 else ''}`"
        )

    # 2..3. Rows 2, 3, 4 have the same column count.
    widths = [len(r2), len(r3), len(r4)]
    if len(set(widths)) != 1:
        errors.append(
            f"rows 2/3/4 must have the same populated column count; "
            f"found name:{widths[0]}, tag:{widths[1]}, source:{widths[2]}"
        )
    col_count = min(widths) if widths else 0

    if col_count == 0:
        errors.append("no columns found in the header rows")
        return errors, warnings, 0

    # 4. Every row-2 cell starts with `name:`.
    for c, cell in enumerate(r2, start=1):
        if not cell.startswith(NAME_PREFIX):
            errors.append(
                f"row 2 col {c}: expected `name: <label>`, found `{cell}`"
            )

    # 5. Every row-3 cell starts with `tag:`.
    for c, cell in enumerate(r3, start=1):
        if not cell.startswith(TAG_PREFIX):
            errors.append(
                f"row 3 col {c}: expected `tag: dateTime` or `tag: result`, "
                f"found `{cell}`"
            )

    # 6. Row 3 col 1 is `tag: dateTime`; every other row-3 cell is `tag: result`.
    if r3:
        if r3[0] != TAG_DATETIME:
            errors.append(
                f"row 3 col 1: trigger column must be `{TAG_DATETIME}`, "
                f"found `{r3[0]}`"
            )
        for c, cell in enumerate(r3[1:], start=2):
            if cell != TAG_RESULT:
                errors.append(
                    f"row 3 col {c}: non-trigger column must be "
                    f"`{TAG_RESULT}`, found `{cell}`"
                )

    # 7 & 8. Every row-4 cell must be `source: <integer>`. Non-integer values
    # (including `TODO`-style placeholders) are rejected server-side with
    # `Invalid PID or VPID format for: <value>. input does not start with a digit`
    # (observed live on a test Lumberjack on 2026-07-10). Pre-empt the server round-trip.
    seen_pids: dict[int, int] = {}  # pid -> first column
    for c, cell in enumerate(r4, start=1):
        if not cell.startswith(SOURCE_PREFIX):
            errors.append(
                f"row 4 col {c}: expected `source: <integer-PID>`, found `{cell}`"
            )
            continue
        rest = cell[len(SOURCE_PREFIX):].strip()
        try:
            pid = int(rest)
        except ValueError:
            errors.append(
                f"row 4 col {c}: `source:` value `{rest}` is not an integer PID. "
                "Server rejects non-integer sources with "
                "`Invalid PID or VPID format for: <value>. input does not start with a digit`."
            )
            continue
        # 9. Warn on duplicate PIDs (server accepts them, but almost always a bug).
        if pid in seen_pids:
            warnings.append(
                f"row 4 col {c}: duplicate PID {pid} (also at col {seen_pids[pid]})"
            )
        else:
            seen_pids[pid] = c

    return errors, warnings, col_count


def _upload(
    token: str,
    serial: str,
    table_uuid: str,
    xlsx_path: str,
    xlsx_bytes: bytes,
) -> None:
    url = BASE_URL + IMPORT_PATH.format(serial=serial)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    # The handler at Service.hs defines the form as
    #   renderDivs $ (,) <$> fileAFormReq "File" <*> areq textField "TableId"
    # Those strings are LABELS. Yesod's renderDivs auto-generates the actual
    # multipart field NAMES `f1`, `f2` in field order. Posting `File`/`TableId`
    # yields `400 FormFailure`. See the comment on the form definition.
    files = {
        "f1": (os.path.basename(xlsx_path), xlsx_bytes, XLSX_CONTENT_TYPE),
    }
    data = {"f2": table_uuid}
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
        print(f"OK — imported spreadsheet for source {table_uuid} on LJ {serial}.")
        try:
            payload = resp.json()
        except ValueError:
            return
        # OnpingResponse a: on success, the envelope is `toJSON a` — the
        # `LogTableSource` object itself. On error, it's `{"error": <text>}`.
        if isinstance(payload, dict) and "error" in payload:
            # 2xx with an error envelope is unusual, but surface it.
            print(f"NOTE: server returned an error envelope: {payload['error']}",
                  file=sys.stderr)
            return
        if isinstance(payload, dict):
            server_id = payload.get("logTableSourceId")
            schemas = payload.get("logTableSourceSchemas") or []
            col_count: Optional[int] = None
            if schemas and isinstance(schemas, list):
                # Pick the schema matching the current schemaVersion.
                version = payload.get("logTableSourceSchemaVersion")
                match = next(
                    (
                        s
                        for s in schemas
                        if isinstance(s, dict)
                        and s.get("logSchemaVersion") == version
                    ),
                    schemas[0] if isinstance(schemas[0], dict) else None,
                )
                if match:
                    header = match.get("logSchemaHeader") or {}
                    cols = header.get("schemaHeaderColumns") or {}
                    if isinstance(cols, dict):
                        col_count = len(cols)
            print(f"  TableId: {server_id}")
            if col_count is not None:
                print(f"  Columns: {col_count}")
        return

    # Non-2xx.
    body = resp.text[:1000]
    if resp.status_code == 400 and "Permission Denied" in body:
        print(
            f"HTTP 400 Permission Denied from {url}\n"
            "The log-table source's group must be in your owned-groups list "
            "(handler check at onping/Handler/OnpingLogTable/Service.hs). "
            "Confirm the source's `logTableSourceGroupId` matches a group you own.",
            file=sys.stderr,
        )
    else:
        print(f"HTTP {resp.status_code} from {url}", file=sys.stderr)
        print(body, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Upload a multiple-rows-header log-table XLSX to OnPing. "
        "MUTATING — requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("lj_serial", help="Lumberjack serial (int, sent as path segment)")
    p.add_argument("table_uuid", help="target log-table source's TableId (UUID)")
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

    # Sanity-check the UUID locally so the handler doesn't reject with a
    # bare `error "tableId is not a valid UUID"` (Service.hs).
    try:
        parsed_uuid = _uuid.UUID(args.table_uuid)
    except ValueError:
        print(
            f"table_uuid `{args.table_uuid}` is not a valid UUID.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.exists(args.spreadsheet):
        print(f"File not found: {args.spreadsheet}", file=sys.stderr)
        sys.exit(1)

    with open(args.spreadsheet, "rb") as f:
        xlsx_bytes = f.read()

    rows = _load_header_rows(xlsx_bytes)
    errors, warnings, col_count = _validate(rows)

    print(f"LJ serial:     {args.lj_serial}")
    print(f"Table UUID:    {parsed_uuid}")
    print(f"Spreadsheet:   {os.path.abspath(args.spreadsheet)}")
    print(f"Header rows:   {min(len(rows), 4)}")
    print(f"Columns:       {col_count}")
    print(f"Warnings:      {len(warnings)}")
    print(f"Errors:        {len(errors)}")
    for w in warnings:
        print(f"  warn: {w}")
    for e in errors:
        print(f"  err : {e}", file=sys.stderr)

    if args.dry_run or not args.yes:
        if args.dry_run:
            print("\n[dry-run] not uploading.")
        else:
            print("\nPreview only. Re-run with --yes to upload.")
        if errors:
            print(
                "NOTE: upload is currently BLOCKED (validation errors).",
                file=sys.stderr,
            )
        return

    if errors:
        print(
            "\nRefusing to upload: fix the validation errors above first.",
            file=sys.stderr,
        )
        sys.exit(1)

    _upload(
        args.access_token,
        args.lj_serial,
        str(parsed_uuid),
        args.spreadsheet,
        xlsx_bytes,
    )


if __name__ == "__main__":
    main()
