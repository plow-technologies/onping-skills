# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read mqtt-json-integrator rule-execution reports, and trigger an execution.

Routes: GET    /mqtt/json/integrator/{serial}/execute/rules/report
        DELETE /mqtt/json/integrator/{serial}/execute/rules/report
        POST   /mqtt/json/integrator/{serial}/generation/rules/execute

THIS IS THE ONLY PLACE RULE-EXECUTION ERRORS SURFACE. The execute route returns
an empty success envelope regardless of what happened — it does not report
matches, failures, or counts. Everything you learn about an execution comes from
the report it leaves behind, so the useful sequence is:

    --execute --yes   then   (re-run with no flags to read the new report)

REPORT FIELDS (ExecuteRulesReport, verified against
mqtt-json-integrator-types/golden/ExecuteRulesReport/ExecuteRulesReport.json):
    executeRulesReportSource                 "ExecuteRulesManual" |
                                             "ExecuteRulesAutomatic" (bare string)
    executeRulesReportExecuteTime            ISO-8601 UTC
    executeRulesCount                        rules evaluated
    executeRulesNewUncreatedLocationsCount   NEW uncreated locations produced
    executeRulesNewUncreatedPidsCount        NEW uncreated PIDs produced
    executeRulesErrors                       [text]

"NEW" IS THE KEY WORD. The counts report only what this run ADDED. A run over
data whose objects were already generated legitimately reports 0/0 — that means
"nothing new", not "nothing matched". A first run against fresh data reporting
0/0 with no errors means the rules matched nothing.

--execute IS BLOCKING AND SERIALIZED SERVER-SIDE. The server refuses concurrent
executions; a large queue with many rules can take a while. It runs all stored
rules against all stored unprocessed data. It creates NOTHING in OnPing — it only
produces uncreated candidates (see onping-mqtt-integrator-create for the step
that does create).

--delete-all CLEARS EVERY REPORT. There is no per-report delete. Note this is the
one integrator mutation that is a real HTTP DELETE; every other one is a POST.

Source of truth (re-verify if these drift):
  - Handlers: onping/Handler/MqttJsonIntegrator/Service.hs (GET),
              :281 (DELETE), :265 (execute)
  - Type:     mqtt-json-integrator-types/.../Types.hs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _mqtt_integrator_routes.integrator_http import (
    _fail,
    delete,
    get_json,
    post_empty,
    report_write,
)
from _mqtt_integrator_routes.routes import endpoint

SOURCE_LABEL = {
    "ExecuteRulesManual": "manual",
    "ExecuteRulesAutomatic": "automatic",
}


def fetch(token: str, serial: str) -> list:
    reports = get_json(token, endpoint("get_reports"), serial=serial)
    if not isinstance(reports, list):
        _fail(f"Expected a report array, got: {json.dumps(reports)[:400]}")
    return reports


def sort_key(r: dict):
    return str(r.get("executeRulesReportExecuteTime") or "")


def print_report(r: dict, *, indent: str = "  ") -> None:
    src = r.get("executeRulesReportSource")
    when = r.get("executeRulesReportExecuteTime")
    errors = r.get("executeRulesErrors") or []
    locs = r.get("executeRulesNewUncreatedLocationsCount")
    pids = r.get("executeRulesNewUncreatedPidsCount")
    print(
        f"{indent}{when}  ({SOURCE_LABEL.get(src, src)})\n"
        f"{indent}    rules evaluated      : {r.get('executeRulesCount')}\n"
        f"{indent}    NEW uncreated locs   : {locs}\n"
        f"{indent}    NEW uncreated PIDs   : {pids}"
    )
    if errors:
        print(f"{indent}    errors ({len(errors)}):")
        for e in errors:
            for line in str(e).splitlines():
                print(f"{indent}      {line}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Read mqtt-json-integrator rule-execution reports — the only place "
            "execution errors surface. --execute triggers a run; --delete-all "
            "clears the history."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument("--json", action="store_true", help="emit the raw report array")
    p.add_argument(
        "--latest",
        action="store_true",
        help="show only the most recent report (by execute time)",
    )
    p.add_argument(
        "--errors-only",
        action="store_true",
        help="show only reports that recorded at least one error; exits 1 if any "
        "are found, so it can gate a pipeline",
    )
    p.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="show at most the N most recent reports",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="run all stored rules against all stored unprocessed data. "
        "Blocking and serialized server-side. Creates nothing in OnPing — it "
        "only produces uncreated candidates. Requires --yes.",
    )
    p.add_argument(
        "--delete-all",
        action="store_true",
        help="DESTRUCTIVE: clear ALL execution reports (no per-report delete "
        "exists). Requires --yes.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report what --execute/--delete-all would do and stop (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually perform the action")
    args = p.parse_args()

    gated = args.execute or args.delete_all

    # ── mutation paths ──────────────────────────────────────────────────────
    if gated:
        existing = fetch(args.access_token, args.serial)
        if args.execute:
            print(
                f"--execute would run all stored generation rules against all "
                f"stored unprocessed data on LJ {args.serial}.\n"
                f"  It is blocking and serialized server-side, and may take a "
                f"while on a large queue.\n"
                f"  It creates NOTHING in OnPing — it produces uncreated "
                f"candidates only.\n"
                f"  A new report will be appended to the {len(existing)} "
                f"already stored."
            )
        if args.delete_all:
            print(
                f"--delete-all would clear ALL {len(existing)} execution "
                f"report(s) for LJ {args.serial}. There is no per-report delete "
                f"and no undo."
            )

        if args.dry_run or not args.yes:
            why = "--dry-run" if args.dry_run else "no --yes"
            print(f"\nNothing done ({why}). Re-run with --yes to apply.")
            return

        if args.execute:
            resp = post_empty(
                args.access_token, endpoint("execute_rules"), serial=args.serial
            )
            report_write(resp, what=f"rule execution on LJ {args.serial}")
            print("\nExecution finished. Fetching the resulting report...\n")
            after = fetch(args.access_token, args.serial)
            fresh = sorted(after, key=sort_key)
            if len(after) > len(existing) and fresh:
                print_report(fresh[-1])
                errs = fresh[-1].get("executeRulesErrors") or []
                if errs:
                    print(
                        "\nThe execution recorded errors (above). The rules ran "
                        "but did not fully succeed."
                    )
                    sys.exit(1)
                if not (
                    fresh[-1].get("executeRulesNewUncreatedLocationsCount")
                    or fresh[-1].get("executeRulesNewUncreatedPidsCount")
                ):
                    print(
                        "\nNo NEW objects were produced. That is expected if this "
                        "data had already been processed; if it is fresh data, the "
                        "rules matched nothing — check "
                        "onping-mqtt-integrator-unprocessed --show 3 against your "
                        "selectors."
                    )
            else:
                print(
                    "No new report appeared. The server may have refused a "
                    "concurrent execution; re-read reports in a moment."
                )
            return

        resp = delete(
            args.access_token, endpoint("delete_reports"), serial=args.serial
        )
        report_write(resp, what=f"report deletion for LJ {args.serial}")
        print(f"\nCleared all execution reports for LJ {args.serial}.")
        return

    # ── read path ───────────────────────────────────────────────────────────
    reports = fetch(args.access_token, args.serial)
    ordered = sorted(reports, key=sort_key, reverse=True)

    if args.errors_only:
        ordered = [r for r in ordered if (r.get("executeRulesErrors") or [])]
    if args.latest:
        ordered = ordered[:1]
    elif args.limit:
        ordered = ordered[: args.limit]

    if args.json:
        print(json.dumps(ordered, indent=2, sort_keys=True))
    else:
        total = len(reports)
        shown = len(ordered)
        label = " with errors" if args.errors_only else ""
        print(
            f"mqtt-json-integrator execution reports for LJ {args.serial} — "
            f"{shown}{label} of {total} shown (newest first)\n"
        )
        if not ordered:
            if args.errors_only:
                print("  No report recorded any errors.")
            elif total == 0:
                print(
                    "  No reports at all. The rules have never run on this LJ — "
                    "either mqttConfigExecuteRulesOnMessageReceive is off and no "
                    "manual run has happened, or the reports were cleared.\n"
                    "  Trigger one with --execute --yes."
                )
        for r in ordered:
            print_report(r)
            print()

    if args.errors_only and ordered:
        sys.exit(1)


if __name__ == "__main__":
    main()
