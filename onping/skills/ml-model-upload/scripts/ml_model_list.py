# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Compatibility wrapper for listing OnPing ML models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root

from _inferno_ml_routes.inferno_ml_models import OnPingRequestError, emit_json, list_models  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List OnPing ML models and their versions."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument(
        "--name-filter",
        help="Filter models by name using a case-insensitive substring match",
    )
    args = parser.parse_args(argv)

    try:
        data = list_models(args.access_token)
        if args.name_filter:
            needle = args.name_filter.lower()
            data = [
                item
                for item in data
                if needle in item.get("model", {}).get("name", "").lower()
            ]
        emit_json(data)
        return 0
    except OnPingRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
