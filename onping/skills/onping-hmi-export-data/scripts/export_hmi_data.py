# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export an OnPing HMI's data-binding mappings to a Dhall file.

`GET /hmi/export-data/{uuid}` returns only the HMI's data bindings — a Dhall
`[DataImport]` list, each `{ from: { onpingKey, description }, to: Maybe onpingKey }`
— NOT the full dashboard layout (`Content-Type: text/x-dhall`,
`filename="hmi-data.dhall"`). Use this to transfer/re-point which OnPing
parameters an HMI reads without touching its visual design.

Read-only — no `--yes` gate. The Dhall this emits is imported back into a target
HMI by `onping-hmi-import-data`. For the FULL dashboard (layout + everything),
use `onping-hmi-export`. Requires **Write** permission on the HMI UUID.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _hmi_routes.hmi_http import get_dhall
from _hmi_routes.routes import ROUTES


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export an OnPing HMI's data-binding mappings to Dhall via "
        "GET /hmi/export-data/{uuid}. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("uuid", help="HMI dashboard UUID whose data bindings to export")
    p.add_argument("--output", help="output file path (also prints to stdout)")
    args = p.parse_args()

    dhall_text = get_dhall(args.access_token, ROUTES["export-data"]["endpoint"], uuid=args.uuid)

    # Write only after a confirmed 200 non-HTML response.
    if args.output:
        Path(args.output).write_text(dhall_text)
        print(f"Exported HMI {args.uuid} data bindings to {args.output}", file=sys.stderr)

    print(dhall_text)


if __name__ == "__main__":
    main()
