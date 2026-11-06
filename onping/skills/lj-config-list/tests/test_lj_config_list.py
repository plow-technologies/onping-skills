"""Offline tests for scripts/lj_config_list.py. Run:
    uv run --with pytest --with requests pytest onping/skills/lj-config-list/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL.parent / "_las_routes" / "tests"))
import las_fakes as fx  # noqa: E402

LEGACY_TOKEN = "eyJhbGciOiJIUzI1NiJ9.sample.signature"

spec = importlib.util.spec_from_file_location("lj_config_list",
                                              SKILL / "scripts" / "lj_config_list.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.fixture
def server(monkeypatch):
    return fx.install(monkeypatch)


def run(argv, capsys):
    code = mod.main([LEGACY_TOKEN, *argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_summary(server, capsys):
    code, out, _ = run([str(fx.SERIAL)], capsys)
    assert code == 0
    assert '"Synthetic Sim LJ"' in out and "owner: yes" in out
    assert "storage synced: yes" in out and "bridge up: unknown" in out
    assert "3 package(s)" in out
    assert "client-mosquitto-broker  monitor (no monitor)  keys 4" in out
    assert not server.posts()


def test_package_masks_passwords_text_and_json(server, capsys):
    code, out, _ = run([str(fx.SERIAL), "--package", "client-mosquitto-broker"], capsys)
    assert code == 0
    assert 'password (CPassword) = "********"' in out and fx.SECRET not in out
    assert "port (CPort) = 1883" in out
    code, out, _ = run([str(fx.SERIAL), "--package", "zz-kitchen-sink", "--json"], capsys)
    data = json.loads(out)
    tokens = [e for e in data["packages"][0]["pkgConfSchema"] if e["configKey"] == "tokens"][0]
    assert tokens["configValue"] == ["********", "********"]
    assert fx.SECRET not in out


def test_show_secrets(server, capsys):
    code, out, _ = run([str(fx.SERIAL), "--package", "client-mosquitto-broker",
                        "--show-secrets"], capsys)
    assert code == 0 and fx.SECRET in out


def test_unknown_package(server, capsys):
    code, _, err = run([str(fx.SERIAL), "--package", "zz-nope"], capsys)
    assert code == 1 and "single-well-tflow" in err


def test_member_only_lumberjack(server, capsys):
    code, out, _ = run([str(fx.OTHER)], capsys)
    assert code == 0 and "owner: no" in out and "need Owner" in out


def test_forbidden(server, capsys):
    code, _, err = run(["12345"], capsys)
    assert code == 1 and "403" in err


def test_lumberjacks_never_print_password(server, capsys):
    code, out, _ = run(["--lumberjacks", "--json"], capsys)
    assert code == 0
    rows = json.loads(out)
    assert len(rows) == 2 and all("lumberjackPassword" not in r for r in rows)
    assert "$2b$" not in out
    code, out, _ = run(["--lumberjacks", "--name", "another"], capsys)
    assert "1 Lumberjack(s)" in out and "Another Synthetic LJ" in out and "$2b$" not in out


def test_usage(server):
    with pytest.raises(SystemExit) as e:
        mod.main([LEGACY_TOKEN])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        mod.main([LEGACY_TOKEN, "1", "--lumberjacks"])
