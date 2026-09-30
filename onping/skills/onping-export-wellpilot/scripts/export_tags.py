# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Download the OnPing wellpilot driver tag export to a local .xlsx file."""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _driver_export_routes.download import download_export
from _driver_export_routes.routes import ROUTES

DRIVER = "wellpilot"


def _utc_stamp() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Download OnPing {DRIVER} tag export as XLSX.",
    )
    parser.add_argument("access_token", help="OnPing OAuth bearer token")
    parser.add_argument("location_id", nargs="?", help="path-param int (LocationIdRef, or LJSerial for sparkplug-bridge)")
    parser.add_argument("filename", nargs="?", default="tags.xlsx", help="path-param string forwarded to OnPing (default: tags.xlsx)")
    parser.add_argument("--output", help="local output path (default: ./<driver>-<id>-<UTC>.xlsx)")
    parser.add_argument("--cards", action="store_true", help="Export pump cards instead of parameter tags")
    args = parser.parse_args()

    entry = ROUTES[DRIVER]
    variant_key = None
    if getattr(args, "cards", False):
        variant_key = "cards"
    if variant_key is not None:
        route = entry["variants"][variant_key]
    else:
        route = entry

    endpoint = route["endpoint"]
    needs_id = "{location_id}" in endpoint or "{lumberjack_serial}" in endpoint
    needs_filename = "{filename}" in endpoint

    if needs_id and not args.location_id:
        parser.error("location_id (or lumberjack_serial) is required for this route")

    # Compose URL path from endpoint pattern. Endpoint is "GET /path/..."; strip the method.
    path = endpoint.split(" ", 1)[1]
    path = path.replace("{location_id}", args.location_id or "")
    path = path.replace("{lumberjack_serial}", args.location_id or "")
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
