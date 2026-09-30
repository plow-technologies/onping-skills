# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export OnPing Inferno inference (ml-) parameters as JSON.

Wraps `POST /inferno/ml/inference/export` — read-only despite being a POST. The
body is a JSON array of parameter UUIDs; the response is a JSON array of flat
`ExportedInferenceParam` records, the same shape
`POST /inferno/ml/inference/import` consumes.

The route SILENTLY OMITS ids it cannot serve (unknown, or outside the caller's
groups/locations) — HTTP 200 with a short array and nothing naming the dropped
id. `--strict` (the default) reconciles requested against returned ids and fails
rather than let a partial export masquerade as a complete backup.

Handler: onping/Handler/Inferno/ML/Parameters.hs
Route:   onping/config/routes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _inferno_ml_routes.inferno_ml_models import (  # noqa: E402
    OnPingRequestError,
    _validate_exported_param,
    export_inference_params,
    is_uuid,
)


def _collect_ids(args: argparse.Namespace) -> list[str]:
    """Resolve the requested ids from argv or stdin, validated and de-duplicated."""
    if args.stdin_ids and args.param_ids:
        raise SystemExit(
            "Pass ids either positionally or via --stdin-ids, not both "
            "(the combined order would be ambiguous)."
        )

    if args.stdin_ids:
        raw = sys.stdin.read().split()
    else:
        raw = list(args.param_ids)

    if not raw:
        source = "--stdin-ids received no input" if args.stdin_ids else "no ids given"
        raise SystemExit(
            f"At least one parameter UUID is required ({source}). "
            "The export route answers an empty list with an ambiguous 200 []."
        )

    malformed = [value for value in raw if not is_uuid(value)]
    if malformed:
        raise SystemExit(
            "Not a canonical 8-4-4-4-12 UUID: "
            + ", ".join(repr(value) for value in malformed)
            + "\nNo request was sent. Note OnPing cannot tell a typo'd id from one "
            "you lack access to — both are silently omitted — so ids are checked here."
        )

    # De-duplicate, preserving first-seen order so output order is predictable.
    seen: dict[str, None] = {}
    for value in raw:
        seen.setdefault(value.strip(), None)
    return list(seen)


def _reconcile(requested: list[str], records: list[dict], *, strict: bool) -> None:
    """Report ids the server omitted. Raises in strict mode."""
    returned = {r.get("id") for r in records}
    missing = [pid for pid in requested if pid not in returned]
    if not missing:
        return

    detail = (
        f"OnPing returned {len(records)} of {len(requested)} requested parameters.\n"
        "Omitted (unknown id, or not accessible to your groups/locations):\n"
        + "\n".join(f"  {pid}" for pid in missing)
    )
    if strict:
        raise OnPingRequestError(
            detail + "\n\nNothing was written. Re-run with --no-strict to accept a "
            "partial export."
        )
    print(f"warning: {detail}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Export OnPing Inferno inference (ml-) parameters as JSON via "
            "POST /inferno/ml/inference/export. Read-only."
        ),
    )
    p.add_argument("access_token", help="OnPing bearer token (see onping-login)")
    p.add_argument(
        "param_ids",
        nargs="*",
        metavar="UUID",
        help="One or more inference parameter UUIDs",
    )
    p.add_argument(
        "--stdin-ids",
        action="store_true",
        help="Read whitespace/newline-separated UUIDs from stdin instead of argv",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        help="Write JSON here instead of stdout (written only on success)",
    )
    p.add_argument("--pretty", action="store_true", help="Indent the JSON output")
    p.add_argument(
        "--unwrap-single",
        action="store_true",
        help="Emit the bare record object when exactly one was returned "
        "(refuses when more came back)",
    )
    strictness = p.add_mutually_exclusive_group()
    strictness.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        default=True,
        help="Fail if any requested id is missing from the response (default)",
    )
    strictness.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        help="Warn instead of failing when ids are omitted",
    )
    args = p.parse_args()

    requested = _collect_ids(args)

    try:
        records = export_inference_params(args.access_token, requested)

        extras: set[str] = set()
        for index, record in enumerate(records):
            extras.update(_validate_exported_param(record, index=index))
        if extras:
            print(
                "note: response carried unrecognized top-level keys "
                f"{sorted(extras)}; passing them through unchanged.",
                file=sys.stderr,
            )

        _reconcile(requested, records, strict=args.strict)

        payload: object = records
        if args.unwrap_single:
            if len(records) != 1:
                raise OnPingRequestError(
                    f"--unwrap-single needs exactly one record, got {len(records)}. "
                    "Refusing to discard data; drop the flag to emit the array."
                )
            payload = records[0]
    except OnPingRequestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    text = json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True)

    if args.output:
        Path(args.output).write_text(text + "\n")
        print(
            f"Wrote {len(records)} exported parameter(s) to {args.output}",
            file=sys.stderr,
        )
    else:
        print(text)


if __name__ == "__main__":
    main()
