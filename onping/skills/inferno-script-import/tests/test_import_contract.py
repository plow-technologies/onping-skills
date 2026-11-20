"""Contract tests for inferno-script-import against the /script/{vp,cp,ml}/import wire format.

Shapes follow onping-frontend-types (ExportedScript, ScriptImported,
ScriptImportRejected) and OnpingResponse's {"error"} / {"typed-error"}
envelopes. Synthetic hashes and UUIDs throughout.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_inferno_script.py"
spec = importlib.util.spec_from_file_location("import_inferno_script", SCRIPT)
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)

OLD_HASH = "A" * 43 + "="
NEW_HASH = "B" * 43 + "="
MODEL_VERSION = "00000000-0000-4000-8000-000000000001"


def exported(**overrides) -> dict:
    script = {
        "hash": OLD_HASH,
        "name": "synthetic script",
        "args": ["input0", "model_x"],
        "body": "input0",
        "type": "double -> 'a -> double",
        "author": "000000000000000000000001",
        "group": "000000000000000000000002",
        "visibility": "VCObjectPrivate",
        "timestamp": 0,
        "models": {},
    }
    script.update(overrides)
    return script


def ml_exported(**overrides) -> dict:
    """An ML export in the onping 2026.10.13 (#16217) shape: models, inputs, outputs."""
    script = exported(
        args=["model_m1", "flow", "pred"],
        body="pred",
        type="modelName → series of double → write → array of write",
        models={"model_m1": MODEL_VERSION},
        inputs={"flow": "r"},
        outputs=["pred"],
    )
    script.update(overrides)
    return script


def for_kind(kind: str) -> dict:
    return ml_exported() if kind == "ml" else exported()


class FakeResponse:
    def __init__(self, status: int, body, headers: dict | None = None):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def post(monkeypatch):
    calls: list[dict] = []
    replies: list[FakeResponse] = []

    def fake_post(url, headers=None, data=None, **kwargs):
        calls.append({"url": url, "headers": headers, "body": json.loads(data), **kwargs})
        return replies.pop(0)

    monkeypatch.setattr(imp.requests, "post", fake_post)
    return calls, replies


def run(monkeypatch, tmp_path, argv: list[str], script) -> int:
    path = tmp_path / "script.json"
    path.write_text(script if isinstance(script, str) else json.dumps(script))
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setattr("sys.argv", ["import_inferno_script.py", "--input", str(path), *argv])
    try:
        imp.main()
    except SystemExit as e:
        return e.code or 0
    return 0


def test_default_previews_and_sends_nothing(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "vp"], exported()) == 0
    assert calls == []
    out = capsys.readouterr()
    assert "DRY RUN" in out.err
    assert f"UPDATE if this server has {OLD_HASH}" in out.out
    assert "/script/vp/import" in out.out


def test_preview_names_cp_route(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "cp"], exported()) == 0
    assert calls == []
    assert "/script/cp/import (--kind cp)" in capsys.readouterr().out


def test_retired_route_is_never_used():
    # #16187: /script/import is 404 in production; there is no fallback to it.
    assert "/script/import" not in imp.ROUTES.values()


def test_dry_run_wins_over_yes(monkeypatch, tmp_path, post):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes", "--dry-run"], exported()) == 0
    assert calls == []


@pytest.mark.parametrize("hash_value", [None, "absent"])
def test_preview_without_hash_is_create(monkeypatch, tmp_path, post, capsys, hash_value):
    script = exported(hash=hash_value)
    if hash_value == "absent":
        del script["hash"]
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--json"], script) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["plan"].startswith("CREATE a new script in group")
    assert info["hash"] is None


def test_as_new_sends_null_hash(monkeypatch, tmp_path, post):
    calls, replies = post
    replies.append(FakeResponse(200, {
        "hash": NEW_HASH, "name": "synthetic script", "type": "double", "inputs": ["input0"],
        "warnings": [], "updatedFrom": None,
    }))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--as-new", "--yes"], exported()) == 0
    assert calls[0]["body"]["hash"] is None


@pytest.mark.parametrize(
    "kind,route",
    [("vp", "/script/vp/import"), ("cp", "/script/cp/import"), ("ml", "/script/ml/import")],
)
def test_kind_selects_route_and_sends_json(monkeypatch, tmp_path, post, kind, route):
    calls, replies = post
    replies.append(FakeResponse(200, {
        "hash": NEW_HASH, "name": "synthetic script", "type": "double", "inputs": [],
        "warnings": [], "updatedFrom": None,
    }))
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], for_kind(kind)) == 0
    assert calls[0]["url"].endswith(route)
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert calls[0]["headers"]["Authorization"] == "Bearer TOKEN"
    assert calls[0]["allow_redirects"] is False


def test_created_vs_updated(monkeypatch, tmp_path, post, capsys):
    _, replies = post
    replies.append(FakeResponse(200, {
        "hash": NEW_HASH, "name": "synthetic script", "type": "double", "inputs": [],
        "warnings": [], "updatedFrom": OLD_HASH,
    }))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported()) == 0
    assert f"UPDATED 'synthetic script': {OLD_HASH} -> {NEW_HASH}" in capsys.readouterr().out

    replies.append(FakeResponse(200, {
        "hash": NEW_HASH, "name": "synthetic script", "type": "double", "inputs": [],
        "warnings": [], "updatedFrom": None,
    }))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes", "--json"], exported()) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "created"


def test_typed_error_is_rejection_exit_3(monkeypatch, tmp_path, post, capsys):
    _, replies = post
    replies.append(FakeResponse(422, {"typed-error": {"diagnostics": [{
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        "severity": "error",
        "source": "inferno.import.version",
        "message": "This file was exported from version X, but the script has been updated since.",
    }]}}))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported()) == imp.EXIT_REJECTED
    err = capsys.readouterr().err
    assert "REJECTED (HTTP 422) with 1 diagnostic(s)" in err
    assert "file error inferno.import.version" in err
    assert "export the latest version" in err


def script_type_rejection(script_type: str) -> FakeResponse:
    # Import.hs wrongScriptTypeDiagnostic; "a script with no script type" when the script has none.
    return FakeResponse(422, {"typed-error": {"diagnostics": [{
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        "severity": "error",
        "source": "inferno.import.scriptType",
        "message": f"This file was exported from {script_type}, which can't be updated "
        "through this import route. Import it through the route for its script type.",
    }]}})


@pytest.mark.parametrize(
    "kind,script_type,target",
    [
        ("vp", "a control parameter script", "cp"),
        ("ml", "a control parameter script", "cp"),
        ("cp", "a virtual parameter script", "vp"),
        ("vp", "a Inferno ML inference script", "ml"),
        ("cp", "a Inferno ML inference script", "ml"),
        ("ml", "a virtual parameter script", "vp"),
    ],
)
def test_script_type_hint_names_kind(monkeypatch, tmp_path, post, capsys, kind, script_type, target):
    _, replies = post
    replies.append(script_type_rejection(script_type))
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], for_kind(kind)) == imp.EXIT_REJECTED
    err = capsys.readouterr().err
    assert f"retry with --kind {target}" in err
    assert "no import route" not in err


@pytest.mark.parametrize(
    "script_type",
    ["a mask script", "a Inferno ML training script", "a script with no script type"],
)
def test_script_type_without_route_suggests_no_kind(monkeypatch, tmp_path, post, capsys, script_type):
    _, replies = post
    replies.append(script_type_rejection(script_type))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported()) == imp.EXIT_REJECTED
    err = capsys.readouterr().err
    assert "no import route updates" in err
    assert "--kind" not in err.split("->", 1)[1]


@pytest.mark.parametrize(
    "kind,expected",
    [("vp", "function, array, tuple, `rep`, open record, or nested record"),
     ("cp", "function, array, tuple, `rep`, open record, or nested record"),
     ("ml", "`array of write`")],
)
def test_output_hint_follows_kind(monkeypatch, tmp_path, post, capsys, kind, expected):
    _, replies = post
    replies.append(FakeResponse(422, {"typed-error": {"diagnostics": [{
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        "severity": "error",
        "source": "inferno.import.output",
        "message": "Invalid output, output cannot be: double",
    }]}}))
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], for_kind(kind)) == imp.EXIT_REJECTED
    err = capsys.readouterr().err
    assert expected in err
    if kind != "ml":
        assert "array of write" not in err


def test_body_diagnostic_positions_are_shown_1_based(monkeypatch, tmp_path, post, capsys):
    # Live 2026-10-01: an error on body line 3, column 3 came back as line 2, character 2.
    _, replies = post
    diagnostic = {
        "range": {"start": {"line": 2, "character": 2}, "end": {"line": 2, "character": 3}},
        "severity": "error",
        "source": "inferno.infer",
        "message": "Could not find any matching definitions for\n  addition on double text _",
    }
    replies.append(FakeResponse(422, {"typed-error": {"diagnostics": [diagnostic]}}))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported()) == imp.EXIT_REJECTED
    assert "3:3-3:4 error inferno.infer" in capsys.readouterr().err

    replies.append(FakeResponse(422, {"typed-error": {"diagnostics": [diagnostic]}}))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes", "--json"], exported()) == imp.EXIT_REJECTED
    assert json.loads(capsys.readouterr().out)["diagnostics"] == [diagnostic]


def test_401_says_token_expired(monkeypatch, tmp_path, post, capsys):
    _, replies = post
    replies.append(FakeResponse(401, {"error": "NotAuthenticated"}))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported()) == 1
    assert "expired or invalid" in capsys.readouterr().err


def test_json_404_names_missing_route(monkeypatch, tmp_path, post, capsys):
    # Live 2026-10-11: an authenticated POST to the retired /script/import got 404 {"error":"NotFound"}.
    _, replies = post
    replies.append(FakeResponse(404, {"error": "NotFound"}))
    assert run(monkeypatch, tmp_path, ["--kind", "cp", "--yes"], exported()) == 1
    err = capsys.readouterr().err
    assert "HTTP 404: NotFound" in err
    assert "no /script/cp/import route" in err


@pytest.mark.parametrize("status", [400, 403, 500])
def test_error_envelope_exits_1(monkeypatch, tmp_path, post, capsys, status):
    _, replies = post
    replies.append(FakeResponse(status, {"error": "The current user cannot edit the script this file was exported from."}))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported()) == 1
    assert f"HTTP {status}: The current user cannot edit" in capsys.readouterr().err


def test_login_redirect_exits_1(monkeypatch, tmp_path, post, capsys):
    _, replies = post
    replies.append(FakeResponse(303, "", {"Location": "https://onping.example/auth/login"}))
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported()) == 1
    assert "token may be expired" in capsys.readouterr().err


def test_html_body_exits_1(monkeypatch, tmp_path, post, capsys):
    _, replies = post
    replies.append(FakeResponse(404, "<!DOCTYPE html><html></html>"))
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported()) == 1
    assert "is the route deployed" in capsys.readouterr().err


def test_array_is_refused(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], [exported(), exported()]) == 1
    assert calls == []
    assert "list of 2 scripts" in capsys.readouterr().err


def test_blank_name_is_refused(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], exported(name="  ")) == 1
    assert calls == []
    assert "cannot be blank" in capsys.readouterr().err


def test_missing_field_is_refused(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    script = exported()
    del script["body"]
    assert run(monkeypatch, tmp_path, ["--kind", "vp", "--yes"], script) == 1
    assert calls == []
    assert "'body'" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["vp", "cp"])
def test_vp_or_cp_with_models_is_refused(monkeypatch, tmp_path, post, capsys, kind):
    calls, _ = post
    script = exported(models={"model_x": MODEL_VERSION})
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], script) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "--kind ml" in err
    assert f"The {kind.upper()} route" in err


def test_ml_models_are_checked(monkeypatch, tmp_path, post, capsys):
    calls, replies = post
    bad = exported(models={"model_y": MODEL_VERSION, "model_x": "not-a-uuid"})
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], bad) == 1
    err = capsys.readouterr().err
    assert "model_y is not an argument" in err
    assert "'not-a-uuid'" in err
    assert calls == []

    replies.append(FakeResponse(200, {
        "hash": NEW_HASH, "name": "synthetic script", "type": "double", "inputs": [],
        "warnings": [], "updatedFrom": None,
    }))
    good = exported(models={"model_x": MODEL_VERSION}, inputs={"input0": "r"}, outputs=[])
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], good) == 0
    assert calls[0]["body"]["models"] == {"model_x": MODEL_VERSION}


def test_invalid_json_is_refused(monkeypatch, tmp_path, post, capsys):
    assert run(monkeypatch, tmp_path, ["--kind", "vp"], "{not json") == 1
    assert "not valid JSON" in capsys.readouterr().err


# --- #16217: ML inputs and outputs (onping 2026.10.13) ---------------------------------

def io_rejection() -> FakeResponse:
    # checkInputOutputArguments, source inferno.import.io.
    return FakeResponse(422, {"typed-error": {"diagnostics": [{
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        "severity": "error",
        "source": "inferno.import.io",
        "message": "The argument flow is not listed as an input, an output or a model.",
    }]}})


def created() -> FakeResponse:
    return FakeResponse(200, {
        "hash": NEW_HASH, "name": "synthetic script", "type": "double", "inputs": ["flow"],
        "warnings": [], "updatedFrom": None,
    })


def test_ml_new_format_is_sent_unchanged(monkeypatch, tmp_path, post):
    calls, replies = post
    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported()) == 0
    assert calls[0]["body"]["inputs"] == {"flow": "r"}
    assert calls[0]["body"]["outputs"] == ["pred"]


@pytest.mark.parametrize("flags", [["--yes"], []])
def test_old_ml_file_is_refused_without_request(monkeypatch, tmp_path, post, capsys, flags):
    calls, _ = post
    old = ml_exported()
    del old["inputs"], old["outputs"]
    assert run(monkeypatch, tmp_path, ["--kind", "ml", *flags], old) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "onping 2026.10.13 and later reject it" in err
    assert "--allow-old-ml-format" in err
    assert "inferno-script-export" in err
    assert "--ml-input" in err


@pytest.mark.parametrize(
    "args,models",
    [(["model_m1"], {"model_m1": MODEL_VERSION}), ([None], {}), ([], {})],
    ids=["only-models", "only-unnamed", "no-args"],
)
def test_old_ml_file_with_nothing_unlisted_is_sent(monkeypatch, tmp_path, post, args, models):
    # With no inputs and outputs the server still accepts a file whose every
    # named argument is a model (checkInputOutputArguments finds nothing).
    calls, replies = post
    replies.append(created())
    old = ml_exported(args=args, models=models)
    del old["inputs"], old["outputs"]
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], old) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("models", [{}, None], ids=["empty", "absent"])
def test_vp_or_cp_file_on_ml_suggests_vp_or_cp(monkeypatch, tmp_path, post, capsys, models):
    # An old VP/CP export has "models": {}; a current one has no models key.
    calls, _ = post
    script = exported(models={}) if models is not None else {k: v for k, v in exported().items() if k != "models"}
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], script) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "may not be an ML inference script" in err
    assert "--kind vp or --kind cp" in err


def test_null_inputs_and_outputs_count_as_absent(monkeypatch, tmp_path, post, capsys):
    # FromJSON reads them with .:?, which treats null as absent.
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported(inputs=None, outputs=None)) == 1
    assert calls == []
    assert "onping 2026.10.13 and later reject it" in capsys.readouterr().err


@pytest.mark.parametrize(
    "overrides,message",
    [
        # the server's import check
        ({"inputs": {"flow": "r", "ghost": "r"}}, "ghost is not an argument of the script."),
        ({"outputs": ["pred", "ghost"]}, "ghost is not an argument of the script."),
        # the server's import check
        ({"inputs": {}, "outputs": ["pred"]}, "The argument flow is not listed as an input, an output or a model."),
        # the server's import check, roles joined with " and "
        ({"outputs": ["flow", "pred"]}, "The argument flow is listed as an input and an output."),
        ({"outputs": ["pred", "model_m1"]}, "The argument model_m1 is listed as an output and a model."),
        ({"inputs": {"flow": "r", "model_m1": "r"}, "outputs": ["pred", "model_m1"]},
         "The argument model_m1 is listed as an input and an output and a model."),
    ],
)
def test_io_messages_match_the_server(monkeypatch, tmp_path, post, capsys, overrides, message):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported(**overrides)) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "inferno.import.io" in err
    assert f"  - {message}\n" in err


def test_null_arg_is_ignored(monkeypatch, tmp_path, post):
    # the server's import check: argNames = [name | Just (Ident name) <- args]
    calls, replies = post
    replies.append(created())
    script = ml_exported(args=["model_m1", None, "flow", "pred"])
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], script) == 0
    assert calls[0]["body"]["args"] == ["model_m1", None, "flow", "pred"]


@pytest.mark.parametrize("mode", ["read", "R", "", 1])
def test_bad_input_mode_is_refused(monkeypatch, tmp_path, post, capsys, mode):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported(inputs={"flow": mode})) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert f"flow: {mode!r}" in err
    assert '"r", "w" or "rw"' in err


@pytest.mark.parametrize(
    "overrides",
    [{"inputs": ["flow"]}, {"outputs": "pred"}, {"outputs": [1]}],
)
def test_bad_inputs_or_outputs_shape_is_refused(monkeypatch, tmp_path, post, overrides):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported(**overrides)) == 1
    assert calls == []


def test_ml_input_splits_the_args(monkeypatch, tmp_path, post, capsys):
    calls, replies = post
    old = ml_exported()
    del old["inputs"], old["outputs"]

    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", "flow"], old) == 0
    out = capsys.readouterr().out
    assert "inputs: flow (r) (set by --ml-input)" in out
    assert "outputs: pred (set by --ml-input)" in out

    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", "flow", "--json"], old) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["inputs"] == {"flow": "r"}
    assert info["outputs"] == ["pred"]
    assert info["inputsFrom"] == "--ml-input"

    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", "flow", "--yes"], old) == 0
    assert calls[0]["body"]["inputs"] == {"flow": "r"}
    assert calls[0]["body"]["outputs"] == ["pred"]
    assert calls[0]["body"]["models"] == {"model_m1": MODEL_VERSION}


def test_ml_input_modes_and_replacing_a_mangled_split(monkeypatch, tmp_path, post):
    calls, replies = post
    script = ml_exported(args=["model_m1", "flow", "level", "pred"], inputs={}, outputs=["flow", "level", "pred"])
    replies.append(created())
    argv = ["--kind", "ml", "--ml-input", "flow=rw", "--ml-input", "level=w", "--yes"]
    assert run(monkeypatch, tmp_path, argv, script) == 0
    assert calls[0]["body"]["inputs"] == {"flow": "rw", "level": "w"}
    assert calls[0]["body"]["outputs"] == ["pred"]


def test_ml_input_keeps_duplicate_args_like_the_export(monkeypatch, tmp_path, post):
    # Live 2026-10-15: a production ML script names one argument twice, and its
    # export lists it twice in `outputs` (the server's export rule does not dedupe).
    calls, replies = post
    script = ml_exported(args=["model_m1", "flow", "pred", "pred"], inputs={}, outputs=["flow", "pred", "pred"])
    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", "flow", "--yes"], script) == 0
    assert calls[0]["body"]["outputs"] == ["pred", "pred"]


@pytest.mark.parametrize(
    "value,message",
    [
        # Reported by _io_problems on the rewritten split, in the server's wording.
        ("ghost", "  - ghost is not an argument of the script.\n"),
        ("model_m1", "  - The argument model_m1 is listed as an input and a model.\n"),
    ],
)
def test_ml_input_not_matching_the_file_is_refused(monkeypatch, tmp_path, post, capsys, value, message):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", value, "--yes"], ml_exported()) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "set by --ml-input" in err and "inferno.import.io" in err
    assert message in err


@pytest.mark.parametrize(
    "values,message",
    [
        (["flow=x"], "mode 'x' is not one of r, w, rw"),
        (["=r"], "the argument name is blank"),
        (["flow=r", "flow=w"], "names flow twice"),
    ],
)
def test_malformed_ml_input_is_a_usage_error(monkeypatch, tmp_path, post, capsys, values, message):
    calls, _ = post
    flags = [f for v in values for f in ("--ml-input", v)]
    assert run(monkeypatch, tmp_path, ["--kind", "ml", *flags, "--yes"], ml_exported()) == 2
    assert calls == []
    assert message in capsys.readouterr().err


def test_ml_input_shows_the_split_it_replaces(monkeypatch, tmp_path, post, capsys):
    script = ml_exported(args=["model_m1", "flow", "level", "pred"], inputs={"flow": "rw"},
                         outputs=["level", "pred"])
    argv = ["--kind", "ml", "--ml-input", "level"]
    assert run(monkeypatch, tmp_path, argv, script) == 0
    captured = capsys.readouterr()
    assert "inputs: level (r) (set by --ml-input)" in captured.out
    assert "outputs: flow, pred (set by --ml-input)" in captured.out
    assert "file inputs (replaced): flow (rw)\n" in captured.out
    assert "file outputs (replaced): level, pred\n" in captured.out
    assert "replaces the file's own inputs and outputs" in captured.err

    assert run(monkeypatch, tmp_path, [*argv, "--json"], script) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["replaced"] == {"inputs": {"flow": "rw"}, "outputs": ["level", "pred"]}
    assert any("replaces the file's own inputs and outputs" in w for w in info["warnings"])


def test_ml_input_on_an_old_file_replaces_nothing(monkeypatch, tmp_path, post, capsys):
    old = ml_exported()
    del old["inputs"], old["outputs"]
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", "flow", "--json"], old) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["replaced"] is None
    assert info["warnings"] == []


@pytest.mark.parametrize("kind", ["vp", "cp"])
@pytest.mark.parametrize("flag", [["--ml-input", "flow"], ["--allow-empty-inputs"]])
def test_ml_only_flags_are_refused_on_vp_and_cp(monkeypatch, tmp_path, post, capsys, kind, flag):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", kind, *flag, "--yes"], exported()) == 2
    assert calls == []
    assert "--kind ml only" in capsys.readouterr().err


def mangled() -> dict:
    # A script imported before onping 2026.10.13 has no inputs; its export lists
    # every non-model argument as an output (the server's export rule).
    return ml_exported(inputs={}, outputs=["flow", "pred"])


def test_mangled_file_warns_in_preview(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml"], mangled()) == 0
    assert calls == []
    captured = capsys.readouterr()
    assert "inputs: none" in captured.out
    assert "likely imported before onping 2026.10.13" in captured.err

    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--json"], mangled()) == 0
    assert "likely imported before" in json.loads(capsys.readouterr().out)["warnings"][0]


def test_mangled_file_blocks_yes(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], mangled()) == imp.EXIT_REFUSED
    assert calls == []
    err = capsys.readouterr().err
    assert "likely imported before onping 2026.10.13" in err
    assert "--ml-input" in err and "--allow-empty-inputs" in err


def without_inputs() -> dict:
    script = mangled()
    del script["inputs"]
    return script


@pytest.mark.parametrize(
    "script",
    [without_inputs(), ml_exported(inputs=None, outputs=["flow", "pred"])],
    ids=["absent", "null"],
)
def test_absent_or_null_inputs_count_as_mangled(monkeypatch, tmp_path, post, capsys, script):
    # The server decodes an absent or null `inputs` as {} (.:? then mempty).
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml"], script) == 0
    captured = capsys.readouterr()
    assert "inputs: none" in captured.out
    assert "no `inputs` and 2 output(s)" in captured.err

    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], script) == imp.EXIT_REFUSED
    assert calls == []
    assert "likely imported before onping 2026.10.13" in capsys.readouterr().err


def test_preview_warning_respects_allow_empty_inputs(monkeypatch, tmp_path, post, capsys):
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-empty-inputs"], mangled()) == 0
    err = capsys.readouterr().err
    assert "--allow-empty-inputs is set" in err
    assert "or pass --allow-empty-inputs" not in err

    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-empty-inputs", "--json"], mangled()) == 0
    (warning,) = json.loads(capsys.readouterr().out)["warnings"]
    assert "--allow-empty-inputs is set" in warning


def test_mangled_file_sends_with_allow_empty_inputs(monkeypatch, tmp_path, post):
    calls, replies = post
    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes", "--allow-empty-inputs"], mangled()) == 0
    assert calls[0]["body"]["inputs"] == {}


def test_mangled_file_sends_with_ml_input(monkeypatch, tmp_path, post):
    calls, replies = post
    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes", "--ml-input", "flow"], mangled()) == 0
    assert calls[0]["body"]["inputs"] == {"flow": "r"}
    assert calls[0]["body"]["outputs"] == ["pred"]


@pytest.mark.parametrize("kind", ["vp", "cp"])
@pytest.mark.parametrize("overrides", [{"inputs": {"input0": "r"}}, {"outputs": ["input0"]}])
def test_vp_or_cp_with_inputs_or_outputs_is_refused(monkeypatch, tmp_path, post, capsys, kind, overrides):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], exported(**overrides)) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "would drop them silently" in err
    assert "--kind ml" in err


@pytest.mark.parametrize("kind", ["vp", "cp"])
def test_vp_or_cp_with_empty_inputs_and_outputs_is_sent(monkeypatch, tmp_path, post, kind):
    calls, replies = post
    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], exported(inputs={}, outputs=[])) == 0
    assert len(calls) == 1


def test_server_io_rejection_has_hint_and_exits_3(monkeypatch, tmp_path, post, capsys):
    _, replies = post
    replies.append(io_rejection())
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported()) == imp.EXIT_REJECTED
    err = capsys.readouterr().err
    assert "file error inferno.import.io: The argument flow is not listed" in err
    hint = err.split("->", 1)[1]
    for word in ("`inputs`", "`outputs`", "`models`", "re-export", "onping 2026.10.13", "--ml-input"):
        assert word in hint


def test_preview_lists_models_inputs_and_outputs(monkeypatch, tmp_path, post, capsys):
    assert run(monkeypatch, tmp_path, ["--kind", "ml"], ml_exported(inputs={"flow": "rw"})) == 0
    out = capsys.readouterr().out
    assert f"models: {{'model_m1': '{MODEL_VERSION}'}}" in out
    assert "inputs: flow (rw)\n" in out
    assert "outputs: pred\n" in out


# --- PR #17 review fixes -----------------------------------------------------


def test_ml_input_over_a_malformed_split_shows_raw_json(monkeypatch, tmp_path, post, capsys):
    # Reproduced crash: `replaced` held a list `inputs` and a string `outputs`.
    calls, _ = post
    script = ml_exported(args=["model_m1", "a", "b"], inputs=["a"], outputs="b")
    argv = ["--kind", "ml", "--ml-input", "a"]
    assert run(monkeypatch, tmp_path, argv, script) == 0
    assert calls == []
    out = capsys.readouterr().out
    assert 'file inputs (replaced): ["a"] (malformed)\n' in out
    assert 'file outputs (replaced): "b" (malformed)\n' in out
    assert "inputs: a (r) (set by --ml-input)" in out

    assert run(monkeypatch, tmp_path, [*argv, "--json"], script) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["replaced"] == {"inputs": ["a"], "outputs": "b"}
    assert info["inputs"] == {"a": "r"}
    assert info["outputs"] == ["b"]


def test_text_helpers_never_split_a_string():
    assert imp._outputs_text("pred") == '"pred" (malformed)'
    assert imp._outputs_text(["a", 1]) == '["a", 1] (malformed)'
    assert imp._inputs_text(["a"]) == '["a"] (malformed)'
    assert imp._inputs_text({"a": 1}) == '{"a": 1} (malformed)'
    assert imp._inputs_text(None) == "none"
    assert imp._outputs_text([]) == "none"


def old_ml() -> dict:
    script = ml_exported()
    del script["inputs"], script["outputs"]
    return script


def test_allow_old_ml_format_sends_the_file_unchanged(monkeypatch, tmp_path, post, capsys):
    calls, replies = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-old-ml-format", "--json"], old_ml()) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["oldFormat"] is True
    assert any("onping 2026.10.13 and later reject it" in w for w in info["warnings"])
    assert calls == []

    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-old-ml-format", "--yes"], old_ml()) == 0
    assert "inputs" not in calls[0]["body"] and "outputs" not in calls[0]["body"]
    assert calls[0]["body"]["models"] == {"model_m1": MODEL_VERSION}


def test_allow_old_ml_format_skips_the_suggest_vp_or_cp_refusal(monkeypatch, tmp_path, post):
    calls, replies = post
    replies.append(created())
    script = exported(models=None)
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-old-ml-format", "--yes"], script) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["vp", "cp"])
def test_allow_old_ml_format_is_a_usage_error_on_vp_and_cp(monkeypatch, tmp_path, post, capsys, kind):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--allow-old-ml-format", "--yes"], exported()) == 2
    assert calls == []
    assert "--allow-old-ml-format is for --kind ml only" in capsys.readouterr().err


def test_mangled_yes_json_prints_a_structured_refusal(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes", "--json"], mangled()) == imp.EXIT_REFUSED
    assert imp.EXIT_REFUSED == 4
    assert calls == []
    info = json.loads(capsys.readouterr().out)
    assert info["mode"] == "refused" and info["status"] == "refused"
    assert info["exitCode"] == 4
    assert "Nothing was sent" in info["error"]
    assert "likely imported before onping 2026.10.13" in info["warnings"][0]
    assert info["inputs"] == {} and info["outputs"] == ["flow", "pred"]


@pytest.mark.parametrize("kind", ["vp", "cp"])
@pytest.mark.parametrize(
    "overrides",
    [{"inputs": []}, {"outputs": {}}, {"outputs": "x"}, {"outputs": [1]}, {"models": []}, {"inputs": "r"}],
    ids=["inputs-list", "outputs-object", "outputs-string", "outputs-int", "models-list", "inputs-string"],
)
def test_vp_or_cp_with_a_wrong_shape_is_refused_locally(monkeypatch, tmp_path, post, capsys, kind, overrides):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], exported(**overrides)) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "HTTP 400" in err
    assert f"`{next(iter(overrides))}` must be" in err


@pytest.mark.parametrize("kind", ["vp", "cp"])
@pytest.mark.parametrize(
    "overrides",
    [{"inputs": {}}, {"outputs": []}, {"inputs": None, "outputs": None, "models": None}, {"models": {}}],
    ids=["inputs-empty", "outputs-empty", "all-null", "models-empty"],
)
def test_vp_or_cp_with_an_empty_value_of_the_right_shape_is_sent(monkeypatch, tmp_path, post, kind, overrides):
    calls, replies = post
    replies.append(created())
    assert run(monkeypatch, tmp_path, ["--kind", kind, "--yes"], exported(**overrides)) == 0
    assert len(calls) == 1


def test_ml_models_with_a_wrong_shape_is_refused_locally(monkeypatch, tmp_path, post, capsys):
    calls, _ = post
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--yes"], ml_exported(models=[])) == 1
    assert calls == []
    assert "HTTP 400" in capsys.readouterr().err


def test_no_replacement_warning_when_the_split_is_the_same(monkeypatch, tmp_path, post, capsys):
    # ml_exported() is already {"flow": "r"} / ["pred"]: --ml-input flow changes nothing.
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", "flow", "--json"], ml_exported()) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["replaced"] is None
    assert info["warnings"] == []

    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--ml-input", "flow"], ml_exported()) == 0
    captured = capsys.readouterr()
    assert "replaced" not in captured.out
    assert "replaces the file's own" not in captured.err


def test_allow_empty_inputs_notice_when_the_file_is_not_mangled(monkeypatch, tmp_path, post, capsys):
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-empty-inputs"], ml_exported()) == 0
    assert "NOTICE: --allow-empty-inputs has no effect: the file is not missing its inputs." in (
        capsys.readouterr().err
    )


def test_allow_empty_inputs_notice_with_ml_input(monkeypatch, tmp_path, post, capsys):
    argv = ["--kind", "ml", "--allow-empty-inputs", "--ml-input", "flow"]
    assert run(monkeypatch, tmp_path, argv, mangled()) == 0
    assert "NOTICE: --allow-empty-inputs has no effect: --ml-input sets the inputs." in capsys.readouterr().err


def test_no_notice_when_allow_empty_inputs_is_used(monkeypatch, tmp_path, post, capsys):
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-empty-inputs"], mangled()) == 0
    assert "NOTICE" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv, script, why",
    [
        ([], "new", "the file is not in the old format"),
        (["--ml-input", "flow"], "old", "--ml-input sets the inputs and outputs"),
    ],
    ids=["new-format", "ml-input"],
)
def test_allow_old_ml_format_notice_when_it_has_no_effect(monkeypatch, tmp_path, post, capsys, argv, script, why):
    file = ml_exported() if script == "new" else old_ml()
    assert run(monkeypatch, tmp_path, ["--kind", "ml", "--allow-old-ml-format", *argv], file) == 0
    assert f"NOTICE: --allow-old-ml-format has no effect: {why}." in capsys.readouterr().err
