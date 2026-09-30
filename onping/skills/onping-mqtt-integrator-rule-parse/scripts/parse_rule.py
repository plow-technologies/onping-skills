# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Validate an mqtt-json-integrator generation-rule expression against OnPing.

Routes: POST /mqtt/json/integrator/rule/parse       (full grammar)
        POST /mqtt/json/integrator/jq/rule/parse    (JQ-only subset)

Read-only and STATELESS. Neither route is scoped to a Lumberjack and neither
touches stored rules, unprocessed data, or artifacts — they only answer "would
the server accept this expression?". Use before committing a sheet via
onping-mqtt-integrator-rules-import, whose failure mode is otherwise a 400 with
a megaparsec dump.

REQUEST BODY IS A BARE JSON STRING, not an object. The handler does
`requireInsecureJsonBody :: Handler Text`, so the body is e.g.
    "{topic|s#/([^/]*)/.*#\\1#}"
quotes included. Posting {"rule": "..."} yields a 400.

A PARSE FAILURE IS REPORTED AS HTTP 200. The response is a RulesParseResult:
    {"tag": "ParsedRulesSuccesfully"}                  -- note the misspelling
    {"tag": "FailedToParseRules", "contents": "<err>"}
so status alone tells you nothing. This script exits 1 on FailedToParseRules so
it can gate a pipeline.

WHICH ROUTE TO USE:
  --full (default)  Rules.parseRules — accepts the whole grammar: static text,
                    {topic|s#pat#rep#} sed substitutions, {jq} expressions, and
                    {jq} with template fields. This is what columns 2, 3, 5 and
                    8 of the rules sheet hold (Location Name, Location Match,
                    PID Topic, PID Description).
  --jq-only         Rules.parseRuleJqOnly — rejects the sed/topic forms. This is
                    what columns 6 and 9 hold (PID Time, PID Value), which must
                    be plain JQ selectors.

Source of truth (re-verify if these drift):
  - Handlers:  onping/Handler/MqttJsonIntegrator/Service.hs
               (postMqttJsonIntegratorParseRuleR) and :296
               (postMqttJsonIntegratorParseJqRuleR)
  - Parser:    mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types/Rules/Parse.hs
  - Result:    onping-frontend-types/src/OnPing/Frontend/Types/MqttJsonIntegrator.hs
  - Grammar:   mqtt-json-integrator/README.md, "SED Expression Guide"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _mqtt_integrator_routes.integrator_http import _fail, post_json
from _mqtt_integrator_routes.routes import endpoint

SUCCESS_TAG = "ParsedRulesSuccesfully"  # sic — misspelled server-side
FAILURE_TAG = "FailedToParseRules"


def parse_one(token: str, rule: str, *, jq_only: bool) -> tuple[bool, str]:
    """POST one rule string; return (ok, detail)."""
    key = "parse_jq_rule" if jq_only else "parse_rule"
    resp = post_json(token, endpoint(key), rule)

    if not (200 <= resp.status_code < 300):
        _fail(
            f"HTTP {resp.status_code} from {endpoint(key)}:\n{resp.text[:600]}\n"
            f"(the body must be a bare JSON string, e.g. \"{rule[:40]}\")"
        )

    try:
        payload = resp.json()
    except ValueError:
        _fail(f"Expected a RulesParseResult but could not parse:\n{resp.text[:600]}")

    if isinstance(payload, dict) and "error" in payload and len(payload) == 1:
        _fail(f"OnPing returned an error: {payload['error']}")

    tag = payload.get("tag") if isinstance(payload, dict) else None
    if tag == SUCCESS_TAG:
        return True, ""
    if tag == FAILURE_TAG:
        return False, str(payload.get("contents", "")).strip()
    _fail(f"Unrecognized RulesParseResult shape: {json.dumps(payload)[:600]}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Validate mqtt-json-integrator rule expressions. Read-only and "
            "stateless — no Lumberjack serial required."
        ),
        epilog=(
            "Examples:\n"
            "  parse_rule.py $TOKEN '{topic|s#/([^/]*)/.*#\\1#}'\n"
            "  parse_rule.py $TOKEN --jq-only '.temperature'\n"
            "  parse_rule.py $TOKEN --file rules.txt   # one expression per line\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument(
        "rule",
        nargs="*",
        help="one or more rule expressions to validate (quote them — they "
        "contain braces, # and backslashes the shell would eat)",
    )
    p.add_argument(
        "--file",
        help="read expressions from a file, one per line (blank lines and "
        "lines starting with # are skipped)",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--full",
        action="store_true",
        help="validate against the full grammar: static text + sed + JQ "
        "(default). Use for Location Name/Match, PID Topic, PID Description.",
    )
    mode.add_argument(
        "--jq-only",
        action="store_true",
        help="validate as a plain JQ selector, rejecting sed/topic forms. "
        "Use for PID Time and PID Value.",
    )
    p.add_argument("--json", action="store_true", help="emit results as JSON")
    args = p.parse_args()

    rules: list[str] = list(args.rule)
    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            _fail(f"Could not read --file {args.file}: {e}")
        rules += [
            line.rstrip("\n")
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    if not rules:
        _fail("No expressions given — pass them as arguments or via --file.")

    results = []
    for rule in rules:
        ok, detail = parse_one(args.access_token, rule, jq_only=args.jq_only)
        results.append({"rule": rule, "ok": ok, "error": detail})

    failures = [r for r in results if not r["ok"]]

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "jq-only" if args.jq_only else "full",
                    "checked": len(results),
                    "failed": len(failures),
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        mode_label = "JQ-only" if args.jq_only else "full grammar"
        print(f"Validated {len(results)} expression(s) against the {mode_label} parser.\n")
        for r in results:
            if r["ok"]:
                print(f"  OK    {r['rule']}")
            else:
                print(f"  FAIL  {r['rule']}")
                for line in r["error"].splitlines():
                    print(f"          {line}")
        if failures:
            print(f"\n{len(failures)} of {len(results)} expression(s) failed to parse.")
        else:
            print(f"\nAll {len(results)} expression(s) parse.")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
