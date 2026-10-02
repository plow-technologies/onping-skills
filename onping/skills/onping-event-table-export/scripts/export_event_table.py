# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export an OnPing event table as Dhall by UUID.

`GET /event/table/export/<file>.dhall?eventTableUUID=<uuid>` returns the
`EventTableConfiguration` as Dhall. The path segment only names the download;
the server reads the UUID from the query parameter. Read-only — no `--yes` gate.

The output file is written only after a successful, non-HTML response, through a
temporary file, so a failed export never replaces an existing file.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _event_table_routes.event_table_http import EventTableError, die, get_text
from _event_table_routes.routes import ROUTES


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export an OnPing event table as Dhall via "
        "GET /event/table/export/<file>?eventTableUUID=<uuid>. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("uuid", help="event-table UUID (from onping-event-table-list)")
    p.add_argument("--output", required=True, help="Dhall file to write")
    args = p.parse_args()

    out = Path(args.output)
    try:
        dhall = get_text(
            args.access_token,
            ROUTES["export"]["endpoint"],
            path_params={"filename": out.name if out.suffix == ".dhall" else "exportedEventTable.dhall"},
            params={"eventTableUUID": args.uuid},
        )
    except EventTableError as err:
        die(err)

    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(dhall if dhall.endswith("\n") else dhall + "\n")
    os.replace(tmp, out)
    print(f"Saved event table {args.uuid} to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
