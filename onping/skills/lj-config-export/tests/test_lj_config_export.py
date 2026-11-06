"""Offline tests for scripts/lj_config_export.py. Run:
    uv run --with pytest --with requests pytest onping/skills/lj-config-export/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL.parent / "_las_routes" / "tests"))
import las_fakes as fx  # noqa: E402

LEGACY_TOKEN = "eyJhbGciOiJIUzI1NiJ9.sample.signature"

spec = importlib.util.spec_from_file_location("lj_config_export",
                                              SKILL / "scripts" / "lj_config_export.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.fixture
def server(monkeypatch):
    return fx.install(monkeypatch)


def run(argv, capsys):
    code = mod.main([LEGACY_TOKEN, *argv])
    out, err = capsys.readouterr()
    return code, out, err


def config_calls(server):
    return [c for c in server.calls if "configs" in c[1]]


def test_yaml_to_file(server, capsys, tmp_path):
    out = tmp_path / "x.yaml"
    code, _, err = run([str(fx.SERIAL), "--package", "single-well-tflow", "-o", str(out)], capsys)
    assert code == 0, err
    assert out.read_text() == "multi-serial-wait-time: 1\nwait-time: 15\n"
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600


def test_json_to_stdout(server, capsys):
    code, out, _ = run([str(fx.SERIAL), "--package", "client-mosquitto-broker", "--json",
                        "-o", "-"], capsys)
    assert code == 0
    assert json.loads(out)["pkgConfName"] == "client-mosquitto-broker"
    assert fx.SECRET in out  # exports are unmasked, by decision


def test_existing_file_refused_before_any_request(server, capsys, tmp_path):
    out = tmp_path / "x.yaml"
    out.write_text("keep")
    code, _, err = run([str(fx.SERIAL), "--package", "single-well-tflow", "-o", str(out)], capsys)
    assert code == 2 and "--force" in err
    assert out.read_text() == "keep" and server.calls == []
    code, _, _ = run([str(fx.SERIAL), "--package", "single-well-tflow", "-o", str(out),
                      "--force"], capsys)
    assert code == 0 and "wait-time: 15" in out.read_text()


def test_not_owner(server, capsys, tmp_path):
    code, _, err = run([str(fx.OTHER), "--package", "single-well-tflow",
                        "-o", str(tmp_path / "x")], capsys)
    assert code == 3 and "Owner" in err
    assert config_calls(server) == []


def test_missing_package(server, capsys, tmp_path):
    code, _, err = run([str(fx.SERIAL), "--package", "zz-missing", "-o", str(tmp_path / "x")],
                       capsys)
    assert code == 1 and "No configs for package zz-missing" in err
    assert not (tmp_path / "x").exists()
    code, _, err = run([str(fx.SERIAL), "--package", "zz-missing", "--json",
                        "-o", str(tmp_path / "y")], capsys)
    assert code == 1 and "single-well-tflow" in err


def test_package_required(server):
    with pytest.raises(SystemExit) as e:
        mod.main([LEGACY_TOKEN, str(fx.SERIAL)])
    assert e.value.code == 2
