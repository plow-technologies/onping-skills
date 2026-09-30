# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export an OnPing line-graph widget's pid bindings as a Dhall [Field] list.

Mirrors the OnPing frontend's data-only export: a single
`GET /content/widgets/line-graph/export-data-only/{id}` returns the widget's
pid bindings — a Dhall `[Field]` list of `{from: {onpingKey, description}, to: Optional {type, value}}`
records, one per y-axis parameter and event parameter that has a set pid — as
`application/vnd.plow.haskell-type+dhall`.

Read-only — no `--yes` gate. Distinct shape from `onping-line-graph-export`; the
list this emits is the input for `onping-line-graph-import-data` (remap the `to`
fields to remap pids), NOT `onping-line-graph-import` (which needs a record).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _line_graph_routes.line_graph_http import _fail, get_dhall
from _line_graph_routes.routes import ROUTES


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export an OnPing line-graph widget's pid bindings to Dhall via "
        "GET /content/widgets/line-graph/export-data-only/{id}. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("widget_id", help="LineGraphWidgetId (Mongo `o…` id)")
    p.add_argument("--output", help="output file path (also prints to stdout)")
    args = p.parse_args()

    dhall_text = get_dhall(
        args.access_token, ROUTES["export-data"]["endpoint"], widget_id=args.widget_id
    )

    # Defensive: /export-data-only should always emit a Dhall list starting with `[`.
    if not dhall_text.lstrip().startswith("["):
        _fail(
            "Expected a Dhall [Field] list (body starting with '['), got:\n"
            f"{dhall_text[:200]}"
        )

    if args.output:
        Path(args.output).write_text(dhall_text)
        print(
            f"Exported widget {args.widget_id} pid bindings to {args.output}",
            file=sys.stderr,
        )

    print(dhall_text)


if __name__ == "__main__":
    main()
