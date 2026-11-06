"""Offline tests for scripts/list_generic_swd.py against the in-memory fake.

    uv run --with pytest --with requests pytest onping/skills/onping-generic-swd-list/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "_generic_swd_routes" / "tests"))
import gswd_fakes as fx  # noqa: E402

LEGACY_TOKEN = "eyJhbGciOiJIUzI1NiJ9.sample.signature"

spec = importlib.util.spec_from_file_location("list_generic_swd", SKILLS / "onping-generic-swd-list" / "scripts" / "list_generic_swd.py")
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)


@pytest.fixture
def server(monkeypatch):
    return fx.install(monkeypatch)


def run(argv, capsys):
    code = ls.main([LEGACY_TOKEN, *argv, "--json"])
    out, err = capsys.readouterr()
    return code, json.loads(out), err


def test_lists_only_the_callers_groups(server, capsys):
    code, doc, _ = run([], capsys)
    assert code == 0
    assert {k["uuid"] for k in doc["kiosks"]} == {fx.K_OWN, fx.K_MEM}
    sent = [c["body"] for c in server.calls if c["path"] == "/generic-swd/kiosk/configs"]
    assert sent == [[fx.G_OWN, fx.G_MEM]]
    owned = {k["uuid"]: k["owned"] for k in doc["kiosks"]}
    assert owned == {fx.K_OWN: True, fx.K_MEM: False}


def test_owned_only(server, capsys):
    code, doc, _ = run(["--owned-only"], capsys)
    assert code == 0 and [k["uuid"] for k in doc["kiosks"]] == [fx.K_OWN]


def test_group_filter(server, capsys):
    code, doc, _ = run(["--group", fx.G_MEM], capsys)
    assert code == 0 and [k["uuid"] for k in doc["kiosks"]] == [fx.K_MEM]


def test_foreign_group_refused_before_any_kiosk_request(server, capsys):
    code, doc, _ = run(["--group", fx.G_FOREIGN], capsys)
    assert code == 3 and "neither own nor belong" in doc["error"]
    assert not server.generic_swd_paths()


def test_permission_read_failure_fails_closed(server, capsys):
    server.ownership_status = 500
    code, doc, _ = run([], capsys)
    assert code == 3 and "fails closed" in doc["error"]
    assert not server.generic_swd_paths()


def test_text_output(server, capsys):
    assert ls.main([LEGACY_TOKEN]) == 0
    out = capsys.readouterr().out
    assert "2 kiosk(s)" in out and fx.K_OWN in out


def test_usage_error_exits_2(server, capsys):
    with pytest.raises(SystemExit) as exc:
        ls.main([])
    assert exc.value.code == 2 and not server.calls
