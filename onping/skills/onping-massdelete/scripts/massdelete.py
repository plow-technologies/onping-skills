# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete historian samples via OnPing's mass-delete endpoint.

Route:  POST /massdelete/execute
Body:   JSON array  [{"deletePid": <int>, "deleteDate": "<RFC-3339 UTC>"}, ...]
Handler: onping/Handler/MassWrite/Service.hs (postMassDeleteExecuteR)
Type:   onping-types/onping-base-types/src/Onping/Types/GenericWriteRequest.hs
        (DeleteRequest {deletePid :: PID, deleteDate :: PlowUTCTime})

Input is the OnPing event-report CSV shape:
  row 1: human labels          (ignored)
  row 2: `Time,<PID>,<PID>,...` (column 0 is a placeholder header,
                                remaining cells are integer PIDs)
  data rows: column 0 = ISO-8601 timestamp,
             other cells = `1.0` (delete this (PID, timestamp) point)
                         or blank (skip)

Each non-blank data cell produces one `{deletePid, deleteDate}` entry.
Non-`1.0` populated cells are hard-blocked: they usually mean the caller
forgot to sed-replace some values, and a silent skip would under-delete.

`PlowUTCTime`'s FromJSON delegates to aeson's UTCTime parser, which REQUIRES
a timezone (`Z` or `±HH:MM`). Naive timestamps are treated as UTC and
emitted with a `Z` suffix; offset-bearing timestamps are converted to UTC
and re-emitted with `Z`. Second precision — the historian buckets to
whole seconds (`plowUTCTimeToInt` in the handler).

MUTATES live OnPing state only with --yes. Without --yes (or with --dry-run)
the skill validates + previews and never POSTs. --dry-run wins if both are
passed.

Response envelope (from mass-writes-types/src/MassWrites/Types.hs,199):
  { "successes": [ { "responsePid": <int>,
                     "responseWriteTime": {"tag": "PastWriteTime",
                                           "contents": "<ISO>"} }, ... ],
    "failures":  [ ...same shape... ] }
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from typing import Iterable, List, Optional, Tuple

import requests

BASE_URL = "https://onping.plowtech.net"
EXECUTE_PATH = "/massdelete/execute"
TIMEOUT_SECONDS = 60

DEFAULT_MAX_BATCH = 5000
DELETE_SENTINEL = "1.0"


def _parse_timestamp(raw: str, row: int) -> dt.datetime:
    """Parse an ISO-8601 timestamp, naive-treated-as-UTC.

    Returns a timezone-aware UTC datetime. Raises ValueError with the row
    number in the message on failure.
    """
    s = raw.strip()
    # datetime.fromisoformat accepts a trailing `Z` only from Python 3.11+;
    # normalize to `+00:00` so 3.10 works too.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(
            f"row {row}: column-0 timestamp `{raw}` is not ISO-8601: {e}"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    else:
        parsed = parsed.astimezone(dt.timezone.utc)
    return parsed.replace(microsecond=0)


def _format_utc(t: dt.datetime) -> str:
    # `YYYY-MM-DDTHH:MM:SSZ` — matches the reference request body verbatim.
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_csv(csv_path: str) -> Tuple[List[int], List[List[str]]]:
    """Return (pid_header, data_rows) as ints + row-of-strings.

    Row 1 (human labels) is dropped. Row 2 is the PID header; column 0 is the
    time-column placeholder and is stripped.
    """
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        raise ValueError(
            f"CSV must have at least 3 rows (labels, PID header, "
            f"and ≥1 data row); found {len(rows)}"
        )
    pid_row = rows[1]
    if not pid_row:
        raise ValueError("row 2 (PID header) is empty")
    pids: List[int] = []
    for c, cell in enumerate(pid_row[1:], start=2):
        try:
            pids.append(int(cell.strip()))
        except ValueError:
            raise ValueError(
                f"row 2 col {c}: expected integer PID, found `{cell}`"
            ) from None
    return pids, rows[2:]


def _build_entries(
    pids: List[int], data_rows: List[List[str]]
) -> Tuple[List[dict], List[str]]:
    """Return (entries, errors). Errors are validation problems; if any are
    non-empty the caller should refuse to upload."""
    entries: List[dict] = []
    errors: List[str] = []
    for i, row in enumerate(data_rows):
        sheet_row = i + 3  # rows[0]=labels, rows[1]=pid header, so data row 0 == sheet row 3
        if not row or all(c.strip() == "" for c in row):
            continue  # blank line
        # Column 0 is the timestamp.
        try:
            ts = _parse_timestamp(row[0], sheet_row)
        except ValueError as e:
            errors.append(str(e))
            continue
        deleteDate = _format_utc(ts)
        for c_idx, cell in enumerate(row[1:], start=1):
            if c_idx - 1 >= len(pids):
                # more data columns than PID columns — flag once per row
                errors.append(
                    f"row {sheet_row}: has {len(row) - 1} data cells but only "
                    f"{len(pids)} PIDs declared in row 2"
                )
                break
            val = cell.strip()
            if val == "":
                continue
            if val != DELETE_SENTINEL:
                errors.append(
                    f"row {sheet_row} col {c_idx + 1}: value `{val}` is not `{DELETE_SENTINEL}` — "
                    "normalize populated cells to 1.0 (the delete-marker convention)"
                )
                continue
            entries.append({"deletePid": pids[c_idx - 1], "deleteDate": deleteDate})
    return entries, errors


def _chunked(seq: List[dict], size: int) -> Iterable[List[dict]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _post_chunk(
    token: str, chunk: List[dict], verbose: bool
) -> Tuple[Optional[dict], Optional[str]]:
    """POST one chunk. Returns (parsed_response_or_None, error_or_None)."""
    url = BASE_URL + EXECUTE_PATH
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(chunk),
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return None, f"transport error: {e}"
    if not (200 <= resp.status_code < 300):
        return None, f"HTTP {resp.status_code}: {resp.text[:500]}"
    try:
        parsed = resp.json()
    except ValueError:
        return None, f"non-JSON response: {resp.text[:500]}"
    if isinstance(parsed, dict) and "error" in parsed and "successes" not in parsed:
        # OnpingResponse error envelope
        return None, f"server error: {parsed['error']}"
    if verbose:
        print(json.dumps(parsed, indent=2), file=sys.stderr)
    return parsed, None


def _summarize_failure(item: dict) -> str:
    pid = item.get("responsePid", "?")
    wt = item.get("responseWriteTime") or {}
    if isinstance(wt, dict):
        tag = wt.get("tag")
        if tag == "PastWriteTime":
            return f"pid={pid} time={wt.get('contents', '?')}"
        if tag == "WriteNow":
            return f"pid={pid} time=WriteNow"
    return f"pid={pid} raw={wt!r}"


def _report(
    successes: List[dict], failures: List[dict], chunks_ok: int, chunks_total: int
) -> int:
    n = len(successes)
    m = len(failures)
    tag = "" if chunks_total == 1 else f" across {chunks_total} chunks"
    print(f"deleted {n}, failed {m}{tag}.")
    if m == 0:
        return 0
    print("Failures:", file=sys.stderr)
    for it in failures[:20]:
        print(f"  - {_summarize_failure(it)}", file=sys.stderr)
    if m > 20:
        print(f"  …and {m - 20} more", file=sys.stderr)
    return 1


def main() -> None:
    p = argparse.ArgumentParser(
        description="Delete historian samples via OnPing's /massdelete/execute. "
        "MUTATING — requires --yes."
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("csv_path", help="path to the event-report CSV (1.0 sentinel)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + preview only; never POST (wins over --yes)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="perform the delete (POST). Without it, preview only.",
    )
    p.add_argument(
        "--max-batch",
        type=int,
        default=DEFAULT_MAX_BATCH,
        help=f"chunk size for /massdelete/execute POSTs (default {DEFAULT_MAX_BATCH})",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="print full JSON responses to stderr",
    )
    args = p.parse_args()

    try:
        pids, data_rows = _load_csv(args.csv_path)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    entries, errors = _build_entries(pids, data_rows)

    unique_pids = sorted({e["deletePid"] for e in entries})
    unique_times = sorted({e["deleteDate"] for e in entries})

    print(f"CSV:          {args.csv_path}")
    print(f"PID columns:  {len(pids)}  {pids}")
    print(f"Data rows:    {len(data_rows)}")
    print(f"Delete entries: {len(entries)}")
    if unique_pids:
        print(f"Unique PIDs:  {unique_pids}")
    if unique_times:
        print(
            f"Time range:   {unique_times[0]}  →  {unique_times[-1]}  "
            f"({len(unique_times)} distinct)"
        )
    print(f"Errors:       {len(errors)}")
    for err in errors:
        print(f"  err: {err}", file=sys.stderr)

    if args.dry_run or not args.yes:
        if args.dry_run:
            print("\n[dry-run] not deleting.")
        else:
            print("\nPreview only. Re-run with --yes to delete.")
        if errors:
            print(
                "NOTE: delete is currently BLOCKED (validation errors).",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    if errors:
        print(
            "\nRefusing to delete: fix the validation errors above first.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not entries:
        print("\nNothing to delete (no `1.0` cells found).")
        return

    chunks = list(_chunked(entries, max(1, args.max_batch)))
    successes: List[dict] = []
    failures: List[dict] = []
    for idx, chunk in enumerate(chunks, start=1):
        print(f"POST chunk {idx}/{len(chunks)} ({len(chunk)} entries) …", flush=True)
        parsed, err = _post_chunk(args.access_token, chunk, args.verbose)
        if err is not None:
            submitted = sum(len(c) for c in chunks[: idx - 1])
            print(
                f"chunk {idx}/{len(chunks)} failed: {err}\n"
                f"  {submitted} entries were already submitted in prior chunks; "
                f"{len(entries) - submitted} entries were NOT sent.",
                file=sys.stderr,
            )
            sys.exit(1)
        successes.extend(parsed.get("successes") or [])
        failures.extend(parsed.get("failures") or [])

    exit_code = _report(successes, failures, len(chunks), len(chunks))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
