# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export an OnPing line-graph widget to a Dhall file.

Mirrors the OnPing frontend's line-graph export: a single
`GET /content/widgets/line-graph/export/{id}` returns the full
`ExportedLineGraphWidget` as Dhall (`Content-Type: text/x-dhall`,
`Content-Disposition: attachment`).

Read-only — no `--yes` gate. The Dhall this emits is imported back verbatim by
`onping-line-graph-import` (the round-trip is lossless). Distinct from
`onping-line-graph-export-data`, which returns a bare `[Field]` list — feeding
that into `-import` yields a 400 Dhall type error.
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
        description="Export an OnPing line-graph widget to Dhall via "
        "GET /content/widgets/line-graph/export/{id}. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("widget_id", help="LineGraphWidgetId (Mongo `o…` id)")
    p.add_argument("--output", help="output file path (also prints to stdout)")
    args = p.parse_args()

    dhall_text = get_dhall(
        args.access_token, ROUTES["export"]["endpoint"], widget_id=args.widget_id
    )

    # Defensive: /export should always emit a Dhall record starting with `{`.
    if not dhall_text.lstrip().startswith("{"):
        _fail(
            "Expected a Dhall ExportedLineGraphWidget record (body starting "
            f"with '{{'), got:\n{dhall_text[:200]}"
        )

    if args.output:
        Path(args.output).write_text(dhall_text)
        print(f"Exported widget {args.widget_id} to {args.output}", file=sys.stderr)

    print(dhall_text)


if __name__ == "__main__":
    main()
