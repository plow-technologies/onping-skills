# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read an OnPing line-graph widget's JSON representation by id.

Mirrors the OnPing frontend's widget-load call: `GET /content/widgets/line-graph/widget/{id}`
returns the raw `LineGraphWidget` JSON (title, timePeriod, timeUnit, yAxes,
eventParameters, maxStep, normalizeValue, latestValueLine, legendWithCurrentValue,
dashboardId?). `dashboardId` is absent for orphaned widgets (not yet attached).

Read-only — no `--yes` gate. Wire-level `pid` is a bare integer (Dhall's
`{type, value}` record is flattened on serialization).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _line_graph_routes.line_graph_http import get_json
from _line_graph_routes.routes import ROUTES


def main() -> None:
    p = argparse.ArgumentParser(
        description="Get an OnPing line-graph widget as JSON via "
        "GET /content/widgets/line-graph/widget/{id}. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("widget_id", help="LineGraphWidgetId (Mongo `o…` id)")
    p.add_argument("--output", help="output file path (also prints to stdout)")
    p.add_argument("--pretty", action="store_true", help="pretty-print JSON (2-space indent)")
    args = p.parse_args()

    body = get_json(args.access_token, ROUTES["get"]["endpoint"], widget_id=args.widget_id)

    rendered = json.dumps(body, indent=2 if args.pretty else None, sort_keys=args.pretty)

    if args.output:
        Path(args.output).write_text(rendered + "\n")
        print(f"Saved widget {args.widget_id} to {args.output}", file=sys.stderr)

    print(rendered)


if __name__ == "__main__":
    main()
