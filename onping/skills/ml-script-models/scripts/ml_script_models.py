# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Resolve which models an OnPing Inferno ML parameter or script uses.

An inference parameter carries NO model reference. `params` has no model column
and no table links a parameter to a model. The link lives in the SCRIPT's
version-control metadata, so resolving it takes two hops:

    GET  /inferno/ml/inference/{uuid}   -> param.script (a hash, nothing else)
    POST /scripts/by-hash               -> author.scriptTypes[].contents.models
                                           = { ident: model-VERSION-uuid }
    GET  /inferno/ml/model/version/{id} -> version label, kind, parent model id

The values in `models` are model VERSION ids, not parent model ids. Sending one
to /inferno/ml/model/{uuid} returns HTTP 500.

Model selection is part of the script's hashed metadata (InferenceOptions derives
VCHashUpdate, and vcHash covers the whole VCMeta). So changing a model mints a
NEW script hash: the old hash stays valid, keeps its old bindings, and a
parameter still pointing at it runs the previous model versions with no error.
This script therefore re-reads param.script on every call and always reports the
hash it resolved.

Routes:  onping/config/routes (InfernoScriptR), :819 (InfernoScriptsByHashR),
         :1453 (ParamsByInferenceScriptR)
Wire:    plow-inferno/src/Plow/Inferno/Types/Metadata.hs (InferenceOptions)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _inferno_ml_routes.inferno_ml_models import (  # noqa: E402
    ML_SCRIPT_TAG,
    OnPingRequestError,
    _json_response,
    _request,
    extract_ml_models,
    get_inference_param,
    get_model_version,
    get_script,
    list_inference_params_by_script,
    model_history,
    scripts_by_hash,
)

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

GROUP_SCOPE_NOTE = (
    "Parameter visibility is limited to your authorized groups; this is not an "
    "exhaustive list of every parameter in OnPing."
)


def is_uuid(value: str) -> bool:
    return bool(UUID_RE.match(value.strip()))


# --------------------------------------------------------------------------
# Enrichment
# --------------------------------------------------------------------------


def fetch_parent_models(access_token: str) -> dict[str, dict[str, Any]]:
    """GET /inferno/ml/models/all -> {parent model id: model record}.

    One call instead of one request per model, which is what the OnPing web UI
    does. Returns an empty dict on failure: parent names are enrichment, and a
    lookup MUST still report idents and version ids without them.
    """
    try:
        payload = _json_response(_request("GET", "/inferno/ml/models/all", access_token))
    except OnPingRequestError:
        return {}
    if not isinstance(payload, list):
        return {}
    parents: dict[str, dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        model = entry.get("model")
        if isinstance(model, dict) and model.get("id"):
            parents[str(model["id"])] = model
    return parents


def contents_kind(version: dict[str, Any]) -> str | None:
    """'torchscript' | 'bedrock' | None, from the version's `contents` object."""
    contents = version.get("contents")
    if not isinstance(contents, dict):
        return None
    for kind in ("torchscript", "bedrock"):
        if kind in contents:
            return kind
    keys = sorted(contents.keys())
    return keys[0] if keys else None


def enrich_models(
    access_token: str,
    models: dict[str, str],
    parents: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve each ident's model version. One failure never aborts the rest."""
    rows: list[dict[str, Any]] = []
    for ident in sorted(models):
        version_id = models[ident]
        row: dict[str, Any] = {
            "ident": ident,
            "version_id": version_id,
            "version": None,
            "kind": None,
            "model_id": None,
            "model_name": None,
            "error": None,
        }
        try:
            version = get_model_version(access_token, version_id)
        except OnPingRequestError as exc:
            # Keep the row: the ident and version id are still the answer.
            row["error"] = str(exc).splitlines()[0]
            rows.append(row)
            continue

        row["version"] = version.get("version")
        row["kind"] = contents_kind(version)
        # The parent model id comes off the VERSION record. Never send a version
        # id to /inferno/ml/model/{uuid} — that returns HTTP 500.
        parent_id = version.get("model")
        if parent_id:
            row["model_id"] = str(parent_id)
            parent = parents.get(str(parent_id))
            if parent is None:
                try:
                    parent = _json_response(
                        _request(
                            "GET", f"/inferno/ml/model/{parent_id}", access_token
                        )
                    )
                except OnPingRequestError:
                    parent = None
            if isinstance(parent, dict):
                name = parent.get("name")
                row["model_name"] = name.strip() if isinstance(name, str) else name
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Forward resolution
# --------------------------------------------------------------------------


def resolve_target(access_token: str, target: str) -> tuple[str, str | None, dict]:
    """(script_hash, param_id, param_envelope) for a parameter UUID or a hash.

    For a parameter UUID the hash is re-read from the server on every call. A
    caller-supplied or cached hash can already be stale, because a model swap
    mints a new one.
    """
    target = target.strip()
    if not target:
        raise OnPingRequestError("A parameter UUID or a script hash is required.")
    if is_uuid(target):
        envelope = get_inference_param(access_token, target)
        script_hash = envelope["param"]["script"]
        return script_hash, target, envelope
    return target, None, {}


def forward(access_token: str, target: str) -> dict[str, Any]:
    script_hash, param_id, envelope = resolve_target(access_token, target)

    metas = scripts_by_hash(access_token, [script_hash])
    if script_hash not in metas:
        raise OnPingRequestError(
            f"No script metadata returned for hash {script_hash!r}. The script is "
            "unknown, or it is outside your authorized groups."
        )
    meta = metas[script_hash]
    models, script_types = extract_ml_models(meta)

    if ML_SCRIPT_TAG not in script_types:
        raise OnPingRequestError(
            f"Script {script_hash} is not an ML inference script. Script types "
            f"present: {script_types or ['<none>']}. Model selections exist only "
            "on MLInferenceScript metadata."
        )

    parents = fetch_parent_models(access_token) if models else {}
    rows = enrich_models(access_token, models, parents)

    result: dict[str, Any] = {
        "script_hash": script_hash,
        "script_name": meta.get("name"),
        "param_id": param_id,
        "param_name": envelope.get("name") if envelope else None,
        "script_types": script_types,
        "model_count": len(rows),
        "models": rows,
    }
    if not models:
        result["note"] = "no models selected"
    return result


def check_latest(access_token: str, param_id: str) -> dict[str, Any]:
    """Compare a parameter's pinned hash against the head of its script history."""
    envelope = get_inference_param(access_token, param_id)
    pinned = envelope["param"]["script"]
    payload = get_script(access_token, pinned)
    history = payload["history"]

    head = None
    for entry in history:
        if isinstance(entry, dict) and entry.get("obj"):
            head = str(entry["obj"])
            break

    return {
        "param_id": param_id,
        "param_name": envelope.get("name"),
        "pinned_hash": pinned,
        "latest_hash": head,
        "history_length": len(history),
        "is_latest": head is None or head == pinned,
    }


# --------------------------------------------------------------------------
# Reverse resolution (blast radius)
# --------------------------------------------------------------------------


def reverse(access_token: str, target: str) -> dict[str, Any]:
    """Which scripts select a model version, and which parameters run them.

    No route answers this directly, so this sweeps every reachable script's
    metadata via GET /scripts and matches locally. The cost is proportional to
    the number of scripts your groups can reach. An OnPing feature to serve this
    query directly is in flight as of 2026-08-04.
    """
    target = target.strip()
    if not is_uuid(target):
        raise OnPingRequestError(
            f"Reverse lookup needs a model-version UUID or a parent model UUID, got {target!r}."
        )

    # A parent model id expands over its versions.
    version_ids: dict[str, str | None] = {}
    try:
        version = get_model_version(access_token, target)
        version_ids[target] = version.get("version")
    except OnPingRequestError:
        try:
            history = model_history(access_token, target)
        except OnPingRequestError as exc:
            raise OnPingRequestError(
                f"{target} is neither a reachable model version nor a parent model: {exc}"
            ) from exc
        entries = history.values() if isinstance(history, dict) else history
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id"):
                version_ids[str(entry["id"])] = entry.get("version")
        if not version_ids:
            raise OnPingRequestError(f"Model {target} has no versions.")

    payload = _json_response(_request("GET", "/scripts", access_token))
    if not isinstance(payload, list):
        raise OnPingRequestError("Expected /scripts to return a JSON array.")

    scripts_scanned = 0
    ml_scripts = 0
    hits: list[dict[str, Any]] = []
    for meta in payload:
        if not isinstance(meta, dict):
            continue
        scripts_scanned += 1
        models, script_types = extract_ml_models(meta)
        if ML_SCRIPT_TAG in script_types:
            ml_scripts += 1
        if not models:
            continue
        matched = {
            ident: vid for ident, vid in models.items() if vid in version_ids
        }
        if not matched:
            continue
        script_hash = meta.get("obj")
        if not script_hash:
            continue
        script_hash = str(script_hash)
        try:
            params = list_inference_params_by_script(access_token, script_hash)
        except OnPingRequestError as exc:
            params = []
            param_error = str(exc).splitlines()[0]
        else:
            param_error = None
        hits.append(
            {
                "script_hash": script_hash,
                "script_name": meta.get("name"),
                "matched_idents": matched,
                "parameters": [
                    {"id": p.get("id"), "name": p.get("name"), "active": p.get("active")}
                    for p in params
                ],
                "param_error": param_error,
            }
        )

    return {
        "target": target,
        "version_ids": version_ids,
        "scripts_scanned": scripts_scanned,
        "ml_scripts": ml_scripts,
        "matching_scripts": len(hits),
        "parameter_count": sum(len(h["parameters"]) for h in hits),
        "hits": hits,
        "scope_note": GROUP_SCOPE_NOTE,
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_forward_table(result: dict[str, Any]) -> str:
    lines: list[str] = []
    if result.get("param_id"):
        lines.append(f"Parameter : {result['param_id']}  {result.get('param_name') or ''}".rstrip())
    lines.append(f"Script    : {result['script_hash']}  {result.get('script_name') or ''}".rstrip())

    rows = result["models"]
    if not rows:
        lines.append("")
        lines.append("No models selected by this script.")
        return "\n".join(lines)

    headers = ("IDENT", "VERSION ID", "VERSION", "KIND", "PARENT MODEL")
    table = [
        (
            r["ident"],
            r["version_id"],
            str(r.get("version") or "-"),
            str(r.get("kind") or "-"),
            str(r.get("model_name") or r.get("model_id") or "-"),
        )
        for r in rows
    ]
    widths = [
        max(len(headers[i]), max(len(row[i]) for row in table))
        for i in range(len(headers))
    ]
    lines.append("")
    lines.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip())
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in table:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))).rstrip())

    errors = [r for r in rows if r.get("error")]
    if errors:
        lines.append("")
        for r in errors:
            lines.append(f"! {r['ident']} ({r['version_id']}): {r['error']}")
    return "\n".join(lines)


def render_reverse_table(result: dict[str, Any]) -> str:
    lines = [
        f"Target    : {result['target']}",
        f"Versions  : {len(result['version_ids'])}",
        f"Scanned   : {result['scripts_scanned']} scripts ({result['ml_scripts']} ML)",
    ]
    if not result["hits"]:
        lines.append("")
        # Never phrase an empty result as "this model is unused".
        lines.append(
            "No scripts visible to you select this model version. "
            "If a parameter was re-pointed to a newer script, an older hash no "
            "longer appears here."
        )
        lines.append(f"Note      : {result['scope_note']}")
        return "\n".join(lines)

    for hit in result["hits"]:
        lines.append("")
        lines.append(f"Script    : {hit['script_hash']}  {hit.get('script_name') or ''}".rstrip())
        for ident, vid in sorted(hit["matched_idents"].items()):
            lines.append(f"  ident   : {ident} -> {vid}")
        if hit["parameters"]:
            for p in hit["parameters"]:
                state = "active" if p.get("active") else "inactive"
                lines.append(f"  param   : {p['id']}  [{state}]  {p.get('name') or ''}".rstrip())
        else:
            lines.append(
                f"  param   : no parameters visible to you use script {hit['script_hash']}"
            )
        if hit.get("param_error"):
            lines.append(f"  ! {hit['param_error']}")

    lines.append("")
    lines.append(f"Note      : {result['scope_note']}")
    return "\n".join(lines)


def render_check_latest(result: dict[str, Any]) -> str:
    lines = [
        f"Parameter : {result['param_id']}  {result.get('param_name') or ''}".rstrip(),
        f"Pinned    : {result['pinned_hash']}",
        f"Latest    : {result['latest_hash'] or '<unknown>'}",
        f"History   : {result['history_length']} revisions",
    ]
    if result["is_latest"]:
        lines.append("Status    : up to date")
    else:
        lines.append("Status    : SUPERSEDED — this parameter does not run the newest revision.")
        lines.append(
            "            A model swap mints a new script hash. The old hash stays "
            "valid and keeps its old model bindings, so this parameter still runs "
            "the previous model versions with no error."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve which models an OnPing Inferno ML parameter or script uses. "
            "Read-only."
        ),
    )
    parser.add_argument("access_token", help="OnPing bearer token (see onping-login)")
    parser.add_argument(
        "target",
        help=(
            "An inference-parameter UUID, or an Inferno script hash. "
            "With --reverse, a model-version UUID or a parent model UUID."
        ),
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Blast radius: which scripts and parameters use this model version.",
    )
    parser.add_argument(
        "--check-latest",
        action="store_true",
        help="Report whether a parameter's pinned script hash is the newest revision.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--map-only",
        action="store_true",
        help="Emit bare 'ident<TAB>version-id' pairs for piping.",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.reverse and args.check_latest:
        print("--reverse and --check-latest are mutually exclusive.", file=sys.stderr)
        sys.exit(2)
    if args.map_only and args.json:
        print("--map-only and --json are mutually exclusive.", file=sys.stderr)
        sys.exit(2)
    if args.map_only and (args.reverse or args.check_latest):
        print("--map-only applies to the forward lookup only.", file=sys.stderr)
        sys.exit(2)
    if args.check_latest and not is_uuid(args.target):
        print(
            "--check-latest needs a parameter UUID, not a script hash.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        if args.check_latest:
            result = check_latest(args.access_token, args.target)
            rendered = render_check_latest(result)
        elif args.reverse:
            result = reverse(args.access_token, args.target)
            rendered = render_reverse_table(result)
        else:
            result = forward(args.access_token, args.target)
            rendered = render_forward_table(result)
    except OnPingRequestError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if args.map_only:
        for row in result["models"]:
            print(f"{row['ident']}\t{row['version_id']}")
    elif args.json:
        print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    else:
        print(rendered)

    # A forward lookup where nothing resolved is a failure, even though the
    # idents and version ids are still reported.
    if not args.reverse and not args.check_latest:
        rows = result.get("models") or []
        if rows and all(r.get("error") for r in rows):
            print(
                "No model version resolved; every enrichment call failed.",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
