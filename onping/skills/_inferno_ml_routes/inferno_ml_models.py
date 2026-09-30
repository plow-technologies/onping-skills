# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Shared helpers for OnPing Inferno ML model management scripts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import requests

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net").rstrip("/")
DEFAULT_TIMEOUT = 30
UPLOAD_TIMEOUT = 120
RETRYABLE_STATUS_CODES = {502, 503, 504}
VERSION_RE = re.compile(r"^v\d+(?:\.\d+)*(?:-[A-Za-z]+(?:-[A-Za-z]+)*)?$")
MISSING = object()


class OnPingRequestError(RuntimeError):
    """Raised when an OnPing request fails."""


def emit_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def require_suffix(path: Path, suffix: str) -> None:
    if path.suffix.lower() != suffix:
        raise OnPingRequestError(
            f"Expected a {suffix} file for upload, got: {path.name}"
        )


def parse_version_string(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise OnPingRequestError(
            "Invalid version string. Expected forms like v1, v1.0, or v1.2.3-beta."
        )
    return version


def parse_categories(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    if raw.strip() == "":
        return []
    parts = [part.strip() for part in raw.split(",")]
    try:
        return [int(part) for part in parts if part]
    except ValueError as exc:
        raise OnPingRequestError(
            f"Invalid category list {raw!r}; expected comma-separated integers."
        ) from exc


def default_model_card(*, categories: list[int] | None = None) -> dict[str, Any]:
    return {
        "summary": {
            "evaluation": "",
            "summary": "",
            "uses": "",
        },
        "metadata": {
            "categories": [] if categories is None else categories,
            "datasets": "",
            "metrics": "",
        },
    }


def merge_model_card(
    existing: dict[str, Any],
    *,
    summary: Any = MISSING,
    evaluation: Any = MISSING,
    uses: Any = MISSING,
    datasets: Any = MISSING,
    metrics: Any = MISSING,
    categories: Any = MISSING,
    base_model: Any = MISSING,
) -> dict[str, Any]:
    card = json.loads(json.dumps(existing))
    card.setdefault("summary", {})
    card.setdefault("metadata", {})

    if summary is not MISSING:
        card["summary"]["summary"] = summary
    if evaluation is not MISSING:
        card["summary"]["evaluation"] = evaluation
    if uses is not MISSING:
        card["summary"]["uses"] = uses
    if datasets is not MISSING:
        card["metadata"]["datasets"] = datasets
    if metrics is not MISSING:
        card["metadata"]["metrics"] = metrics
    if categories is not MISSING:
        card["metadata"]["categories"] = categories
    if base_model is not MISSING:
        if base_model in (None, ""):
            card["metadata"].pop("base-model", None)
        else:
            card["metadata"]["base-model"] = base_model

    return card


def _headers(access_token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    if extra:
        headers.update(extra)
    return headers


def _format_error(response: requests.Response) -> str:
    body = response.text.strip()
    if not body:
        body = "<empty response>"
    if 300 <= response.status_code < 400:
        location = response.headers.get("Location")
        if location:
            body = f"{body}\nRedirect location: {location}"
    return f"HTTP {response.status_code} for {response.request.method} {response.url}:\n{body}"


def _request(
    method: str,
    path: str,
    access_token: str,
    *,
    json_body: Any = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    expected_statuses: Iterable[int] = (200,),
    stream: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> requests.Response:
    url = f"{BASE_URL}{path}"
    headers = _headers(access_token, extra_headers)
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    attempts = 3
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                data=data,
                files=files,
                allow_redirects=False,
                timeout=timeout,
                stream=stream,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                raise OnPingRequestError(f"Request error: {exc}") from exc
            continue

        if response.status_code in expected_statuses:
            return response

        if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts:
            continue

        raise OnPingRequestError(_format_error(response))

    raise OnPingRequestError(f"Request error: {last_error}")


def _json_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise OnPingRequestError(
            f"Failed to decode JSON response from {response.url}:\n{response.text}"
        ) from exc


def _maybe_json_response(response: requests.Response) -> Any:
    text = response.text.strip()
    if not text:
        return None
    try:
        return response.json()
    except ValueError:
        return text


def list_models(access_token: str) -> list[dict[str, Any]]:
    response = _request("GET", "/inferno/ml/models", access_token)
    payload = _json_response(response)
    if not isinstance(payload, list):
        raise OnPingRequestError("Expected model list response to be a JSON array.")
    return payload


def get_model(access_token: str, model_id: str) -> dict[str, Any]:
    response = _request("GET", f"/inferno/ml/model/{model_id}", access_token)
    payload = _json_response(response)
    if not isinstance(payload, dict):
        raise OnPingRequestError("Expected model response to be a JSON object.")
    return payload


def create_model(
    access_token: str,
    *,
    name: str,
    gid: str,
    visibility: str,
) -> str:
    body = {
        "id": None,
        "name": name,
        "gid": gid,
        "visibility": visibility,
        "created": None,
        "updated": None,
        "terminated": None,
    }
    response = _request("POST", "/inferno/ml/model", access_token, json_body=body)
    payload = _maybe_json_response(response)
    if not isinstance(payload, str):
        raise OnPingRequestError(
            f"Expected model creation response to be a UUID string, got: {payload!r}"
        )
    return payload


def update_model(
    access_token: str,
    *,
    model_id: str,
    name: str | None = None,
    gid: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    model = get_model(access_token, model_id)

    if name is None and gid is None and visibility is None:
        raise OnPingRequestError(
            "No changes requested. Provide at least one of --name, --gid, or --visibility."
        )

    if name is not None:
        model["name"] = name
    if gid is not None:
        model["gid"] = gid
    if visibility is not None:
        model["visibility"] = visibility

    _request("PUT", "/inferno/ml/model/update", access_token, json_body=model)
    return get_model(access_token, model_id)


def delete_model(access_token: str, model_id: str) -> None:
    _request("DELETE", f"/inferno/ml/model/{model_id}", access_token)


def model_history(access_token: str, model_id: str) -> dict[str, Any]:
    response = _request("GET", f"/inferno/ml/model/history/{model_id}", access_token)
    payload = _json_response(response)
    if not isinstance(payload, dict):
        raise OnPingRequestError("Expected model history response to be a JSON object.")
    return payload


def get_model_version(access_token: str, version_id: str) -> dict[str, Any]:
    response = _request(
        "GET", f"/inferno/ml/model/version/{version_id}", access_token
    )
    payload = _json_response(response)
    if not isinstance(payload, dict):
        raise OnPingRequestError(
            "Expected model version response to be a JSON object."
        )
    return payload


def upload_model_version(
    access_token: str,
    *,
    model_id: str,
    file_path: Path,
    version: str,
    description: str,
    card: dict[str, Any],
) -> str:
    if not file_path.exists():
        raise OnPingRequestError(f"File not found: {file_path}")
    require_suffix(file_path, ".pt")

    version = parse_version_string(version)
    with file_path.open("rb") as handle:
        files = {
            "file": (file_path.name, handle, "application/octet-stream"),
        }
        data = {
            "model": model_id,
            "version": json.dumps(version),
            "card": json.dumps(card),
            "description": description,
        }
        response = _request(
            "POST",
            "/inferno/ml/model/version",
            access_token,
            data=data,
            files=files,
            timeout=UPLOAD_TIMEOUT,
        )

    payload = _maybe_json_response(response)
    if not isinstance(payload, str):
        raise OnPingRequestError(
            f"Expected model version upload response to be a UUID string, got: {payload!r}"
        )
    return payload


def update_version_docs(
    access_token: str,
    *,
    version_id: str,
    description: Any = MISSING,
    version: Any = MISSING,
    summary: Any = MISSING,
    evaluation: Any = MISSING,
    uses: Any = MISSING,
    datasets: Any = MISSING,
    metrics: Any = MISSING,
    categories: Any = MISSING,
    base_model: Any = MISSING,
) -> dict[str, Any]:
    current = get_model_version(access_token, version_id)

    if all(
        value is MISSING
        for value in (
            description,
            version,
            summary,
            evaluation,
            uses,
            datasets,
            metrics,
            categories,
            base_model,
        )
    ):
        raise OnPingRequestError(
            "No changes requested. Provide at least one version or card field to update."
        )

    if description is not MISSING:
        current["description"] = description
    if version is not MISSING:
        current["version"] = parse_version_string(version)

    current["card"] = merge_model_card(
        current.get("card", default_model_card()),
        summary=summary,
        evaluation=evaluation,
        uses=uses,
        datasets=datasets,
        metrics=metrics,
        categories=categories,
        base_model=base_model,
    )

    response = _request(
        "PUT",
        "/inferno/ml/model/version/update",
        access_token,
        json_body=current,
    )
    payload = _maybe_json_response(response)
    target_id = payload if isinstance(payload, str) else version_id
    return get_model_version(access_token, target_id)


def delete_model_version(access_token: str, version_id: str) -> None:
    _request("DELETE", f"/inferno/ml/model/version/{version_id}", access_token)


def export_model_version(
    access_token: str,
    *,
    version_id: str,
    output_path: Path | None = None,
) -> Path:
    response = _request(
        "GET",
        f"/inferno/ml/model/version/export/{version_id}",
        access_token,
        stream=True,
        expected_statuses=(200,),
        timeout=UPLOAD_TIMEOUT,
    )

    if output_path is None:
        filename = _filename_from_response(response) or f"{version_id}.ts.pt.zip"
        output_path = Path.cwd() / filename

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)

    return output_path


def _filename_from_response(response: requests.Response) -> str | None:
    content_disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename="([^"]+)"', content_disposition)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Inference (ml-) parameter helpers
#
# API shape (locked by fixtures under
# openspec/changes/add-ml-parameter-update/fixtures/):
#
#   GET  /inferno/ml/inference/all
#        → Vector InferenceParamX  (array of envelopes)
#   GET  /inferno/ml/inference/{uuid}
#        → InferenceParamX (bare)
#   GET  /inferno/ml/inference/list/script/{hash}
#        → Vector InferenceParamX filtered by script hash
#   GET  /inferno/ml/inference/list/script/with-sources/{hash}
#        → Vector InferenceParamXWithSources (param.inputs/outputs hold full
#          SourceInfo records keyed by binding name)
#   PUT  /inferno/ml/inference/update
#        body: { "param": InferenceParamXBody, "sources": Vector SourceInfo }
#   POST /inferno/ml/inference/export
#        body: [ uuid, ... ]  (bare JSON array of param ids)
#        → Vector (ExportedInferenceParam PID) — FLAT records, a different
#          shape from the InferenceParamX envelope above. See the export
#          section further down for the shape and the silent-omission gotcha.
#
# Envelope shape:
#   { active, company, description, id, name, param, schedule }
# param body shape:
#   { gid, id, inputs, outputs, resolution, script, terminated }
# ---------------------------------------------------------------------------

_PARAM_ENVELOPE_REQUIRED = {"active", "company", "description", "id", "name", "param", "schedule"}
_PARAM_BODY_REQUIRED = {"gid", "id", "inputs", "outputs", "resolution", "script", "terminated"}


def _validate_source_binding(value: Any, *, label: str) -> None:
    """SourceInfo follows SingleOrMany: an object or a nonempty object array."""
    items = value if isinstance(value, list) else [value]
    if not items or any(
        not isinstance(info, dict)
        or type(info.get("pid")) is not int
        or info["pid"] <= 0
        for info in items
    ):
        raise OnPingRequestError(
            f"{label} must be a SourceInfo object or a nonempty array of SourceInfo objects."
        )


def _pids_from_source_binding(value: Any, *, label: str) -> int | list[int]:
    _validate_source_binding(value, label=label)
    if isinstance(value, list):
        return [info["pid"] for info in value]
    return value["pid"]


def _validate_param_envelope(data: Any, *, with_sources: bool = False) -> list[str]:
    """Validate an InferenceParamX envelope and return any unknown top-level keys.

    Raises OnPingRequestError when required keys are missing or when
    param.inputs / param.outputs are not dicts.
    """
    if not isinstance(data, dict):
        raise OnPingRequestError(
            f"Expected inference param to be a JSON object, got {type(data).__name__}."
        )
    missing = _PARAM_ENVELOPE_REQUIRED - data.keys()
    if missing:
        raise OnPingRequestError(
            f"Inference param response is missing required keys: {sorted(missing)}"
        )
    param = data.get("param")
    if not isinstance(param, dict):
        raise OnPingRequestError("Inference param response has non-dict 'param'.")
    body_missing = _PARAM_BODY_REQUIRED - param.keys()
    if body_missing:
        raise OnPingRequestError(
            f"Inference param body is missing required keys: {sorted(body_missing)}"
        )
    if not isinstance(param.get("inputs"), dict):
        raise OnPingRequestError("Inference param body 'inputs' must be a dict.")
    if not isinstance(param.get("outputs"), dict):
        raise OnPingRequestError("Inference param body 'outputs' must be a dict.")
    if with_sources:
        for section in ("inputs", "outputs"):
            for name, value in param[section].items():
                _validate_source_binding(value, label=f"with-sources {section} '{name}'")
    return sorted(data.keys() - _PARAM_ENVELOPE_REQUIRED)


def list_inference_params(access_token: str) -> list[dict[str, Any]]:
    """GET /inferno/ml/inference/all."""
    response = _request("GET", "/inferno/ml/inference/all", access_token)
    payload = _json_response(response)
    if not isinstance(payload, list):
        raise OnPingRequestError("Expected inference param list to be a JSON array.")
    return payload


def list_inference_params_by_script(
    access_token: str,
    script_hash: str,
    *,
    with_sources: bool = False,
) -> list[dict[str, Any]]:
    """GET /inferno/ml/inference/list/script[/with-sources]/{hash}."""
    if not script_hash:
        raise OnPingRequestError("script_hash is required.")
    from urllib.parse import quote

    encoded = quote(script_hash, safe="")
    suffix = "with-sources/" if with_sources else ""
    path = f"/inferno/ml/inference/list/script/{suffix}{encoded}"
    response = _request("GET", path, access_token)
    payload = _json_response(response)
    if not isinstance(payload, list):
        raise OnPingRequestError(
            "Expected list-by-script response to be a JSON array."
        )
    for entry in payload:
        _validate_param_envelope(entry, with_sources=with_sources)
    return payload


def get_inference_param(access_token: str, param_id: str) -> dict[str, Any]:
    """GET /inferno/ml/inference/{uuid} (bare envelope, no SourceInfo)."""
    response = _request("GET", f"/inferno/ml/inference/{param_id}", access_token)
    payload = _json_response(response)
    _validate_param_envelope(payload, with_sources=False)
    return payload


def get_inference_param_with_sources(
    access_token: str,
    param_id: str,
) -> dict[str, Any]:
    """Fetch the with-sources variant for a single param id.

    The by-script/with-sources endpoint is the only server-side way to obtain
    full SourceInfo records. We fetch the bare param first to learn its script
    hash, then query the with-sources list and filter by id.
    """
    bare = get_inference_param(access_token, param_id)
    script_hash = bare["param"]["script"]
    with_sources = list_inference_params_by_script(
        access_token, script_hash, with_sources=True
    )
    for entry in with_sources:
        if entry.get("id") == param_id:
            return entry
    raise OnPingRequestError(
        f"Param {param_id} not found in with-sources response for script {script_hash}."
    )


def build_sources_vector(with_sources_param: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten SourceInfo SingleOrMany bindings for read-side inspection.

    Order: inputs sorted by name, then outputs sorted by name; each array
    retains its positional order. The PUT endpoint does NOT accept this vector
    in its request: it derives SourceInfo from the complete bare-PID envelope.
    """
    if "param" not in with_sources_param:
        raise OnPingRequestError("build_sources_vector: missing 'param' key.")
    param = with_sources_param["param"]
    if not isinstance(param, dict):
        raise OnPingRequestError("build_sources_vector: 'param' must be a dict.")
    for key in ("inputs", "outputs"):
        if not isinstance(param.get(key), dict):
            raise OnPingRequestError(f"build_sources_vector: 'param.{key}' must be a dict.")
        for name, value in param[key].items():
            _validate_source_binding(value, label=f"build_sources_vector {key}[{name}]")
    sources: list[dict[str, Any]] = []
    for key in ("inputs", "outputs"):
        for name in sorted(param[key]):
            value = param[key][name]
            sources.extend(value if isinstance(value, list) else [value])
    return sources


def _param_body_from_with_sources(with_sources_param: dict[str, Any]) -> dict[str, Any]:
    """Convert a with-sources param body into the bare PID-map form used by PUT."""
    param = with_sources_param["param"]
    return {
        "gid": param["gid"],
        "id": param["id"],
        "inputs": {
            name: _pids_from_source_binding(info, label=f"input {name}")
            for name, info in param["inputs"].items()
        },
        "outputs": {
            name: _pids_from_source_binding(info, label=f"output {name}")
            for name, info in param["outputs"].items()
        },
        "resolution": param["resolution"],
        "script": param["script"],
        "terminated": param["terminated"],
    }


def update_inference_param(
    access_token: str,
    *,
    param_id: str,
    script_hash: str | None = None,
    set_inputs: dict[str, int] | None = None,
    set_outputs: dict[str, int] | None = None,
    remove_inputs: Iterable[str] | None = None,
    remove_outputs: Iterable[str] | None = None,
    resolution: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read-modify-write update for an OnPing inference parameter.

    Fetches the with-sources param, overlays the caller's requested changes,
    and PUTs the result. When dry_run=True, returns a descriptor of the diff
    without making the PUT.

    Invariants enforced:
      * Callers may not submit a pre-constructed body.
      * Bindings present in the current GET but absent from the overlaid body
        are preserved unless the caller explicitly names them in
        remove_inputs / remove_outputs.
      * set_inputs / set_outputs REPLACE existing bindings by name; they do
        NOT clear unreferenced names.
    """
    current = get_inference_param_with_sources(access_token, param_id)
    current_param = current["param"]
    if any(
        isinstance(value, list)
        for section in ("inputs", "outputs")
        for value in current_param[section].values()
    ):
        raise OnPingRequestError(
            "Scalar --set-input/--set-output cannot edit a multi-well parameter. "
            "Use restore-export with a complete, reviewed four-wide or rollback export."
        )

    # Start from a deep-ish copy of the current mappings.
    next_inputs_si = {name: dict(info) for name, info in current_param["inputs"].items()}
    next_outputs_si = {name: dict(info) for name, info in current_param["outputs"].items()}

    diff: dict[str, Any] = {"param_id": param_id, "changes": {}}

    # Apply removals first, then overrides.
    if remove_inputs:
        removed = []
        for name in remove_inputs:
            if name not in next_inputs_si:
                raise OnPingRequestError(
                    f"Cannot remove input '{name}': not present on param."
                )
            removed.append({"name": name, "pid": next_inputs_si[name]["pid"]})
            del next_inputs_si[name]
        if removed:
            diff["changes"]["remove_inputs"] = removed

    if remove_outputs:
        removed = []
        for name in remove_outputs:
            if name not in next_outputs_si:
                raise OnPingRequestError(
                    f"Cannot remove output '{name}': not present on param."
                )
            removed.append({"name": name, "pid": next_outputs_si[name]["pid"]})
            del next_outputs_si[name]
        if removed:
            diff["changes"]["remove_outputs"] = removed

    if set_inputs:
        changed = []
        for name, pid in set_inputs.items():
            before = next_inputs_si.get(name, {}).get("pid")
            if before == pid:
                continue
            if name in next_inputs_si:
                next_inputs_si[name] = {**next_inputs_si[name], "pid": pid, "id": None}
            else:
                # New binding — other SourceInfo fields are unknown; orchestrator
                # will look them up from the PID.
                next_inputs_si[name] = {
                    "id": None,
                    "pid": pid,
                    "param": param_id,
                    "itype": None,
                    "company": None,
                    "site": None,
                    "location": None,
                    "stype": "InputSource",
                }
            changed.append({"name": name, "before": before, "after": pid})
        if changed:
            diff["changes"]["set_inputs"] = changed

    if set_outputs:
        changed = []
        for name, pid in set_outputs.items():
            before = next_outputs_si.get(name, {}).get("pid")
            if before == pid:
                continue
            if name in next_outputs_si:
                next_outputs_si[name] = {**next_outputs_si[name], "pid": pid, "id": None}
            else:
                next_outputs_si[name] = {
                    "id": None,
                    "pid": pid,
                    "param": param_id,
                    "itype": None,
                    "company": None,
                    "site": None,
                    "location": None,
                    "stype": "OutputSource",
                }
            changed.append({"name": name, "before": before, "after": pid})
        if changed:
            diff["changes"]["set_outputs"] = changed

    next_body = _param_body_from_with_sources(current)
    next_body["inputs"] = {name: info["pid"] for name, info in next_inputs_si.items()}
    next_body["outputs"] = {name: info["pid"] for name, info in next_outputs_si.items()}

    if script_hash is not None and script_hash != current_param["script"]:
        next_body["script"] = script_hash
        diff["changes"]["script_hash"] = {
            "before": current_param["script"],
            "after": script_hash,
        }

    if resolution is not None and resolution != current_param["resolution"]:
        next_body["resolution"] = resolution
        diff["changes"]["resolution"] = {
            "before": current_param["resolution"],
            "after": resolution,
        }

    # The handler consumes a FULL InferenceParamX envelope, not {param, sources}.
    # It resolves and permission-checks SourceInfo from the submitted PIDs itself.
    put_body = {**current, "param": next_body}
    _validate_param_envelope(put_body)

    if not diff["changes"]:
        diff["result"] = "no-op"
        return diff

    if dry_run:
        diff["result"] = "dry-run"
        diff["put_body"] = put_body
        return diff

    _request(
        "PUT",
        "/inferno/ml/inference/update",
        access_token,
        json_body=put_body,
        expected_statuses=(200, 204),
    )
    diff["result"] = "applied"
    return diff


def _validate_bare_pid_maps(param: dict[str, Any]) -> int | None:
    """Require the complete SingleOrMany PID maps to have one consistent width."""
    widths: set[int] = set()
    shapes: set[type] = set()
    for section in ("inputs", "outputs"):
        mapping = param.get(section)
        if not isinstance(mapping, dict):
            raise OnPingRequestError(f"Restore {section} must be an object.")
        for name, value in mapping.items():
            if not isinstance(name, str) or not name:
                raise OnPingRequestError(f"Restore {section} has an empty binding name.")
            items = value if isinstance(value, list) else [value]
            if not items or any(type(pid) is not int or pid <= 0 for pid in items):
                raise OnPingRequestError(
                    f"Restore {section}.{name} requires positive integer PIDs."
                )
            shapes.add(list if isinstance(value, list) else int)
            if isinstance(value, list):
                widths.add(len(value))
    if len(shapes) > 1 or len(widths) > 1:
        raise OnPingRequestError("Restore input/output binding shapes or array widths differ.")
    return next(iter(widths)) if widths else None


def restore_inference_param_from_export(
    access_token: str,
    *,
    param_id: str,
    exported: dict[str, Any],
    expected_script_hash: str,
    expected_current_width: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Restore PID maps/script from ONE reviewed export via the full-envelope PUT.

    Reads the live InferenceParamX immediately before constructing the PUT body.
    Never accepts another parameter's id or changes name, schedule, company or
    group. This restores bindings, resolution and script only; it does not touch
    device setpoints or establish that the server executed the requested rollback.
    """
    if not isinstance(exported, dict):
        raise OnPingRequestError("Restore file must contain one bare export object, not an array.")
    required = {
        "id", "name", "description", "company", "gid", "script", "inputs",
        "outputs", "resolution", "schedule", "itype",
    }
    if required - exported.keys() or exported.keys() - required:
        raise OnPingRequestError(
            f"Restore export has missing {sorted(required - exported.keys())} or "
            f"unknown {sorted(exported.keys() - required)} keys."
        )
    if exported["id"] != param_id:
        raise OnPingRequestError("Restore export ID does not match --param-id.")
    if not isinstance(exported["script"], str) or not exported["script"]:
        raise OnPingRequestError("Restore export has no script hash.")
    if type(exported["resolution"]) is not int or exported["resolution"] <= 0:
        raise OnPingRequestError("Restore export resolution must be a positive integer.")
    desired_width = _validate_bare_pid_maps(exported)
    current = get_inference_param(access_token, param_id)
    body = current["param"]
    current_width = _validate_bare_pid_maps(body)
    if body["script"] != expected_script_hash:
        raise OnPingRequestError(
            f"Current script hash {body['script']} differs from expected {expected_script_hash}."
        )
    if expected_current_width is not None and current_width != expected_current_width:
        raise OnPingRequestError(
            f"Current width {current_width} differs from expected {expected_current_width}."
        )
    for field in ("name", "description", "company", "schedule"):
        if exported[field] != current[field]:
            raise OnPingRequestError(f"Restore export {field} differs from live parameter.")
    if exported["gid"] != body["gid"]:
        raise OnPingRequestError("Restore export group differs from live parameter.")
    if body["id"] != param_id or body["terminated"] is not None:
        raise OnPingRequestError("Restore target is mismatched or terminated.")

    changes: dict[str, Any] = {}
    for section in ("inputs", "outputs"):
        old, new = body[section], exported[section]
        if old != new:
            changes[section] = {
                "removed": sorted(old.keys() - new.keys()),
                "added": sorted(new.keys() - old.keys()),
                "changed": {
                    name: {"before": old[name], "after": new[name]}
                    for name in sorted(old.keys() & new.keys()) if old[name] != new[name]
                },
            }
    for field in ("script", "resolution"):
        if body[field] != exported[field]:
            changes[field] = {"before": body[field], "after": exported[field]}
    diff: dict[str, Any] = {
        "param_id": param_id,
        "current_width": current_width,
        "desired_width": desired_width,
        "changes": changes,
    }
    if not changes:
        return {**diff, "result": "no-op"}
    put_body = {
        **current,
        "param": {
            **body,
            "inputs": exported["inputs"],
            "outputs": exported["outputs"],
            "script": exported["script"],
            "resolution": exported["resolution"],
        },
    }
    _validate_param_envelope(put_body)
    if dry_run:
        return {**diff, "result": "dry-run", "put_body": put_body}
    _request(
        "PUT", "/inferno/ml/inference/update", access_token,
        json_body=put_body, expected_statuses=(200, 204),
    )
    return {**diff, "result": "applied"}


# ---------------------------------------------------------------------------
# Inference parameter export
#
#   POST /inferno/ml/inference/export
#        body: [ uuid, ... ]
#        → [ ExportedInferenceParam PID, ... ]
#
# Handler: onping/Handler/Inferno/ML/Parameters.hs
# Route:   onping/config/routes
# Type:    inferno-ml-orchestrator-types/.../Orchestrator/Types.hs
#          (flattening ToJSON instance at :2052)
#
# Exported record shape — FLAT, unlike the nested InferenceParamX envelope:
#   { id, name, description, company, gid, script, inputs, outputs,
#     resolution, schedule, itype }
#
# Three things that are not obvious and have bitten us:
#
#   1. SILENT OMISSION. An id that is unknown, or whose group/location the
#      caller cannot reach, is simply ABSENT from the response array. There is
#      no error and nothing names the dropped id. Verified live 2026-07-31:
#      [valid, bogus] → HTTP 200 with 1 record; [bogus] and [] → HTTP 200 [].
#      Callers MUST reconcile requested ids against returned ids themselves.
#   2. `itype` ({device, cap}) is EXPORT-ONLY. It appears on this route and
#      nowhere else — not /inference/{uuid}, /inference/all, or the
#      with-sources list. Round-tripping a param any other way loses it.
#   3. inputs/outputs hold BARE PIDs (int or [int]), not SourceInfo records.
#      The handler strips source info via `exportedParamStripSourceInfo`
#      (Parameters.hs) because the import side cannot trust
#      caller-supplied metadata. Use the with-sources list for SourceInfo.
#
# Errors are `{"error": "<message>"}` (Handler/Inferno/ML/Utils.hs sendStatus).
# ---------------------------------------------------------------------------

_EXPORTED_PARAM_REQUIRED = {
    "company",
    "description",
    "gid",
    "inputs",
    "itype",
    "name",
    "outputs",
    "resolution",
    "schedule",
    "script",
}
_ITYPE_REQUIRED = {"cap", "device"}

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def is_uuid(value: str) -> bool:
    """True when `value` is a canonical 8-4-4-4-12 hex UUID."""
    return bool(UUID_RE.fullmatch(value.strip()))


def _validate_exported_param(record: Any, *, index: int) -> list[str]:
    """Validate one ExportedInferenceParam record; return unknown extra keys.

    Raises OnPingRequestError when a required key is missing or mistyped — that
    means the OnPing API contract changed and the caller should stop rather than
    emit a half-understood body. Unknown EXTRA keys are returned, not raised, so
    a server-side field addition stays forward-compatible.
    """
    where = f"exported record #{index}"
    if not isinstance(record, dict):
        raise OnPingRequestError(
            f"Expected {where} to be a JSON object, got {type(record).__name__}."
        )

    missing = _EXPORTED_PARAM_REQUIRED - record.keys()
    if missing:
        raise OnPingRequestError(
            f"{where} is missing required keys: {sorted(missing)}. "
            "The OnPing export API contract may have changed."
        )

    for field in ("inputs", "outputs"):
        if not isinstance(record[field], dict):
            raise OnPingRequestError(
                f"{where}: '{field}' must be an object mapping binding names to PIDs, "
                f"got {type(record[field]).__name__}."
            )

    itype = record["itype"]
    if not isinstance(itype, dict):
        raise OnPingRequestError(
            f"{where}: 'itype' must be an object, got {type(itype).__name__}."
        )
    itype_missing = _ITYPE_REQUIRED - itype.keys()
    if itype_missing:
        raise OnPingRequestError(
            f"{where}: 'itype' is missing required keys: {sorted(itype_missing)}"
        )

    # Anything coming back from /export is by definition an existing parameter,
    # so `id` is always present — even though the upstream type makes it
    # optional (Types.hs) for the import direction, where its absence
    # means "create a new param".
    param_id = record.get("id")
    if not isinstance(param_id, str) or not is_uuid(param_id):
        raise OnPingRequestError(
            f"{where}: expected 'id' to be a UUID string, got {param_id!r}."
        )

    return sorted(record.keys() - _EXPORTED_PARAM_REQUIRED - {"id"})


def export_inference_params(
    access_token: str,
    param_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """POST /inferno/ml/inference/export.

    Read-only despite being a POST: the handler reads, permission-checks, and
    serializes. Returns the raw JSON array of flat exported records.

    NOTE this does NOT reconcile requested against returned ids — the route
    silently omits ids it cannot serve (see the section comment above). Callers
    that care about completeness must diff the sets themselves.
    """
    ids = list(param_ids)
    if not ids:
        raise OnPingRequestError(
            "export_inference_params requires at least one parameter id; "
            "the route answers an empty list with an ambiguous 200 []."
        )

    response = _request(
        "POST",
        "/inferno/ml/inference/export",
        access_token,
        json_body=ids,
    )
    payload = _json_response(response)
    if not isinstance(payload, list):
        raise OnPingRequestError(
            f"Expected export response to be a JSON array, got {type(payload).__name__}."
        )
    return payload


# ---------------------------------------------------------------------------
# Inferno script routes (version-control metadata)
#
# An inference parameter carries NO model reference. `params` has no model
# column and no table links a parameter to a model. The link lives in the
# SCRIPT's version-control metadata:
#
#   [...].author.scriptTypes[] = { "tag": "MLInferenceScript",
#                                  "contents": { "models": { ident: uuid },
#                                                "inputs": { ident: "r"|"w"|"rw" } } }
#
# `models` maps an Inferno identifier to a model VERSION id (Id ModelVersion),
# NOT a parent model id. See InferenceOptions at
# plow-inferno/src/Plow/Inferno/Types/Metadata.hs, whose own comment reads
# "This is how model selections are linked to scripts".
#
# In Postgres the junction is `mselections (script, model, ident)`, keyed on
# script hash and NEVER on parameter id, which is why inspecting a parameter
# never reveals the link. `saveInferenceScript` writes those rows from this
# same metadata, so the two agree by construction.
#
# API shape:
#   POST /scripts/by-hash   body: [hash, ...]  → [[hash, VCMeta], ...]
#   GET  /script/id/{hash}                     → [VCMeta, sessionUuid, bool, history]
#
# Prefer scripts_by_hash(): it batches, and GET /script/id/ mints an LSP
# session UUID and mutates the server's session map (onping/Handler/Inferno/
# Scripts.hs) because that route exists to open the editor.
#
# CAUTION: script hashes are base64 and commonly end in '='. Every hash placed
# in a URL path MUST be percent-encoded ('=' → '%3D').
# ---------------------------------------------------------------------------

ML_SCRIPT_TAG = "MLInferenceScript"


def scripts_by_hash(
    access_token: str,
    script_hashes: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """POST /scripts/by-hash — script metadata for one or more hashes.

    Returns a dict keyed by script hash, each value the script's VCMeta object
    (carrying `author`, `name`, `description`, `obj`, `visibility`, ...).

    Preferred over get_script(): batches, and causes no LSP-session side effect.

    A hash the caller cannot reach is absent from the result rather than
    raising, mirroring the route. Callers that need completeness must diff the
    requested hashes against the returned keys.
    """
    hashes = list(dict.fromkeys(script_hashes))
    if not hashes:
        raise OnPingRequestError("scripts_by_hash requires at least one script hash.")

    response = _request(
        "POST",
        "/scripts/by-hash",
        access_token,
        json_body=hashes,
    )
    payload = _json_response(response)
    if not isinstance(payload, list):
        raise OnPingRequestError(
            f"Expected /scripts/by-hash to return a JSON array, got {type(payload).__name__}."
        )

    result: dict[str, dict[str, Any]] = {}
    for entry in payload:
        # Each entry is a [hash, VCMeta] pair.
        if not isinstance(entry, list) or len(entry) != 2:
            raise OnPingRequestError(
                "Expected /scripts/by-hash entries to be [hash, VCMeta] pairs; "
                f"got {type(entry).__name__} with "
                f"{len(entry) if isinstance(entry, list) else 'n/a'} elements."
            )
        script_hash, vcmeta = entry
        if not isinstance(vcmeta, dict):
            raise OnPingRequestError(
                f"Script metadata for {script_hash} is not a JSON object."
            )
        result[script_hash] = vcmeta
    return result


def get_script(access_token: str, script_hash: str) -> dict[str, Any]:
    """GET /script/id/{hash} — full editor payload for one script.

    Returns a dict with keys `meta` (the VCMeta), `session_uuid`, `editable`,
    and `history` (a list of VCMeta records, newest first), unpacked from the
    route's positional 4-tuple.

    Prefer scripts_by_hash() for programmatic reads. This route mints an LSP
    session UUID and writes the server's session map, because it exists to open
    the script editor. Use it when the history or the editable flag is needed.
    """
    if not script_hash:
        raise OnPingRequestError("script_hash is required.")
    from urllib.parse import quote

    encoded = quote(script_hash, safe="")
    response = _request("GET", f"/script/id/{encoded}", access_token)
    payload = _json_response(response)
    if not isinstance(payload, list) or len(payload) < 1:
        raise OnPingRequestError(
            f"Expected /script/id/ to return a tuple-shaped array, got {type(payload).__name__}."
        )
    meta = payload[0]
    if not isinstance(meta, dict):
        raise OnPingRequestError("Script metadata (element 0) is not a JSON object.")
    history = payload[3] if len(payload) > 3 and isinstance(payload[3], list) else []
    return {
        "meta": meta,
        "session_uuid": payload[1] if len(payload) > 1 else None,
        "editable": payload[2] if len(payload) > 2 else None,
        "history": history,
    }


def extract_ml_models(vcmeta: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Pull the ident → model-version-id map out of a script's VCMeta.

    Returns (models, script_types_found).

    `scriptTypes` is a LIST and is scanned by tag: the ML entry is not
    necessarily element 0. The frontend often matches a single element, while
    the backend concatMaps over the list (onping/Handler/Inferno/Scripts.hs).

    An ML script with no `models` key yields an empty dict — the field is parsed
    server-side with `.:? ... .!= mempty`, so it can be absent on older scripts.
    An empty dict with 'MLInferenceScript' in script_types_found therefore means
    "no models selected", which callers MUST distinguish from a non-ML script
    (where the tag is absent from script_types_found entirely).

    NOTE `author` holds PlowMetadata, not a user id; the actual user is
    author.author. The model map living under `author` is not a naming error.
    """
    author = vcmeta.get("author")
    if not isinstance(author, dict):
        # Older encodings serialize `author` as a bare user id, which carries
        # no script types at all.
        return {}, []

    script_types = author.get("scriptTypes")
    if not isinstance(script_types, list):
        return {}, []

    found: list[str] = []
    models: dict[str, str] = {}
    for entry in script_types:
        if isinstance(entry, str):
            # Legacy textual representation, e.g. "VirtualParameterScript".
            found.append(entry)
            continue
        if not isinstance(entry, dict):
            continue
        tag = entry.get("tag")
        if isinstance(tag, str):
            found.append(tag)
        if tag != ML_SCRIPT_TAG:
            continue
        contents = entry.get("contents")
        if not isinstance(contents, dict):
            continue
        raw = contents.get("models")
        if isinstance(raw, dict):
            for ident, version_id in raw.items():
                models[str(ident)] = str(version_id)
    return models, found
