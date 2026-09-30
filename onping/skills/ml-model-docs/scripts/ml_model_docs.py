# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Update OnPing Inferno ML model-version documentation fields."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root

from _inferno_ml_routes.inferno_ml_models import (  # noqa: E402
    MISSING,
    OnPingRequestError,
    emit_json,
    get_model_version,
    parse_categories,
    update_version_docs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show or update documentation fields for an OnPing model version."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="Show the current model-version metadata")
    show.add_argument("--version-id", required=True, help="Model version UUID")

    update = subparsers.add_parser(
        "update",
        help="Update version text or model-card fields while preserving other metadata",
    )
    update.add_argument("--version-id", required=True, help="Model version UUID")
    update.add_argument("--description", help="New version description")
    update.add_argument("--version", help="New version string such as v1.2.3")
    update.add_argument("--card-summary", help="New model-card summary text")
    update.add_argument("--card-evaluation", help="New model-card evaluation text")
    update.add_argument("--card-uses", help="New model-card uses text")
    update.add_argument("--card-datasets", help="New model-card datasets text")
    update.add_argument("--card-metrics", help="New model-card metrics text")
    update.add_argument(
        "--card-categories",
        help="Replace model-card categories with a comma-separated integer list. Use an empty string to clear.",
    )
    update.add_argument("--card-base-model", help="Set the optional base-model field")
    update.add_argument(
        "--clear-base-model",
        action="store_true",
        help="Remove the optional base-model field from the model card",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "show":
            emit_json(get_model_version(args.access_token, args.version_id))
            return 0

        if args.command == "update":
            if args.card_base_model is not None and args.clear_base_model:
                raise OnPingRequestError(
                    "Use either --card-base-model or --clear-base-model, not both."
                )

            categories = parse_categories(args.card_categories)
            base_model = MISSING
            if args.clear_base_model:
                base_model = None
            elif args.card_base_model is not None:
                base_model = args.card_base_model

            emit_json(
                update_version_docs(
                    args.access_token,
                    version_id=args.version_id,
                    description=(
                        args.description if args.description is not None else MISSING
                    ),
                    version=args.version if args.version is not None else MISSING,
                    summary=(
                        args.card_summary if args.card_summary is not None else MISSING
                    ),
                    evaluation=(
                        args.card_evaluation
                        if args.card_evaluation is not None
                        else MISSING
                    ),
                    uses=args.card_uses if args.card_uses is not None else MISSING,
                    datasets=(
                        args.card_datasets
                        if args.card_datasets is not None
                        else MISSING
                    ),
                    metrics=(
                        args.card_metrics if args.card_metrics is not None else MISSING
                    ),
                    categories=categories if args.card_categories is not None else MISSING,
                    base_model=base_model,
                )
            )
            return 0

        parser.error(f"Unhandled command: {args.command}")
        return 2
    except OnPingRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
