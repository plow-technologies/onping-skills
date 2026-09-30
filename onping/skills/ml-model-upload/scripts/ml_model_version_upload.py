# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Compatibility wrapper for uploading a TorchScript model version."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root

from _inferno_ml_routes.inferno_ml_models import (  # noqa: E402
    OnPingRequestError,
    default_model_card,
    parse_categories,
    upload_model_version,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload a TorchScript model version to OnPing."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument("--model-id", required=True, help="Parent model UUID")
    parser.add_argument("--file", required=True, help="Path to local .pt file")
    parser.add_argument("--version", required=True, help="Version string")
    parser.add_argument("--description", required=True, help="Version description")
    parser.add_argument("--card-summary", default="", help="Model card summary text")
    parser.add_argument(
        "--card-evaluation", default="", help="Model card evaluation text"
    )
    parser.add_argument("--card-uses", default="", help="Model card uses text")
    parser.add_argument("--card-datasets", default="", help="Model card datasets text")
    parser.add_argument("--card-metrics", default="", help="Model card metrics text")
    parser.add_argument(
        "--card-categories",
        help="Comma-separated category IDs; defaults to 8 for inference models",
    )
    parser.add_argument("--card-base-model", help="Optional base-model field")
    args = parser.parse_args(argv)

    try:
        categories = parse_categories(args.card_categories)
        if categories is None:
            categories = [8]

        card = default_model_card(categories=categories)
        card["summary"]["summary"] = args.card_summary
        card["summary"]["evaluation"] = args.card_evaluation
        card["summary"]["uses"] = args.card_uses
        card["metadata"]["datasets"] = args.card_datasets
        card["metadata"]["metrics"] = args.card_metrics
        if args.card_base_model:
            card["metadata"]["base-model"] = args.card_base_model

        print(
            upload_model_version(
                args.access_token,
                model_id=args.model_id,
                file_path=Path(args.file),
                version=args.version,
                description=args.description,
                card=card,
            )
        )
        return 0
    except OnPingRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
