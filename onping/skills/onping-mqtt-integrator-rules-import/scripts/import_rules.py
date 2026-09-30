# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "openpyxl"]
# ///
"""Upload a generation-rule spreadsheet to mqtt-json-integrator. DESTRUCTIVE.

Route: POST /mqtt/json/integrator/{serial}/rules/import
Body:  multipart form, f1 = XLSX bytes

THIS REPLACES THE ENTIRE RULE SET. The handler routes to
postImportGenerationRules, documented upstream as "this overwrite any existing
rules"; data-lifetime-and-uniqueness-rules.md is blunter: "when you import it
deletes everything and rebuilds the rule system from the excel file." Any rule
absent from your sheet is DELETED. The only safe workflow is:

    onping-mqtt-integrator-rules-export  ->  edit  ->  import

Because of that, this script FETCHES THE LIVE RULES FIRST and shows you what the
import would add, drop, and keep. Refusing to run without that comparison is the
point: there is no server-side merge and no undo.

IDENTIFIERS ARE RENUMBERED. reconstructGenerationRules assigns every
LocationRuleIdentifier and PidRuleIdentifier from ROW ORDER, so even a byte-identical
round-trip renumbers all ids. Anything holding a rule id externally must be
re-read afterward. The sheet cannot express ids at all — use the incremental
POST .../generation/rules path (not covered by this skill) if you need to edit
one rule while preserving ids.

ROW GROUPING. Rules are grouped by CONSECUTIVE rows sharing identical columns
1-3. Two non-adjacent blocks for the same location become TWO separate location
rules. The pre-flight warns about this because the server accepts it silently.

THE f1 FIELD-NAME GOTCHA. The handler's form is
`renderDivs $ fileAFormReq "File"`. "File" is a LABEL, not a field name — Yesod's
renderDivs auto-names fields positionally, so the real name is `f1`. Posting
"File" yields 400 FormFailure. Confirmed in the frontend at
OnpingFetch_ImportParameters.res (`ret.append("f1", blob)`). Same trap as
the logtable and singlewell-manual imports.

MUTATES OnPing only with --yes. Without --yes (or with --dry-run) the sheet is
validated locally, diffed against the live rules, and previewed — never POSTed.
--dry-run wins if both are passed.

Source of truth (re-verify if these drift):
  - Handler:  onping/Handler/MqttJsonIntegrator/Service.hs
  - Rebuild:  onping/Handler/MqttJsonIntegrator/Rules/ImportExport.hs
              (reconstructGenerationRules, groupByLocationId)
  - Schema:   _mqtt_integrator_routes/rules_sheet.py (RULES_HEADERS)
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _mqtt_integrator_routes import rules_sheet
from _mqtt_integrator_routes.integrator_http import (
    _fail,
    get_json,
    post_empty,
    post_multipart_xlsx,
    report_write,
)
from _mqtt_integrator_routes.routes import endpoint

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - uv installs the dep
    print("openpyxl is required (declared in the uv script header)", file=sys.stderr)
    sys.exit(1)


def read_local_sheet(path: Path) -> tuple[list, list[list]]:
    """Parse the local workbook the way the server will."""
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as e:
        _fail(f"Could not read {path}: {e}")
    if rules_sheet.SHEET_NAME not in wb.sheetnames:
        _fail(
            f"{path} has no {rules_sheet.SHEET_NAME!r} worksheet (found "
            f"{wb.sheetnames}). The server reads only "
            f"{rules_sheet.SHEET_NAME!r} and would reject this file."
        )
    ws = wb[rules_sheet.SHEET_NAME]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    if not rows:
        _fail(f"{path} is empty.")
    header = list(rows[rules_sheet.HEADER_ROW - 1])
    data = rows[rules_sheet.FIRST_DATA_ROW - 1 :]

    def is_blank(row: list) -> bool:
        return all(v is None or (isinstance(v, str) and not v.strip()) for v in row)

    # The server filters blank cells before reading, so trailing template rows
    # are harmless; drop them here too so counts line up.
    while data and is_blank(data[-1]):
        data.pop()
    return header, data


def location_key(row: list) -> tuple:
    """Columns 1-3, which are what the server groups on."""
    cells = list(row) + [None] * (3 - len(row))
    return tuple(
        (str(v).strip() if v is not None else "") for v in cells[:3]
    )


def live_rule_keys(token: str, serial: str) -> tuple[list[tuple], int]:
    """(location keys currently stored, total PID-rule count)."""
    rules = get_json(token, endpoint("get_rules"), serial=serial)
    if not isinstance(rules, list):
        _fail(f"Expected a rule array from the live LJ, got {type(rules).__name__}")
    keys = []
    pid_total = 0
    for r in rules:
        loc = r.get("generationRuleLocation") or {}
        pids = r.get("generationRulePids") or []
        pid_total += len(pids)
        keys.append(
            (
                str(loc.get("locationRuleSelectorName") or ""),
                str((loc.get("locationRuleName") or {}).get("unMqttRuleText") or ""),
                str((loc.get("locationRuleLocationId") or {}).get("unMqttRuleText") or ""),
            )
        )
    return keys, pid_total


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Upload a generation-rule XLSX to mqtt-json-integrator. REPLACES "
            "THE ENTIRE RULE SET — mutates OnPing only with --yes."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument("spreadsheet", help="path to the rules XLSX to upload")
    p.add_argument(
        "--execute",
        action="store_true",
        help="after a successful import, run the new rules against the stored "
        "unprocessed data (POST .../generation/rules/execute). Blocking; "
        "creates nothing in OnPing.",
    )
    p.add_argument(
        "--skip-live-check",
        action="store_true",
        help="do not fetch the live rules for the add/drop diff. Only for when "
        "the GET is failing; you lose the deletion warning.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate, diff, and preview; never POST (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually perform the upload")
    args = p.parse_args()

    path = Path(args.spreadsheet)
    if not path.is_file():
        _fail(f"No such file: {path}")

    header, rows = read_local_sheet(path)

    # ── schema checks ───────────────────────────────────────────────────────
    expected = rules_sheet.RULES_HEADERS
    got = [str(h).strip() if h is not None else "" for h in header][: len(expected)]
    if got != expected:
        print(
            f"Header row does not match the expected rules-sheet schema.\n"
            f"  expected: {expected}\n  got:      {got}",
            file=sys.stderr,
        )
        if got == rules_sheet.ARTIFACTS_HEADERS[: len(got)]:
            print(
                "\nThis looks like an ARTIFACTS sheet, not a rules sheet. The two "
                "are both 12 columns but mean different things — you want "
                "onping-mqtt-integrator-artifacts-import.",
                file=sys.stderr,
            )
        _fail("Refusing to upload a sheet whose headers do not match.")

    if not rows:
        _fail(
            "The sheet has no data rows. Importing it would DELETE every rule on "
            f"LJ {args.serial}. If that is genuinely the intent, do it in the UI "
            "where the consequence is explicit."
        )

    errors: list[str] = []
    location_only = 0
    pid_rows = 0
    blocks: list[tuple[tuple, int]] = []

    for offset, row in enumerate(rows):
        row_number = rules_sheet.FIRST_DATA_ROW + offset
        row_errors, is_loc_only = rules_sheet.validate_row(
            row, flavor="rules", row_number=row_number
        )
        errors.extend(row_errors)
        if is_loc_only:
            location_only += 1
        else:
            pid_rows += 1
        key = location_key(row)
        if blocks and blocks[-1][0] == key:
            blocks[-1] = (key, blocks[-1][1] + (0 if is_loc_only else 1))
        else:
            blocks.append((key, 0 if is_loc_only else 1))

    print(
        f"Sheet: {path}\n"
        f"  {len(rows)} data row(s): {pid_rows} with a PID rule, "
        f"{location_only} location-only\n"
        f"  {len(blocks)} contiguous location block(s) -> "
        f"{len(blocks)} location rule(s) after import\n"
    )

    if errors:
        print(f"{len(errors)} problem(s) would make the server reject this sheet:",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        _fail("Refusing to upload an invalid sheet.")

    # ── non-contiguity warning ──────────────────────────────────────────────
    seen: dict[tuple, int] = {}
    for key, _ in blocks:
        seen[key] = seen.get(key, 0) + 1
    repeated = {k: v for k, v in seen.items() if v > 1}
    if repeated:
        print(
            f"WARNING: {len(repeated)} location appears in more than one "
            f"NON-ADJACENT block. The server groups only CONSECUTIVE rows with "
            f"identical columns 1-3, so each block becomes a SEPARATE location "
            f"rule with duplicated PIDs. Sort the sheet so each location's rows "
            f"are contiguous.",
            file=sys.stderr,
        )
        for key, count in repeated.items():
            print(f"    {count}x  selector={key[0]!r}  match={key[2]!r}",
                  file=sys.stderr)
        print(file=sys.stderr)

    # ── the deletion diff ───────────────────────────────────────────────────
    incoming = [k for k, _ in blocks]
    if args.skip_live_check:
        print(
            "Skipping the live-rules diff (--skip-live-check). You are uploading "
            "blind: any rule not in this sheet will be deleted.\n"
        )
    else:
        current, current_pids = live_rule_keys(args.access_token, args.serial)
        incoming_set = set(incoming)
        current_set = set(current)
        dropped = [k for k in current if k not in incoming_set]
        added = [k for k in incoming if k not in current_set]
        kept = len(current_set & incoming_set)

        print(
            f"Live rules on LJ {args.serial}: {len(current)} location rule(s), "
            f"{current_pids} PID rule(s)\n"
            f"  kept    : {kept}\n"
            f"  added   : {len(added)}\n"
            f"  DROPPED : {len(dropped)}\n"
        )
        if dropped:
            print(
                f"  These {len(dropped)} location rule(s) are NOT in the sheet and "
                f"WILL BE DELETED:",
                file=sys.stderr,
            )
            for key in dropped:
                print(f"    selector={key[0]!r}  name={key[1]!r}  match={key[2]!r}",
                      file=sys.stderr)
            print(file=sys.stderr)
        for key in added:
            print(f"  + selector={key[0]!r}  match={key[2]!r}")
        if added:
            print()

    print(
        "Every surviving rule will be RENUMBERED — identifiers are derived from "
        "row order, so any externally held rule id becomes stale."
    )

    if args.dry_run or not args.yes:
        why = "--dry-run" if args.dry_run else "no --yes"
        print(f"\nNot uploaded ({why}). Re-run with --yes to apply.")
        if not args.skip_live_check:
            print(
                "Back up first if you have not: "
                "onping-mqtt-integrator-rules-export <token> "
                f"{args.serial} --out before-import.xlsx"
            )
        return

    resp = post_multipart_xlsx(
        args.access_token,
        endpoint("import_rules"),
        path.read_bytes(),
        filename=path.name,
        serial=args.serial,
    )
    report_write(resp, what=f"rules import for LJ {args.serial}")
    print(
        f"\nImported {len(blocks)} location rule(s) and {pid_rows} PID rule(s) "
        f"to LJ {args.serial}."
    )

    if args.execute:
        print("\nRunning the new rules against stored unprocessed data...")
        ex = post_empty(
            args.access_token, endpoint("execute_rules"), serial=args.serial
        )
        report_write(ex, what=f"rule execution on LJ {args.serial}")
        print(
            "Execution finished. Read the result with:\n"
            f"  onping-mqtt-integrator-reports <token> {args.serial} --latest"
        )
    else:
        print(
            "\nThe new rules are stored but have not run. They will fire on the "
            "next message if auto-execute is on; otherwise trigger them with "
            f"--execute or:\n"
            f"  onping-mqtt-integrator-reports <token> {args.serial} --execute --yes"
        )


if __name__ == "__main__":
    main()
