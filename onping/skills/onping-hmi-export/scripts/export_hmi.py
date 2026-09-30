# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export a full OnPing HMI dashboard to a Dhall file.

Mirrors the OnPing web UI's HMI export: `GET /hmi/export/{uuid}` returns the
complete `HmiDashboard` (id, name, all components, settings, alert config) as a
Dhall document (`Content-Type: text/x-dhall`, `filename="hmi.dhall"`).

Read-only — no `--yes` gate. The Dhall this emits is imported back by
`onping-hmi-import` (the round-trip). Use `onping-hmi-list` to discover HMI
UUIDs. Requires **Write** permission on the HMI UUID (the export handler gates
on Write, matching the OnPing UI).
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
        description="Export a full OnPing HMI dashboard to Dhall via "
        "GET /hmi/export/{uuid}. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("uuid", help="HMI dashboard UUID to export")
    p.add_argument("--output", help="output file path (also prints to stdout)")
    args = p.parse_args()

    dhall_text = get_dhall(args.access_token, ROUTES["export"]["endpoint"], uuid=args.uuid)

    # Write to the output file only after a confirmed 200 non-HTML response, so a
    # failure never clobbers an existing backup.
    if args.output:
        Path(args.output).write_text(dhall_text)
        print(f"Exported HMI {args.uuid} to {args.output}", file=sys.stderr)

    print(dhall_text)


if __name__ == "__main__":
    main()
