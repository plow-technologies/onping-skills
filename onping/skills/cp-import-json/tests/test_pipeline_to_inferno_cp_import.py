"""End to end: cp-list output -> cp-import-json normalize -> inferno-cp-import --dry-run.

Uses the sibling `inferno-cp-import` skill from the same checkout and skips when it
is not installed next to this one (skills install independently). No network:
inferno-cp-import's requests.post fails the test if it is called.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CIJ_SCRIPT = HERE.parent / "scripts" / "cp_import_json.py"
ICI_SCRIPT = HERE.parent.parent / "inferno-cp-import" / "scripts" / "import_inferno_cp.py"
FIXTURE_PATH = HERE / "fixtures" / "cpinferno-list-all-tags.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())

pytestmark = pytest.mark.skipif(not ICI_SCRIPT.exists(), reason="inferno-cp-import is not next to cp-import-json")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cij = load("cp_import_json_e2e", CIJ_SCRIPT)
ici = load("import_inferno_cp_e2e", ICI_SCRIPT) if ICI_SCRIPT.exists() else None


def run(monkeypatch, capsys, module, argv):
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        module.main()
    out, err = capsys.readouterr()
    return exc.value.code, out, err


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("inferno-cp-import sent a request")

    monkeypatch.setattr(ici.requests, "post", boom)


def normalize_then_dry_run(monkeypatch, capsys, tmp_path, cp_list_doc, *normalize_flags):
    listed = tmp_path / "cp-list.json"
    listed.write_text(json.dumps(cp_list_doc))
    normalized = tmp_path / "cps.json"
    code, _out, norm_err = run(
        monkeypatch,
        capsys,
        cij,
        ["cp_import_json.py", "normalize", "--input", str(listed), "--output", str(normalized), *normalize_flags],
    )
    assert code == 0
    code, out, err = run(
        monkeypatch, capsys, ici, ["import_inferno_cp.py", "TOKEN", "--input", str(normalized), "--dry-run"]
    )
    return code, out, err, norm_err, json.loads(normalized.read_text())


def test_cp_list_fixture_normalized_imports_cleanly(monkeypatch, capsys, tmp_path):
    code, out, err, norm_err, doc = normalize_then_dry_run(monkeypatch, capsys, tmp_path, copy.deepcopy(FIXTURE))
    assert code == 0, err
    assert "DRY RUN" in err
    assert "Would create/overwrite 1 Inferno CP(s)" in out
    assert "1001-00000000-0000-4000-8000-00000000c001" in out
    assert "omitted 1 orphaned CP(s)" in norm_err
    assert "omitted 2 not-readable element(s)" in norm_err
    assert len(doc) == 1


def test_include_orphans_pipeline_also_imports(monkeypatch, capsys, tmp_path):
    code, out, err, norm_err, doc = normalize_then_dry_run(
        monkeypatch, capsys, tmp_path, copy.deepcopy(FIXTURE), "--include-orphans"
    )
    assert code == 0, err
    assert "Would create/overwrite 2 Inferno CP(s)" in out
    assert "kept 1 orphaned CP(s)" in norm_err


def test_default_trigger_update_imports(monkeypatch, capsys, tmp_path):
    """normalize omits an update's OnInputChangeAny trigger, as the server's friendly format does."""
    readable = copy.deepcopy(FIXTURE[0])
    readable["contents"]["cpData"]["trigger"] = {"tag": "OnInputChange", "contents": {"tag": "OnInputChangeAny"}}
    code, out, err, _norm_err, doc = normalize_then_dry_run(monkeypatch, capsys, tmp_path, [readable])
    assert "trigger" not in doc[0]["cpData"]
    assert code == 0, err
    assert "trigger=<default: OnInputChangeAny>" in out


def test_export_json_update_without_trigger_round_trips(monkeypatch, capsys, tmp_path):
    """/cpInferno/export/json omits the default trigger (ControlParametersInferno.hs).

    Such an update entry goes through normalize and inferno-cp-import --dry-run unchanged.
    """
    exported = [
        {
            "cpId": "1001-00000000-0000-4000-8000-00000000c001",
            "inputs": [500012],
            "outputs": {"average": 500013},
            "script": "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF=",
            "name": "Example Casing PSI Daily Avg",
        }
    ]
    code, out, err, norm_err, doc = normalize_then_dry_run(monkeypatch, capsys, tmp_path, exported)
    assert doc == exported
    assert norm_err == ""
    assert code == 0, err
    assert "1001-00000000-0000-4000-8000-00000000c001" in out
    assert "trigger=<default: OnInputChangeAny>" in out


GOLDEN_DIR = os.environ.get("ONPING_FRONTEND_TYPES_GOLDEN")


@pytest.mark.skipif(not GOLDEN_DIR, reason="set ONPING_FRONTEND_TYPES_GOLDEN to the upstream golden dir")
def test_upstream_golden_readable_samples_pass_local_validation(monkeypatch, capsys, tmp_path):
    golden = json.loads(
        (Path(GOLDEN_DIR) / "ReadableControlParameterInferno" / "ReadableControlParameterInferno.json").read_text()
    )["samples"]
    doc = cij.normalize_list_document_status(copy.deepcopy(golden))[0]
    capsys.readouterr()
    assert len(doc) == len(golden)
    # inferno-cp-import's local checks must accept every normalised sample.
    assert all(set(cp) == {"cpId", "cpData"} for cp in doc)
    assert ici._parse_and_validate(json.dumps(doc)) == doc
