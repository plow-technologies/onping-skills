# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Manage OnPing Inferno ML models and local TorchScript uploads."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root

from _inferno_ml_routes.inferno_ml_models import (  # noqa: E402
    OnPingRequestError,
    default_model_card,
    delete_model,
    delete_model_version,
    emit_json,
    export_model_version,
    get_model,
    get_model_version,
    list_models,
    model_history,
    parse_categories,
    update_model,
    upload_model_version,
    create_model,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage OnPing Inferno ML models and local TorchScript versions."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    subparsers = parser.add_subparsers(dest="command", required=True)

    model_list = subparsers.add_parser("model-list", help="List available models")
    model_list.add_argument(
        "--name-filter",
        help="Case-insensitive substring filter applied to model names after fetch",
    )

    model_get = subparsers.add_parser("model-get", help="Fetch a single model")
    model_get.add_argument("--model-id", required=True, help="Parent model UUID")

    model_create = subparsers.add_parser("model-create", help="Create a parent model")
    model_create.add_argument("--name", required=True, help="Model name")
    model_create.add_argument("--gid", required=True, help="OnPing group ID")
    model_create.add_argument(
        "--visibility",
        default="VCObjectPrivate",
        help="Visibility value such as VCObjectPrivate or VCObjectPublic",
    )

    model_update = subparsers.add_parser(
        "model-update", help="Update model name, group, or visibility"
    )
    model_update.add_argument("--model-id", required=True, help="Parent model UUID")
    model_update.add_argument("--name", help="Updated model name")
    model_update.add_argument("--gid", help="Updated OnPing group ID")
    model_update.add_argument(
        "--visibility",
        help="Updated visibility value such as VCObjectPrivate or VCObjectPublic",
    )

    model_delete = subparsers.add_parser("model-delete", help="Delete a parent model")
    model_delete.add_argument("--model-id", required=True, help="Parent model UUID")

    model_hist = subparsers.add_parser(
        "model-history", help="Fetch full version history for a model"
    )
    model_hist.add_argument("--model-id", required=True, help="Parent model UUID")

    version_get = subparsers.add_parser(
        "version-get", help="Fetch a single model version"
    )
    version_get.add_argument("--version-id", required=True, help="Model version UUID")

    version_upload = subparsers.add_parser(
        "version-upload", help="Upload a local .pt file as a new model version"
    )
    version_upload.add_argument("--model-id", required=True, help="Parent model UUID")
    version_upload.add_argument("--file", required=True, help="Path to local .pt file")
    version_upload.add_argument("--version", required=True, help="Version string")
    version_upload.add_argument(
        "--description", required=True, help="Version description text"
    )
    version_upload.add_argument(
        "--card-summary", default="", help="Model card summary text"
    )
    version_upload.add_argument(
        "--card-evaluation", default="", help="Model card evaluation text"
    )
    version_upload.add_argument(
        "--card-uses", default="", help="Model card intended uses text"
    )
    version_upload.add_argument(
        "--card-datasets", default="", help="Model card datasets text"
    )
    version_upload.add_argument(
        "--card-metrics", default="", help="Model card metrics text"
    )
    version_upload.add_argument(
        "--card-categories",
        help="Comma-separated category IDs; defaults to 8 for inference models",
    )
    version_upload.add_argument(
        "--card-base-model", help="Optional base-model field for the model card"
    )

    version_delete = subparsers.add_parser(
        "version-delete", help="Delete a model version"
    )
    version_delete.add_argument("--version-id", required=True, help="Model version UUID")

    version_export = subparsers.add_parser(
        "version-export", help="Export a model version zip artifact"
    )
    version_export.add_argument("--version-id", required=True, help="Model version UUID")
    version_export.add_argument(
        "--out",
        help="Output path for the exported zip. Defaults to the server filename in the current directory.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "model-list":
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

        if args.command == "model-get":
            emit_json(get_model(args.access_token, args.model_id))
            return 0

        if args.command == "model-create":
            print(
                create_model(
                    args.access_token,
                    name=args.name,
                    gid=args.gid,
                    visibility=args.visibility,
                )
            )
            return 0

        if args.command == "model-update":
            emit_json(
                update_model(
                    args.access_token,
                    model_id=args.model_id,
                    name=args.name,
                    gid=args.gid,
                    visibility=args.visibility,
                )
            )
            return 0

        if args.command == "model-delete":
            delete_model(args.access_token, args.model_id)
            emit_json({"deleted": args.model_id, "kind": "model"})
            return 0

        if args.command == "model-history":
            emit_json(model_history(args.access_token, args.model_id))
            return 0

        if args.command == "version-get":
            emit_json(get_model_version(args.access_token, args.version_id))
            return 0

        if args.command == "version-upload":
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

        if args.command == "version-delete":
            delete_model_version(args.access_token, args.version_id)
            emit_json({"deleted": args.version_id, "kind": "model-version"})
            return 0

        if args.command == "version-export":
            output_path = Path(args.out) if args.out else None
            exported = export_model_version(
                args.access_token,
                version_id=args.version_id,
                output_path=output_path,
            )
            emit_json({"exported": str(exported), "version_id": args.version_id})
            return 0

        parser.error(f"Unhandled command: {args.command}")
        return 2
    except OnPingRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
