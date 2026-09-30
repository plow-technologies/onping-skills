# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Download a log-table source's XLSX (multi-row-header variant) from OnPing.

Route: POST /logtable/#LJSerial/source/export/query/multiple-rows-header/#String
Body:  JSON tuple `(LogTableSource, Int)` — the full source record + the
       schema-version integer. The `Int` is `logTableSourceSchemaVersion`
       (verified against the frontend caller
       `OnpingLogTable/Configure/OnpingLogTable_Configure_ImportFromTemplate.res`
       which passes `t'.logTableSourceSchemaVersion`).

Because the endpoint requires the full source record (not just a UUID), the
skill first fetches the LJ's source list (`GET /logtable/#LJSerial/source/list`)
and picks the entry matching the caller's TableId.

Read-only on the server: the POST is a query, not a mutation. No `--yes` gate.

Source of truth (re-verify if these drift):
  - Export handler: onping/Handler/OnpingLogTable/Service.hs
                    (postLogTableSourceExportQueryMultipleRowsHeaderR)
  - List handler:   onping/Handler/OnpingLogTable/Service.hs
                    (getLogTableSourceListR)
  - Types:          onping-logtable/onping-logtable-types/src/Onping/LogTable/Types.hs
                    (LogTableSource)
  - Frontend:       OnpingFetch/OnpingFetch_OnpingLogTable.res
                    (exportLogTableSourceQueryMultipleRowsHeader)
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import uuid as _uuid
from typing import Any, Optional

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 60

LIST_PATH = "/logtable/{serial}/source/list"
EXPORT_PATH = (
    "/logtable/{serial}/source/export/query/multiple-rows-header/{filename}"
)


def _utc_stamp() -> str:
    # Use timezone-aware UTC so this works on Python 3.12+ where naive utcnow is deprecated.
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fetch_source(
    token: str, serial: str, table_uuid: str
) -> dict:
    url = BASE_URL + LIST_PATH.format(serial=serial)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        resp = requests.get(
            url, headers=headers, allow_redirects=True, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        print(f"Failed to fetch source list from {url}: {e}", file=sys.stderr)
        sys.exit(1)

    if not (200 <= resp.status_code < 300):
        print(
            f"HTTP {resp.status_code} fetching source list from {url}\n"
            f"{resp.text[:1000]}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        payload = resp.json()
    except ValueError:
        print(
            f"Expected JSON from {url}, got:\n{resp.text[:500]}",
            file=sys.stderr,
        )
        sys.exit(1)

    # OnpingResponse [LogTableSource]:
    #   success  -> the array itself
    #   error    -> {"error": "<text>"}
    if isinstance(payload, dict) and "error" in payload:
        print(
            f"Server returned an error listing sources on LJ {serial}: "
            f"{payload['error']}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(payload, list):
        print(
            f"Expected a JSON array of LogTableSource, got: {type(payload).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)

    for entry in payload:
        if (
            isinstance(entry, dict)
            and str(entry.get("logTableSourceId", "")).lower() == table_uuid.lower()
        ):
            return entry

    print(
        f"No log-table source with TableId {table_uuid} on LJ {serial}. "
        f"({len(payload)} source(s) returned by GET {LIST_PATH.format(serial=serial)}.)",
        file=sys.stderr,
    )
    sys.exit(1)


def _export(
    token: str,
    serial: str,
    source: dict,
    filename: str,
    out_path: str,
) -> str:
    url = BASE_URL + EXPORT_PATH.format(serial=serial, filename=filename)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    # Body shape from handler `Service.hs`:
    #   payload@(t, _version) <- requireInsecureJsonBody :: Handler (LogTableSource, Int)
    # Aeson's default tuple encoding is a JSON array `[<source>, <int>]`.
    version = source.get("logTableSourceSchemaVersion")
    if not isinstance(version, int):
        print(
            f"LogTableSource missing integer `logTableSourceSchemaVersion`; "
            f"got {version!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    body: list[Any] = [source, version]

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=body,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        print(f"Export request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not (200 <= resp.status_code < 300):
        body_text = resp.text[:1000]
        if resp.status_code == 500 and "Permission Denied" in body_text:
            print(
                f"HTTP 500 Permission Denied from {url}\n"
                "The log-table source's group must be in your owned-or-member "
                "groups (handler check at Service.hs). Verify group access.",
                file=sys.stderr,
            )
        else:
            print(f"HTTP {resp.status_code} from {url}", file=sys.stderr)
            print(body_text, file=sys.stderr)
        sys.exit(1)

    with open(out_path, "wb") as f:
        f.write(resp.content)
    return os.path.abspath(out_path)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Download a log-table source's XLSX (multi-row-header) from OnPing."
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("lj_serial", help="Lumberjack serial (int, sent as path segment)")
    p.add_argument("table_uuid", help="log-table source's TableId (UUID)")
    p.add_argument(
        "filename",
        nargs="?",
        default=None,
        help="local output path (default: ./logtable-<lj>-<uuid>-<UTC>.xlsx)",
    )
    args = p.parse_args()

    try:
        parsed_uuid = _uuid.UUID(args.table_uuid)
    except ValueError:
        print(
            f"table_uuid `{args.table_uuid}` is not a valid UUID.",
            file=sys.stderr,
        )
        sys.exit(1)

    out_path: str = args.filename or (
        f"./logtable-{args.lj_serial}-{parsed_uuid}-{_utc_stamp()}.xlsx"
    )
    # The URL requires a `#String` filename path segment (see route
    # onping/config/routes). Server uses it in the Content-Disposition
    # header of the response; the actual disk path is our `out_path`.
    remote_filename = os.path.basename(out_path)

    source = _fetch_source(
        args.access_token, args.lj_serial, str(parsed_uuid)
    )
    resolved = _export(
        args.access_token,
        args.lj_serial,
        source,
        remote_filename,
        out_path,
    )
    print(resolved)


if __name__ == "__main__":
    main()
