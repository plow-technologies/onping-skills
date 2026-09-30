# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List, fetch, and update OnPing Inferno inference (ml-) parameters.

Update semantics are strict read-modify-write: the current parameter is
fetched from `/inferno/ml/inference/list/script/with-sources/{hash}` before
any edits are applied. `update` defaults to dry-run; pass `--apply` to issue
the PUT.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root

from _inferno_ml_routes.inferno_ml_models import (  # noqa: E402
    OnPingRequestError,
    emit_json,
    get_inference_param,
    get_inference_param_with_sources,
    list_inference_params,
    list_inference_params_by_script,
    restore_inference_param_from_export,
    update_inference_param,
)


def _filter_params(
    entries: list[dict],
    *,
    script_hash: str | None,
    name_filter: str | None,
) -> list[dict]:
    result = entries
    if script_hash:
        result = [e for e in result if e.get("param", {}).get("script") == script_hash]
    if name_filter:
        needle = name_filter.lower()
        result = [e for e in result if needle in e.get("name", "").lower()]
    return result


def _render_list(entries: list[dict]) -> None:
    if not entries:
        print("(no inference parameters match)")
        return
    for e in entries:
        p = e.get("param", {})
        line = (
            f"{e.get('id','?'):36}  "
            f"active={str(e.get('active','?')):5}  "
            f"{e.get('name','?'):40}  "
            f"script={p.get('script','?')[:24]}... "
            f"in={len(p.get('inputs') or {}):2}  "
            f"out={len(p.get('outputs') or {}):2}"
        )
        print(line)


def _parse_kv(values: list[str] | None, *, label: str) -> dict[str, int]:
    if not values:
        return {}
    out: dict[str, int] = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"--{label} expects NAME=PID, got: {raw!r}")
        name, pid_raw = raw.split("=", 1)
        try:
            pid = int(pid_raw)
        except ValueError as exc:
            raise SystemExit(f"--{label} PID must be integer, got: {pid_raw!r}") from exc
        out[name.strip()] = pid
    return out


def _render_diff(diff: dict) -> None:
    print(f"# param {diff['param_id']} — result: {diff['result']}")
    changes = diff.get("changes") or {}
    if not changes:
        print("  (no changes)")
        return
    for field, value in changes.items():
        if field in ("set_inputs", "set_outputs"):
            print(f"  {field}:")
            for entry in value:
                before = entry.get("before")
                print(f"    {entry['name']}: {before} -> {entry['after']}")
        elif field in ("remove_inputs", "remove_outputs"):
            print(f"  {field}:")
            for entry in value:
                print(f"    {entry['name']} (pid {entry['pid']})")
        elif isinstance(value, dict) and "before" in value:
            print(f"  {field}: {value['before']} -> {value['after']}")
        else:
            print(f"  {field}: {value}")


def _cmd_list(args: argparse.Namespace) -> int:
    if args.script_hash:
        entries = list_inference_params_by_script(
            args.access_token, args.script_hash, with_sources=False
        )
    else:
        entries = list_inference_params(args.access_token)
    entries = _filter_params(entries, script_hash=None, name_filter=args.name_filter)
    if args.json:
        emit_json(entries)
    else:
        _render_list(entries)
    return 0


def _cmd_get(args: argparse.Namespace) -> int:
    if args.with_sources:
        payload = get_inference_param_with_sources(args.access_token, args.param_id)
    else:
        payload = get_inference_param(args.access_token, args.param_id)
    emit_json(payload)
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    set_inputs = _parse_kv(args.set_input, label="set-input")
    set_outputs = _parse_kv(args.set_output, label="set-output")
    diff = update_inference_param(
        args.access_token,
        param_id=args.param_id,
        script_hash=args.script_hash,
        set_inputs=set_inputs or None,
        set_outputs=set_outputs or None,
        remove_inputs=args.allow_remove_input or None,
        remove_outputs=args.allow_remove_output or None,
        resolution=args.resolution,
        dry_run=not args.apply,
    )
    if args.json:
        emit_json(diff)
    else:
        _render_diff(diff)
    return 0


def _cmd_restore_export(args: argparse.Namespace) -> int:
    try:
        exported = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OnPingRequestError(f"Cannot read restore export: {exc}") from exc
    diff = restore_inference_param_from_export(
        args.access_token,
        param_id=args.param_id,
        exported=exported,
        expected_script_hash=args.expect_script,
        expected_current_width=args.expect_current_width,
        dry_run=not args.apply,
    )
    if args.json:
        emit_json(diff)
    else:
        _render_diff(diff)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List, fetch, and update OnPing inference parameters."
    )
    parser.add_argument("access_token", help="OnPing OAuth2 access token")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")

    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_list = sub.add_parser("list", help="List inference params")
    p_list.add_argument("--script-hash", help="Filter by exact script hash")
    p_list.add_argument("--name-filter", help="Case-insensitive substring match on name")

    p_get = sub.add_parser("get", help="Fetch one inference param by id")
    p_get.add_argument("--param-id", required=True)
    p_get.add_argument(
        "--with-sources",
        action="store_true",
        help="Return the InferenceParamXWithSources variant",
    )

    p_up = sub.add_parser("update", help="Read-modify-write an inference param")
    p_up.add_argument("--param-id", required=True)
    p_up.add_argument("--script-hash", help="New script hash to install")
    p_up.add_argument(
        "--set-input", action="append", help="NAME=PID; repeat for multiple"
    )
    p_up.add_argument(
        "--set-output", action="append", help="NAME=PID; repeat for multiple"
    )
    p_up.add_argument(
        "--allow-remove-input",
        action="append",
        help="Binding name to drop; repeatable. Required to shrink the inputs map.",
    )
    p_up.add_argument(
        "--allow-remove-output",
        action="append",
        help="Binding name to drop; repeatable. Required to shrink the outputs map.",
    )
    p_up.add_argument("--resolution", type=int, help="New schedule resolution (seconds)")
    p_up.add_argument(
        "--apply",
        action="store_true",
        help="Actually PUT the update. Without this flag the command is a dry-run.",
    )

    p_restore = sub.add_parser(
        "restore-export", help="Preview or restore an existing param from one bare export object"
    )
    p_restore.add_argument("--param-id", required=True)
    p_restore.add_argument("--file", required=True, help="One unwrapped export JSON object")
    p_restore.add_argument("--expect-script", required=True, help="Abort if the live pin changed")
    p_restore.add_argument("--expect-current-width", type=int, help="Abort if live array width changed")
    p_restore.add_argument("--apply", action="store_true", help="Issue the PUT after fresh preflight")

    args = parser.parse_args(argv)

    try:
        if args.subcommand == "list":
            return _cmd_list(args)
        if args.subcommand == "get":
            return _cmd_get(args)
        if args.subcommand == "update":
            return _cmd_update(args)
        if args.subcommand == "restore-export":
            return _cmd_restore_export(args)
    except OnPingRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.error(f"unknown subcommand: {args.subcommand}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
