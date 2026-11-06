# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Download the OnPing dnp3 driver tag export to a local .xlsx file."""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _driver_export_routes.download import download_export
from _driver_export_routes.routes import ROUTES
from _token_input import shapes, token_source

DRIVER = "dnp3"


def _utc_stamp() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Download OnPing {DRIVER} tag export as XLSX.",
    )
    parser.add_argument("location_id", nargs="?", help="path-param int (LocationIdRef, or LJSerial for sparkplug-bridge)", type=shapes.int_arg)
    parser.add_argument("filename", nargs="?", default="tags.xlsx", help="path-param string forwarded to OnPing (default: tags.xlsx)")
    parser.add_argument("--output", help="local output path (default: ./<driver>-<id>-<UTC>.xlsx)")

    args = token_source.parse(parser, None, is_id=shapes.is_int)

    entry = ROUTES[DRIVER]
    variant_key = None

    if variant_key is not None:
        route = entry["variants"][variant_key]
    else:
        route = entry

    endpoint = route["endpoint"]
    needs_id = "{location_id}" in endpoint or "{lumberjack_serial}" in endpoint
    needs_filename = "{filename}" in endpoint

    if needs_id and args.location_id is None:
        parser.error("location_id (or lumberjack_serial) is required for this route")

    # Compose URL path from endpoint pattern. Endpoint is "GET /path/..."; strip the method.
    path = endpoint.split(" ", 1)[1]
    loc = "" if args.location_id is None else str(args.location_id)
    path = path.replace("{location_id}", loc)
    path = path.replace("{lumberjack_serial}", loc)
    path = path.replace("{filename}", args.filename or "tags.xlsx")

    if args.output:
        out = args.output
    else:
        id_part = args.location_id if needs_id else (variant_key or "all")
        out = f"./{DRIVER}-{id_part}-{_utc_stamp()}.xlsx"

    resolved = download_export(args.access_token, path, out)
    print(resolved)


if __name__ == "__main__":
    main()
