"""Contract tests for inferno-script-export against GET /script/export/{hash}.

The success body is a bare ExportedScript object (OnpingResponse's success
case); errors are {"error": ...}. Synthetic hashes throughout.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_inferno_script.py"
spec = importlib.util.spec_from_file_location("export_inferno_script", SCRIPT)
exp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp)

HASH = "A-_" + "A" * 40 + "="
OTHER_HASH = "B" * 43 + "="


def exported(**overrides) -> dict:
    script = {
        "hash": HASH,
        "name": "synthetic script",
        "args": ["input0"],
        "body": "input0",
        "type": "double -> double",
        "author": "000000000000000000000001",
        "group": "000000000000000000000002",
        "visibility": "VCObjectPrivate",
        "timestamp": 0,
    }
    # A VP/CP export since onping 2026.10.13 (#16217) has no models, inputs or outputs.
    script.update(overrides)
    return script


def ml_exported(**overrides) -> dict:
    script = exported(
        args=["model_m1", "flow", "pred"],
        models={"model_m1": "00000000-0000-4000-8000-000000000001"},
        inputs={"flow": "r"},
        outputs=["pred"],
    )
    script.update(overrides)
    return script


class FakeResponse:
    def __init__(self, status: int, body, headers: dict | None = None):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def get(monkeypatch):
    calls: list[dict] = []
    replies: list[FakeResponse] = []

    def fake_get(url, headers=None, **kwargs):
        calls.append({"url": url, "headers": headers, **kwargs})
        return replies.pop(0)

    monkeypatch.setattr(exp.requests, "get", fake_get)
    return calls, replies


def run(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setattr("sys.argv", ["export_inferno_script.py", *argv])
    try:
        exp.main()
    except SystemExit as e:
        return e.code or 0
    return 0


@pytest.mark.parametrize("bad", ["short=", "A" * 44, "A" * 43 + "+", "../" + "A" * 40 + "="])
def test_bad_hash_makes_no_request(monkeypatch, get, capsys, bad):
    calls, _ = get
    assert run(monkeypatch, [bad]) == 2
    assert calls == []
    assert "script hash" in capsys.readouterr().err


def test_hash_is_percent_encoded_in_path(monkeypatch, get):
    calls, replies = get
    replies.append(FakeResponse(200, exported()))
    assert run(monkeypatch, [HASH]) == 0
    assert calls[0]["url"].endswith("/script/export/" + HASH[:-1] + "%3D")
    assert calls[0]["headers"]["Authorization"] == "Bearer TOKEN"
    assert calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("before_options", [True, False])
def test_hash_starting_with_dash_is_a_positional(monkeypatch, get, tmp_path, before_options):
    # Live 2026-10-01: argparse read a '-…' hash as an unknown option.
    dash_hash = "-" + "A" * 42 + "="
    calls, replies = get
    replies.append(FakeResponse(200, exported(hash=dash_hash)))
    out = str(tmp_path / "script.json")
    argv = [dash_hash, "--output", out] if before_options else ["--output", out, dash_hash]
    assert run(monkeypatch, argv) == 0
    assert calls[0]["url"].endswith("/script/export/" + dash_hash[:-1] + "%3D")
    assert json.loads(Path(out).read_text())["hash"] == dash_hash


def test_writes_object_unchanged(monkeypatch, get, tmp_path, capsys):
    _, replies = get
    script = exported(models={"model_x": "00000000-0000-4000-8000-000000000001"}, extra="kept")
    replies.append(FakeResponse(200, script))
    out = tmp_path / "script.json"
    assert run(monkeypatch, [HASH, "--output", str(out)]) == 0
    assert json.loads(out.read_text()) == script
    assert "1 model(s)" in capsys.readouterr().out


def test_stdout_gets_only_the_json(monkeypatch, get, capsys):
    _, replies = get
    replies.append(FakeResponse(200, exported()))
    assert run(monkeypatch, [HASH]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == exported()
    assert "Exported 'synthetic script'" in captured.err


def test_hash_mismatch_fails(monkeypatch, get, capsys):
    _, replies = get
    replies.append(FakeResponse(200, exported(hash=OTHER_HASH)))
    assert run(monkeypatch, [HASH]) == 1
    assert "does not match" in capsys.readouterr().err


def test_list_response_fails(monkeypatch, get, capsys):
    _, replies = get
    replies.append(FakeResponse(200, [exported()]))
    assert run(monkeypatch, [HASH]) == 1
    assert "Expected one ExportedScript object" in capsys.readouterr().err


def test_json_404_vs_html_404(monkeypatch, get, capsys):
    _, replies = get
    replies.append(FakeResponse(404, {"error": "Script not found"}))
    assert run(monkeypatch, [HASH]) == 1
    assert "not found" in capsys.readouterr().err

    replies.append(FakeResponse(404, "<!DOCTYPE html><html></html>"))
    assert run(monkeypatch, [HASH]) == 1
    assert "not deployed" in capsys.readouterr().err


def test_unknown_hash_500_is_reported_as_missing(monkeypatch, get, capsys):
    # Live 2026-10-01: an unknown or deleted hash is a 500, not a 404.
    _, replies = get
    replies.append(FakeResponse(500, {"error": (
        'InternalError "TransientError (InfernoVCCommunicationsException (VCServerError '
        f'{{serverError = CouldNotFindPath \\"{HASH}\\"}}))"'
    )}))
    assert run(monkeypatch, [HASH]) == 1
    assert "never saved on this server, or it has been deleted" in capsys.readouterr().err


def test_401_says_token_expired(monkeypatch, get, capsys):
    _, replies = get
    replies.append(FakeResponse(401, {"error": "NotAuthenticated"}))
    assert run(monkeypatch, [HASH]) == 1
    assert "expired or invalid" in capsys.readouterr().err


def test_login_redirect_fails(monkeypatch, get, capsys):
    _, replies = get
    replies.append(FakeResponse(303, "", {"Location": "https://onping.example/auth/login"}))
    assert run(monkeypatch, [HASH]) == 1
    assert "token may be expired" in capsys.readouterr().err


def test_no_overwrite_without_force(monkeypatch, get, tmp_path, capsys):
    calls, replies = get
    out = tmp_path / "script.json"
    out.write_text("previous")
    assert run(monkeypatch, [HASH, "--output", str(out)]) == 1
    assert calls == []
    assert out.read_text() == "previous"
    assert "--force" in capsys.readouterr().err

    replies.append(FakeResponse(200, exported()))
    assert run(monkeypatch, [HASH, "--output", str(out), "--force"]) == 0
    assert json.loads(out.read_text()) == exported()


# --- #16217: ML inputs and outputs (onping 2026.10.13) ---------------------------------

def test_ml_summary_counts_inputs_and_outputs(monkeypatch, get, tmp_path, capsys):
    _, replies = get
    replies.append(FakeResponse(200, ml_exported()))
    out = tmp_path / "script.json"
    assert run(monkeypatch, [HASH, "--output", str(out)]) == 0
    captured = capsys.readouterr()
    assert "3 arg(s), 1 model(s), 1 input(s), 1 output(s)" in captured.out
    assert "WARNING" not in captured.err
    assert json.loads(out.read_text()) == ml_exported()


def test_ml_json_status_has_inputs_and_outputs(monkeypatch, get, tmp_path, capsys):
    _, replies = get
    replies.append(FakeResponse(200, ml_exported()))
    assert run(monkeypatch, [HASH, "--output", str(tmp_path / "s.json"), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["inputs"] == {"flow": "r"}
    assert status["outputs"] == ["pred"]


def test_vp_json_status_omits_inputs_and_outputs(monkeypatch, get, tmp_path, capsys):
    _, replies = get
    replies.append(FakeResponse(200, exported()))
    assert run(monkeypatch, [HASH, "--output", str(tmp_path / "s.json"), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert "inputs" not in status and "outputs" not in status


def test_vp_summary_has_no_input_output_counts(monkeypatch, get, capsys):
    _, replies = get
    replies.append(FakeResponse(200, exported()))
    assert run(monkeypatch, [HASH]) == 0
    err = capsys.readouterr().err
    assert "1 arg(s), 0 model(s)" in err
    assert "input(s)" not in err


@pytest.mark.parametrize("to_file", [True, False])
def test_mangled_ml_export_warns_and_still_writes(monkeypatch, get, tmp_path, capsys, to_file):
    _, replies = get
    mangled = ml_exported(inputs={}, outputs=["flow", "pred"])
    replies.append(FakeResponse(200, mangled))
    out = tmp_path / "script.json"
    argv = [HASH, "--output", str(out)] if to_file else [HASH]
    assert run(monkeypatch, argv) == 0
    captured = capsys.readouterr()
    assert "0 input(s), 2 output(s)" in (captured.out if to_file else captured.err)
    assert "likely imported before onping 2026.10.13" in captured.err
    written = json.loads(out.read_text()) if to_file else json.loads(captured.out)
    assert written == mangled


@pytest.mark.parametrize("inputs", ["absent", None], ids=["absent", "null"])
def test_absent_or_null_inputs_with_outputs_warn(monkeypatch, get, capsys, inputs):
    # The server decodes an absent or null `inputs` as {} (.:? then mempty).
    _, replies = get
    script = ml_exported(outputs=["flow", "pred"])
    if inputs == "absent":
        del script["inputs"]
    else:
        script["inputs"] = None
    replies.append(FakeResponse(200, script))
    assert run(monkeypatch, [HASH]) == 0
    assert "likely imported before onping 2026.10.13" in capsys.readouterr().err


IMPORT_SCRIPT = SCRIPT.parents[2] / "inferno-script-import" / "scripts" / "import_inferno_script.py"


@pytest.mark.skipif(not IMPORT_SCRIPT.exists(), reason="inferno-script-import is not next to this skill")
@pytest.mark.parametrize(
    "fields",
    [
        {"inputs": {}, "outputs": ["pred"]},
        {"outputs": ["pred"]},
        {"inputs": None, "outputs": ["pred"]},
        {"inputs": {"flow": "r"}, "outputs": ["pred"]},
        {"inputs": {}, "outputs": []},
        {"inputs": {}},
        {},
        {"inputs": None, "outputs": None},
    ],
)
def test_mangled_rule_matches_the_import_skill(fields):
    import_spec = importlib.util.spec_from_file_location("import_inferno_script", IMPORT_SCRIPT)
    imp = importlib.util.module_from_spec(import_spec)
    import_spec.loader.exec_module(imp)
    script = {"name": "s", **fields}
    assert exp.is_mangled(script) == imp.is_mangled(script)
