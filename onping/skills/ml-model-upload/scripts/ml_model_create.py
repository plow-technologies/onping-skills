# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Compatibility wrapper for creating an OnPing ML model record."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root

from _inferno_ml_routes.inferno_ml_models import OnPingRequestError, create_model  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an OnPing ML model record.")
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument("--name", required=True, help="Model name")
    parser.add_argument("--gid", required=True, help="OnPing group ID")
    parser.add_argument(
        "--visibility",
        default="VCObjectPrivate",
        help="Visibility value such as VCObjectPrivate or VCObjectPublic",
    )
    args = parser.parse_args(argv)

    try:
        print(
            create_model(
                args.access_token,
                name=args.name,
                gid=args.gid,
                visibility=args.visibility,
            )
        )
        return 0
    except OnPingRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
