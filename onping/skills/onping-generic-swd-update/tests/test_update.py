"""Offline tests for scripts/update_generic_swd.py against the in-memory fake.

Every write is mocked: the fake stores what the lane update sends. Run:
    uv run --with pytest --with requests pytest onping/skills/onping-generic-swd-update/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "_generic_swd_routes" / "tests"))
import gswd_fakes as fx  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "update_generic_swd", SKILLS / "onping-generic-swd-update" / "scripts" / "update_generic_swd.py")
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)

OFFLOAD_START = "/generic-swd/kiosk/ticket/"
KIOSK_ROUTES_ALLOWED = {
    "/generic-swd/kiosk/configs", "/generic-swd/kiosk/config", "/generic-swd/config/lane/update",
}


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "TOKEN")
    return fx.install(monkeypatch)


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def never_offload(server):
    yield
    paths = [c["path"] for c in server.calls]
    assert not any(OFFLOAD_START in p for p in paths), "an offload-start request was sent"
    for p in paths:
        if p.startswith("/generic-swd/"):
            assert p in KIOSK_ROUTES_ALLOWED or p.startswith(("/generic-swd/kiosk/lanes/", "/generic-swd/kiosk/tickets/")), p


def run(argv, capsys, uuid=fx.K_OWN):
    code = up.main([uuid, *argv, "--json"])
    out, err = capsys.readouterr()
    return code, json.loads(out), err


def stored(server, uuid=fx.K_OWN) -> dict:
    return server.configs[uuid]


# ─────────────────────────────── usage ───────────────────────────────


@pytest.mark.parametrize("argv", [
    [],
    ["lane-set", "--lane", "1"],  # nothing to change
    ["lane-set", "--lane", "x", "--read-pid", "1"],
    ["lane-set", "--lane", "1", "--read-pid", "0"],
    ["lane-set", "--lane", "1", "--wait-val", "nan"],
    ["lane-set", "--lane", "1", "--script", "a", "--clear-script"],
    ["lane-add", "--lane", "2", "--read-pid", "1"],
    ["status-set", "--value", "4"],
    ["status-set", "--value", "4", "--status", "Available", "--disabled", "x"],
    ["status-set", "--value", "4", "--status", "Disabled"],
    ["replace", "--from", "/nonexistent/file.json"],
    ["offload-start", "--lane", "1"],
])
def test_usage_errors_exit_2_before_any_request(server, argv):
    with pytest.raises(SystemExit) as exc:
        up.main([fx.K_OWN, *argv])
    assert exc.value.code == 2
    assert not server.calls


def test_bad_uuid_is_usage(server):
    with pytest.raises(SystemExit) as exc:
        up.main(["nope", "name-set", "--name", "x"])
    assert exc.value.code == 2 and not server.calls


def test_existing_backup_path_is_usage(server, in_tmp):
    (in_tmp / "b.json").write_text("{}")
    with pytest.raises(SystemExit) as exc:
        up.main([fx.K_OWN, "name-set", "--name", "x", "--backup", "b.json", "--yes"])
    assert exc.value.code == 2 and not server.calls


# ─────────────────────────────── guard ───────────────────────────────


def test_member_kiosk_refused(server, capsys):
    code, doc, _ = run(["name-set", "--name", "New", "--yes"], capsys, uuid=fx.K_MEM)
    assert code == 3 and "do not own group" in doc["error"]
    assert not server.writes()
    assert "/generic-swd/kiosk/config" not in [c["path"] for c in server.calls]


@pytest.mark.parametrize("uuid", [fx.K_FOREIGN, fx.UNKNOWN])
def test_foreign_or_unknown_kiosk_refused(server, capsys, uuid):
    code, doc, _ = run(["name-set", "--name", "New", "--yes"], capsys, uuid=uuid)
    assert code == 3 and "not in any group" in doc["error"]
    assert not server.writes()


def test_kiosk_list_only_sends_callers_groups(server, capsys):
    run(["name-set", "--name", "New"], capsys)
    sent = [c["body"] for c in server.calls if c["path"] == "/generic-swd/kiosk/configs"]
    assert sent and all(set(b) <= {fx.G_OWN, fx.G_MEM} for b in sent)


def test_permission_failure_fails_closed(server, capsys):
    server.ownership_status = 500
    code, doc, _ = run(["name-set", "--name", "New", "--yes"], capsys)
    assert code == 3 and not server.writes()


@pytest.mark.parametrize("argv,needle", [
    (["lane-set", "--lane", "1", "--write-pid", str(fx.RO_PID)], "not writeable"),
    (["lane-set", "--lane", "1", "--read-pid", "999999"], "not returned by the parameter lister"),
    (["lane-set", "--lane", "1", "--write-pid", str(fx.MEM_PID)], "do not own group"),
    (["lane-set", "--lane", "1", "--read-pid", str(fx.SPLIT_PID)], "is in 2 groups"),
])
def test_pid_guard_refuses(server, capsys, argv, needle):
    code, doc, _ = run([*argv, "--yes"], capsys)
    assert code == 3, doc
    assert any(needle in p for p in doc["guard_problems"]), doc["guard_problems"]
    assert not server.writes()


def test_unchanged_bad_pid_is_only_a_warning(server, capsys):
    server.pids[fx.WRITE_1] = (fx.LOC_OWN, "TagReadOnly", 0.0)
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes"], capsys)
    assert code == 0, doc
    assert any("not writeable" in w and "unchanged" in w for w in doc["warnings"])


def test_lister_failure_fails_closed(server, capsys):
    server.lister_status = 500
    code, doc, _ = run(["lane-set", "--lane", "1", "--read-pid", str(fx.READ_2), "--yes"], capsys)
    assert code == 3 and not server.writes()


def test_location_scan_only_when_a_pid_changes(server, capsys):
    run(["name-set", "--name", "Renamed"], capsys)
    assert not [p for p in server.paths() if "/location/lister/group/" in p]
    run(["lane-set", "--lane", "1", "--read-pid", str(fx.READ_2)], capsys)
    scanned = sorted(p for p in server.paths() if "/location/lister/group/" in p)
    assert scanned == sorted({f"GET /location/lister/group/{g}" for g in (fx.G_OWN, fx.G_MEM)})


# ─────────────────────────────── validation ───────────────────────────────


@pytest.mark.parametrize("argv", [
    ["name-set", "--name", "   "],
    ["lane-set", "--lane", "1", "--script", "x := input1;"],
    ["lane-delete", "--lane", "1"],  # the last lane
    ["status-delete", "--value", "2"],  # removes Pumping
    ["status-set", "--value", "4", "--disabled", "   "],
])
def test_validation_refuses(server, capsys, argv):
    code, doc, _ = run([*argv, "--yes"], capsys)
    assert code == 3 and doc["validation"]["errors"]
    assert not server.writes()


@pytest.mark.parametrize("argv", [
    ["lane-set", "--lane", "9", "--read-pid", str(fx.READ_2)],
    ["lane-add", "--lane", "1", "--read-pid", "1", "--write-pid", "2", "--wait-val", "1"],
    ["status-delete", "--value", "42"],
])
def test_impossible_edit_refused(server, capsys, argv):
    code, doc, _ = run([*argv, "--yes"], capsys)
    assert code == 3 and not server.writes()


# ─────────────────────────────── preview ───────────────────────────────


def test_preview_sends_nothing_and_prints_the_diff(server, capsys, in_tmp):
    assert up.main([fx.K_OWN, "status-set", "--value", "4", "--disabled", "Bay closed"]) == 0
    out = capsys.readouterr().out
    assert "+ status 4: Disabled('Bay closed')" in out
    assert "PREVIEW ONLY — nothing was posted. Re-run with --yes to apply." in out
    assert "replace --from" in out
    assert not server.writes() and not list(in_tmp.glob("*.backup.json"))


def test_dry_run_wins_over_yes(server, capsys, in_tmp):
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes", "--dry-run"], capsys)
    assert code == 0 and doc["outcome"] == "dry-run"
    assert not server.writes() and not list(in_tmp.glob("*.backup.json"))


def test_no_change_sends_nothing(server, capsys):
    code, doc, _ = run(["status-set", "--value", "0", "--status", "Available", "--yes"], capsys)
    assert code == 0 and doc["outcome"] == "no-change" and not server.writes()


def test_script_change_warns_grammar_not_checked(server, capsys):
    code, doc, _ = run(["lane-set", "--lane", "1", "--script", "output := input1;"], capsys)
    assert code == 0 and any("shape only" in w for w in doc["warnings"])


def test_new_lane_without_a_script_has_no_script_warning(server, capsys):
    code, doc, _ = run(["lane-add", "--lane", "2", "--read-pid", str(fx.READ_2), "--write-pid", str(fx.WRITE_2),
                        "--wait-val", "1"], capsys)
    assert code == 0 and not any("shape only" in w for w in doc["warnings"])


# ─────────────────────────────── the write ───────────────────────────────


def test_write_backup_body_and_readback(server, capsys, in_tmp):
    before = json.loads(json.dumps(stored(server)))
    code, doc, _ = run(["lane-add", "--lane", "2", "--read-pid", str(fx.READ_2), "--write-pid", str(fx.WRITE_2),
                        "--wait-val", "1", "--backup", "b.json", "--yes"], capsys)
    assert code == 0, doc
    assert doc["outcome"] == "written" and doc["live_before"] is True and doc["live_after"] is True
    [w] = server.writes()
    uuid_part, cfg = w["body"]
    assert uuid_part == {"unKioskUUID": fx.K_OWN}
    assert [ln["frontendLaneNumber"] for ln in cfg["frontendConfigLanes"]] == [1, 2]
    assert cfg["frontendConfigLanes"][1]["frontendLaneReadPID"] == {
        "laneParamPID": fx.READ_2, "laneParamName": None, "laneParamRawValue": None,
        "laneParamMaskedValue": None, "laneParamStatus": None}
    backup = json.loads((in_tmp / "b.json").read_text())
    assert backup["kiosk_uuid"] == fx.K_OWN
    assert backup["config"]["frontendConfigLanes"] == [
        {**ln, "frontendLaneWriteWaitingToStartVal": float(ln["frontendLaneWriteWaitingToStartVal"])}
        for ln in before["frontendConfigLanes"]]
    assert doc["restore"].endswith(f"{fx.K_OWN} replace --from b.json --yes")
    # order: backup is written before the drift re-read; the write is sent exactly once
    paths = server.paths()
    assert paths.count("POST /generic-swd/config/lane/update") == 1
    i_write = paths.index("POST /generic-swd/config/lane/update")
    assert paths[:i_write].count("POST /generic-swd/kiosk/config") == 2  # read + drift re-read
    assert paths[i_write + 1] == "POST /generic-swd/kiosk/config"  # read-back


def test_default_backup_path(server, capsys, in_tmp):
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes"], capsys)
    assert code == 0
    [b] = list(in_tmp.glob(f"generic-swd-{fx.K_OWN[:8]}-*.backup.json"))
    assert doc["backup"].endswith(b.name)


def test_restore_round_trip(server, capsys, in_tmp):
    original = up.model.canonical(up.model.from_wire(stored(server)))
    assert run(["name-set", "--name", "Renamed", "--backup", "b.json", "--yes"], capsys)[0] == 0
    assert stored(server)["frontendConfigName"] == "Renamed"
    code, doc, _ = run(["replace", "--from", "b.json", "--backup", "b2.json", "--yes"], capsys)
    assert code == 0, doc
    assert up.model.canonical(up.model.from_wire(stored(server))) == original


def test_replace_refuses_another_kiosks_backup(server, capsys, in_tmp):
    doc = up.model.backup_doc({"uuid": fx.K_MEM, "group_id": fx.G_MEM},
                              up.model.from_wire(fx.base_config()), "2026-10-28T00:00:00Z")
    (in_tmp / "other.json").write_text(json.dumps(doc))
    code, out, _ = run(["replace", "--from", "other.json", "--yes"], capsys)
    assert code == 3 and "is for kiosk" in out["error"] and not server.writes()


def test_drift_refuses(server, capsys, in_tmp):
    def drift(s):
        s.configs[fx.K_OWN]["frontendConfigName"] = "Changed by someone else"
    server.on_config_read = [lambda s: None, drift]
    code, doc, _ = run(["status-set", "--value", "4", "--disabled", "Bay closed", "--backup", "b.json", "--yes"], capsys)
    assert code == 3 and "changed since it was read" in doc["error"]
    assert not server.writes()
    assert (in_tmp / "b.json").exists()  # the backup was written first


def test_unwritable_backup_refuses(server, capsys):
    code, doc, _ = run(["name-set", "--name", "R", "--backup", "/nonexistent-dir/b.json", "--yes"], capsys)
    assert code == 3 and "could not write the backup" in doc["error"] and not server.writes()


def test_rejected_write_exits_1(server, capsys):
    server.update_overrides = [(500, {"error": "boom"})]
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes"], capsys)
    assert code == 1 and doc["outcome"] == "rejected" and "boom" in doc["error"]
    assert len(server.writes()) == 1


def test_lost_response_with_landed_write_is_unknown(server, capsys):
    def lost_after_store(s, cfg):
        raise requests.ConnectionError("reset")
    server.after_update = lost_after_store
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes"], capsys)
    assert code == 4 and "restore with" in doc["error"]
    assert len(server.writes()) == 1  # never retried


def test_readback_mismatch_is_4(server, capsys):
    def clobber(s, cfg):
        cfg["frontendConfigName"] = "Something else"
    server.after_update = clobber
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes"], capsys)
    assert code == 4 and any("does not match" in p for p in doc["problems"])


def test_readback_failure_is_4(server, capsys):
    server.on_config_read = [lambda s: None, lambda s: None, lambda s: s.configs.pop(fx.K_OWN)]
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes"], capsys)
    assert code == 4 and "read-back failed" in doc["error"] and len(server.writes()) == 1


def test_mask_that_does_not_evaluate_is_4(server, capsys):
    code, doc, _ = run(["lane-set", "--lane", "1", "--script", "output := FAIL;", "--yes"], capsys)
    assert code == 4
    assert any("mask script did not evaluate" in p for p in doc["problems"])
    assert any("live lane read now fails" in p for p in doc["problems"])


def test_status_gap_caught_by_live_check(server, capsys):
    server.pids[fx.READ_2] = (fx.LOC_OWN, "TagWriteable", 7.0)  # no status-map entry for 7
    code, doc, _ = run(["lane-set", "--lane", "1", "--read-pid", str(fx.READ_2), "--yes"], capsys)
    assert code == 4 and any("live lane read now fails" in p for p in doc["problems"])


def test_live_check_skipped_when_already_failing(server, capsys):
    server.lanes_fail = True
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes"], capsys)
    assert code == 0 and doc["live_before"] is False and "live_after" not in doc


def test_no_live_check(server, capsys):
    code, doc, _ = run(["name-set", "--name", "Renamed", "--yes", "--no-live-check"], capsys)
    assert code == 0 and not [p for p in server.paths() if "/kiosk/lanes/" in p]


def test_text_report_on_success(server, capsys):
    assert up.main([fx.K_OWN, "name-set", "--name", "Renamed", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "written and confirmed" in out and "restore:" in out


def test_no_offload_route_in_the_route_table():
    assert not any("ticket/" in r for r in up.routes.ROUTES.values())
    assert up.routes.WRITE_ROUTE == "POST /generic-swd/config/lane/update"
    src = (SKILLS / "_generic_swd_routes" / "routes.py").read_text()
    assert "kiosk/ticket/" not in src.split('"""', 2)[2]
