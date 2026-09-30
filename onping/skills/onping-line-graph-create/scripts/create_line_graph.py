# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Mint a fresh empty OnPing line-graph widget.

Wraps `POST /content/widgets/line-graph/config` — server accepts an empty body
and returns the new `LineGraphWidgetId` (a Mongo `o…` id) as a JSON-quoted string.

MUTATING: `--yes`-gated. Even though the resulting widget is empty, it's a
write, and there is no delete route for line-graph widgets — a wrongly-minted
widget can only be cleaned up by deleting its parent dashboard, and this widget
isn't attached to one yet. Use `-import --new` for the atomic
mint-then-populate flow.

Server defaults for the new widget (LineGraphWidget.hs):
- title = "New Chart"
- timePeriod = 3, timeUnit = Hour, updateInterval = 60
- one YAxis (linear, no parameters), no eventParameters
- maxStep = 0, normalizeValue = False
- latestValueLine = Just False, legendWithCurrentValue = False
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _line_graph_routes.line_graph_http import _fail, extract_error, post_empty
from _line_graph_routes.routes import ROUTES


DEFAULTS = """\
Server defaults for a freshly minted widget:
  title           = "New Chart"
  timePeriod      = 3
  timeUnit        = "hour"
  updateInterval  = 60
  yAxes           = [ one linear axis with no parameters ]
  eventParameters = []
  maxStep         = 0
  normalizeValue  = False
  latestValueLine = Just False
  legendWithCurrentValue = False

The widget is NOT attached to a dashboard. To make it visible, wire the id into
an HMI panel config, or use `-import --new` for the mint-then-populate flow.

There is NO delete route: a wrongly-minted widget can only be cleaned up by
deleting the parent dashboard once it's attached, or left orphaned.
"""


def main() -> None:
    p = argparse.ArgumentParser(
        description="Mint a fresh empty OnPing line-graph widget via "
        "POST /content/widgets/line-graph/config. MUTATING; requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("--yes", action="store_true", help="perform the mint (required to write)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit preview (default when --yes is not passed); wins over --yes",
    )
    args = p.parse_args()

    if args.dry_run or not args.yes:
        print("PREVIEW — would mint a fresh line-graph widget.")
        print()
        print(DEFAULTS)
        print(
            "No write performed. Re-run with --yes to mint.\n"
            "  (--dry-run wins over --yes if both are passed.)"
        )
        return

    resp = post_empty(args.access_token, ROUTES["config"]["endpoint"])
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code}: {extract_error(resp)}")
    try:
        widget_id = resp.json()
    except ValueError:
        _fail(f"Expected JSON id but could not parse response:\n{resp.text[:500]}")
    if not isinstance(widget_id, str):
        _fail(f"Expected a JSON string widget id, got: {widget_id!r}")

    print(widget_id)


if __name__ == "__main__":
    main()
