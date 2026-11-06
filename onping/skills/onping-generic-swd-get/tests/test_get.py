"""Offline tests for scripts/get_generic_swd.py against the in-memory fake.

    uv run --with pytest --with requests pytest onping/skills/onping-generic-swd-get/tests
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

spec = importlib.util.spec_from_file_location("get_generic_swd", SKILLS / "onping-generic-swd-get" / "scripts" / "get_generic_swd.py")
gs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gs)


@pytest.fixture
def server(monkeypatch):
    return fx.install(monkeypatch)


def run(argv, capsys):
    code = gs.main([LEGACY_TOKEN, *argv, "--json"])
    out, err = capsys.readouterr()
    return code, json.loads(out), err


def test_get_owned_kiosk(server, capsys):
    code, doc, _ = run([fx.K_OWN], capsys)
    assert code == 0
    assert doc["kiosk"]["owned"] is True
    assert doc["config"]["frontendConfigLanes"][0]["frontendLaneReadPID"]["laneParamPID"] == fx.READ_1
    assert doc["lanes_reported"]["1"]["read"]["laneParamStatus"] == "Available"
    assert doc["stored_config_problems"] == []
    assert not server.writes()


def test_member_kiosk_is_readable(server, capsys):
    code, doc, _ = run([fx.K_MEM], capsys)
    assert code == 0 and doc["kiosk"]["owned"] is False


@pytest.mark.parametrize("uuid", [fx.K_FOREIGN, fx.UNKNOWN])
def test_kiosk_outside_your_groups_is_refused_without_reading_it(server, capsys, uuid):
    code, doc, _ = run([uuid], capsys)
    assert code == 3
    assert "/generic-swd/kiosk/config" not in [c["path"] for c in server.calls]


def test_live_and_tickets(server, capsys):
    code, doc, _ = run([fx.K_OWN, "--live", "--tickets", "5"], capsys)
    assert code == 0
    assert doc["live"] == {"ok": True, "lanes": [{"lane": 1, "status": "Available"}]}
    assert doc["tickets"]["tickets"][0]["ticketId"] == "000000001"
    assert f"GET /generic-swd/kiosk/tickets/5/{fx.K_OWN}" in server.paths()


def test_live_failure_still_prints_config_and_exits_1(server, capsys):
    server.lanes_fail = True
    code, doc, _ = run([fx.K_OWN, "--live"], capsys)
    assert code == 1 and doc["live"]["ok"] is False and doc["config"]


def test_output_writes_a_restorable_backup(server, capsys, tmp_path):
    out = tmp_path / "k.json"
    code, doc, _ = run([fx.K_OWN, "--output", str(out)], capsys)
    assert code == 0
    saved = json.loads(out.read_text())
    assert saved["format"] == "onping-generic-swd-config/1" and saved["kiosk_uuid"] == fx.K_OWN
    assert saved["config"]["frontendConfigLanes"][0]["frontendLaneReadPID"]["laneParamRawValue"] is None


@pytest.mark.parametrize("argv", [["not-a-uuid"], [fx.K_OWN, "--tickets", "0"], [fx.K_OWN, "--tickets", "101"]])
def test_usage_errors(server, capsys, argv):
    with pytest.raises(SystemExit) as exc:
        gs.main([LEGACY_TOKEN, *argv])
    assert exc.value.code == 2 and not server.calls


def test_existing_output_file_is_a_usage_error(server, capsys, tmp_path):
    out = tmp_path / "exists.json"
    out.write_text("{}")
    with pytest.raises(SystemExit) as exc:
        gs.main([LEGACY_TOKEN, fx.K_OWN, "--output", str(out)])
    assert exc.value.code == 2 and not server.calls


def test_failed_mask_is_noted(server, capsys):
    server.configs[fx.K_OWN]["frontendConfigLanes"][0]["frontendLaneReadMaskScript"] = "output := FAIL;"
    assert gs.main([LEGACY_TOKEN, fx.K_OWN]) == 0
    assert "the mask script did not evaluate" in capsys.readouterr().out
