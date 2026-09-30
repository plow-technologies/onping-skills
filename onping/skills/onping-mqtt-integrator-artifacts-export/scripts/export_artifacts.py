# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "openpyxl"]
# ///
"""Download one Lumberjack's mqtt-json-integrator CREATED-object record.

Routes: GET /mqtt/json/integrator/{serial}/artifacts/export/{filename} -> XLSX
        GET /mqtt/json/integrator/{serial}/artifacts                   -> JSON

Read-only on the server: both are GETs and neither mutates state.

WHAT "ARTIFACTS" MEANS HERE. Artifacts are the integrator's OWN RECORD of the
locations and PIDs it believes it created in OnPing and pushed to the mqtt-json
driver. The data flow is strictly one-way: the integrator cannot query OnPing to
confirm these still exist, and it does not trend their values — each
storedPidValue is frozen at the moment the rules ran. So this export is a record
of INTENT, not a verified inventory. To confirm an object really exists, resolve
its PID with onping-pid-locate or list the driver location's parameters with
onping-export-mqtt-json.

WHAT THE RECORD IS FOR. Beyond audit, its live function is SUPPRESSION: the
create pipeline skips anything already recorded as created. That is why
importing an artifacts sheet (onping-mqtt-integrator-artifacts-import) creates
nothing but still changes behavior.

THE EXPORT IS LOSSY (Artifacts/ImportExport.hs). Round-tripping through the
spreadsheet does NOT preserve the record:
  - localParameterTime is dropped entirely; a re-import sets it to null
  - a value that matches no known constructor falls back to Double 0.0 / "0.0"
Use --json for a faithful copy; use the XLSX only when you intend to edit and
re-import.

THE {filename} PATH SEGMENT IS IGNORED by the handler (bound to `_`).

Source of truth (re-verify if these drift):
  - Handlers: onping/Handler/MqttJsonIntegrator/Service.hs (XLSX export),
              :155 (JSON)
  - Sheet:    onping/Handler/MqttJsonIntegrator/Artifacts/ImportExport.hs
  - Schema:   _mqtt_integrator_routes/rules_sheet.py (ARTIFACTS_HEADERS)
  - Lifecycle: mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md,
               "Created Objects"
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _mqtt_integrator_routes import rules_sheet
from _mqtt_integrator_routes.integrator_http import _fail, get_bytes, get_json
from _mqtt_integrator_routes.routes import endpoint

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - uv installs the dep
    print("openpyxl is required (declared in the uv script header)", file=sys.stderr)
    sys.exit(1)


def read_sheet(xlsx: bytes) -> tuple[list, list[list]]:
    """Parse the exported workbook into (header_row, data_rows)."""
    try:
        wb = load_workbook(io.BytesIO(xlsx), data_only=True)
    except Exception as e:
        _fail(f"Could not read the returned workbook: {e}")
    if rules_sheet.SHEET_NAME not in wb.sheetnames:
        _fail(
            f"Expected a {rules_sheet.SHEET_NAME!r} worksheet, found "
            f"{wb.sheetnames}. The export format may have changed."
        )
    ws = wb[rules_sheet.SHEET_NAME]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    if not rows:
        return [], []
    header = list(rows[rules_sheet.HEADER_ROW - 1])
    data = rows[rules_sheet.FIRST_DATA_ROW - 1 :]

    def is_blank(row: list) -> bool:
        return all(v is None or (isinstance(v, str) and not v.strip()) for v in row)

    while data and is_blank(data[-1]):
        data.pop()
    return header, data


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Download one Lumberjack's mqtt-json-integrator created-object "
            "record as XLSX (default) or JSON. Read-only."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument(
        "--out",
        help="local path to write (default: integrator-artifacts-<serial>.xlsx, "
        "or -<serial>.json with --json)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="fetch the JSON record instead of the XLSX — LOSSLESS, unlike the "
        "spreadsheet (see --help notes on lossiness)",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help="print a per-location breakdown of the recorded objects",
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help="check the downloaded sheet against the expected schema",
    )
    p.add_argument(
        "--filename",
        default="artifacts.xlsx",
        help="the {filename} path segment; IGNORED by the server "
        "(default: artifacts.xlsx)",
    )
    p.add_argument(
        "--stdout",
        action="store_true",
        help="with --json, print to stdout instead of writing a file",
    )
    args = p.parse_args()

    # ── JSON path ───────────────────────────────────────────────────────────
    if args.json:
        artifacts = get_json(
            args.access_token, endpoint("get_artifacts"), serial=args.serial
        )
        if not isinstance(artifacts, dict):
            _fail(f"Expected an Artifacts object, got: {json.dumps(artifacts)[:400]}")
        locations = artifacts.get("storedLocations") or []
        pids = artifacts.get("storedPids") or []
        text = json.dumps(artifacts, indent=2, sort_keys=True)
        if args.stdout:
            print(text)
        else:
            out = Path(args.out or f"integrator-artifacts-{args.serial}.json")
            out.write_text(text + "\n", encoding="utf-8")
            print(
                f"Wrote {len(locations)} location(s) and {len(pids)} PID(s) to {out}"
            )
        if args.summary:
            by_loc: dict[str, int] = {}
            for pid in pids:
                key = (
                    (pid.get("storedPidUniqueIdentifier") or {})
                    .get("pidLocationUniqueIdentifier", {})
                    .get("unLocationUniqueIdentifier", "?")
                )
                by_loc[key] = by_loc.get(key, 0) + 1
            print(f"\n{len(locations)} recorded location(s):", file=sys.stderr)
            for loc in locations:
                key = (loc.get("storedLocationUniqueIdentifier") or {}).get(
                    "unLocationUniqueIdentifier", "?"
                )
                print(
                    f"  refId={loc.get('storedLocationIdRef')}  "
                    f"name={loc.get('storedLocationName')!r}  "
                    f"key={key!r}  pids={by_loc.get(key, 0)}",
                    file=sys.stderr,
                )
            orphans = set(by_loc) - {
                (l.get("storedLocationUniqueIdentifier") or {}).get(
                    "unLocationUniqueIdentifier"
                )
                for l in locations
            }
            if orphans:
                print(
                    f"\nWARNING: {len(orphans)} PID(s) reference a location key that "
                    f"is NOT in storedLocations: {sorted(orphans)}",
                    file=sys.stderr,
                )
        return

    # ── XLSX path ───────────────────────────────────────────────────────────
    xlsx = get_bytes(
        args.access_token,
        endpoint("export_artifacts"),
        serial=args.serial,
        filename=args.filename,
    )
    out = Path(args.out or f"integrator-artifacts-{args.serial}.xlsx")
    out.write_bytes(xlsx)
    print(f"Wrote {len(xlsx)} bytes to {out}")
    print(
        "\nNOTE: this spreadsheet is a LOSSY view — PID timestamps are dropped "
        "and unrecognized values collapse to 0.0. Use --json for a faithful copy."
    )

    if not (args.summary or args.validate):
        return

    header, rows = read_sheet(xlsx)
    expected = rules_sheet.ARTIFACTS_HEADERS
    got = [str(h).strip() if h is not None else "" for h in header][: len(expected)]
    if got != expected:
        print(
            f"\nWARNING: header row does not match the expected schema.\n"
            f"  expected: {expected}\n  got:      {got}\n"
            f"Re-verify Artifacts/ImportExport.hs against "
            f"rules_sheet.ARTIFACTS_HEADERS.",
            file=sys.stderr,
        )

    errors: list[str] = []
    location_only = 0
    pid_rows = 0
    per_location: dict[tuple, int] = {}

    for offset, row in enumerate(rows):
        row_number = rules_sheet.FIRST_DATA_ROW + offset
        row_errors, is_loc_only = rules_sheet.validate_row(
            row, flavor="artifacts", row_number=row_number
        )
        errors.extend(row_errors)
        if is_loc_only:
            location_only += 1
        else:
            pid_rows += 1
        key = tuple(str(v).strip() if v is not None else "" for v in list(row)[:3])
        per_location[key] = per_location.get(key, 0) + (0 if is_loc_only else 1)

    if args.summary:
        print(
            f"\n{len(rows)} data row(s): {pid_rows} PID row(s), "
            f"{location_only} location-only.\n"
            f"{len(per_location)} distinct location(s):\n"
        )
        for (key, name, refid), count in per_location.items():
            print(f"  refId={refid}  name={name!r}\n      key={key!r}  pids={count}")

    if args.validate:
        if errors:
            print(
                f"\n{len(errors)} schema problem(s) in the DOWNLOADED sheet:",
                file=sys.stderr,
            )
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
        print("\nValidation: every row matches the expected artifacts-sheet schema.")


if __name__ == "__main__":
    main()
