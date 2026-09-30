#!/usr/bin/env python3
"""Build an OnPing mass-write CSV from timestamp+value points.

Offline only — no network, no auth. Outputs a file (or stdout) ready for
upload via the OnPing UI mass-import dialog.
"""

import argparse
import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_points(rows):
    """Validate and parse rows into [(dt, ts_str, value_str), ...].

    rows: iterable of lists from csv.reader. Trailing fully-blank rows are
    tolerated. Any other validation failure raises SystemExit.
    """
    points = []
    seen = set()
    for idx, row in enumerate(rows, start=1):
        if not row or all(c.strip() == "" for c in row):
            continue
        if len(row) != 2:
            fail(f"row {idx} has {len(row)} columns, expected 2: {row!r}")
        ts_str, val_str = row[0].strip(), row[1].strip()
        try:
            dt = datetime.fromisoformat(ts_str)
        except ValueError:
            fail(f"row {idx} timestamp does not parse as ISO 8601: {ts_str!r}")
        try:
            float(val_str)
        except ValueError:
            fail(f"row {idx} value is not numeric: {val_str!r}")
        if ts_str in seen:
            fail(f"duplicate timestamp: {ts_str!r}")
        seen.add(ts_str)
        points.append((dt, ts_str, val_str))

    if not points:
        fail("no data rows found in input")
    points.sort(key=lambda p: p[0])
    return points


def render_csv(pid: str, label: str, points) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(["", label])
    writer.writerow(["Time", pid])
    for _dt, ts_str, val_str in points:
        writer.writerow([ts_str, val_str])
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an OnPing mass-write CSV from timestamp+value points."
    )
    parser.add_argument("pid", help="Target OnPing parameter id (numeric).")
    parser.add_argument(
        "--input",
        dest="input_path",
        help="Path to a no-header two-column CSV (timestamp,value). "
        "If omitted, reads from stdin.",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Optional human label placed in row 1 column B.",
    )
    out_group = parser.add_mutually_exclusive_group()
    out_group.add_argument(
        "--output",
        dest="output_path",
        help="Path to write the CSV. "
        "Default: ./mass-write-<PID>-<UTC-timestamp>.csv",
    )
    out_group.add_argument(
        "--stdout",
        action="store_true",
        help="Write CSV body to stdout instead of a file.",
    )

    args = parser.parse_args()

    try:
        int(args.pid)
    except ValueError:
        fail(f"PID is not numeric: {args.pid!r}")

    if args.input_path:
        try:
            text = Path(args.input_path).read_text()
        except OSError as e:
            fail(f"could not read --input {args.input_path}: {e}")
        reader = csv.reader(io.StringIO(text))
    else:
        reader = csv.reader(sys.stdin)

    points = parse_points(reader)
    csv_text = render_csv(args.pid, args.label, points)

    if args.stdout:
        sys.stdout.write(csv_text)
        return 0

    if args.output_path:
        out_path = Path(args.output_path)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path.cwd() / f"mass-write-{args.pid}-{ts}.csv"

    out_path.write_text(csv_text)
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
