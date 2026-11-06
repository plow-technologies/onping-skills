"""Offline tests for scripts/lj_config_set.py. Run:
    uv run --with pytest --with requests --with pyyaml pytest onping/skills/lj-config-set/tests
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

spec = importlib.util.spec_from_file_location("lj_config_set",
                                              SKILL / "scripts" / "lj_config_set.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

S = str(fx.SERIAL)
TF = ["--package", "single-well-tflow"]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "TOKEN")
    return fx.install(monkeypatch)


def run(argv, capsys):
    code = mod.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def bk(tmp_path, name="b.json"):
    return ["--backup", str(tmp_path / name)]


def value(server, pkg, key, serial=fx.SERIAL):
    for e in server.pkg(serial, pkg)["pkgConfSchema"]:
        if e["configKey"] == key:
            return e["configValue"]


# ------------------------------------------------------------- preview/gates
def test_preview_only(server, capsys, tmp_path):
    code, out, _ = run([S, *TF, "wait-time=30", *bk(tmp_path)], capsys)
    assert code == 0
    assert "wait-time (CInteger): 15 -> 30" in out
    assert "restarts the service 'swtflow'" in out
    assert "PREVIEW ONLY" in out
    assert not server.posts() and not (tmp_path / "b.json").exists()


def test_dry_run_wins(server, capsys, tmp_path):
    code, out, _ = run([S, *TF, "wait-time=30", "--yes", "--dry-run", *bk(tmp_path)], capsys)
    assert code == 0 and "DRY RUN" in out and not server.posts()


def test_success_flow(server, capsys, tmp_path):
    server.ack_after_polls = 2
    code, out, err = run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 0, err
    (post,) = server.posts()
    body = post[3]
    assert post[2] == {"serial": fx.SERIAL}
    assert body["pkgConfMonitorName"] == "swtflow"
    assert [e["configKey"] for e in body["pkgConfSchema"]] == ["wait-time", "multi-serial-wait-time"]
    assert body["pkgConfSchema"][0]["configValue"] == 30
    assert body["pkgConfSchema"][1]["configValue"] == 1
    assert value(server, "single-well-tflow", "wait-time") == 30
    assert "Read-back: all 2 key(s) match" in out
    assert "Device acknowledged (is-storage-synced: true at poll 3, about 4s" in out
    assert "undo:" in out and "--restore" in out and "ACCESS_TOKEN" not in out
    b = tmp_path / "b.json"
    assert stat.S_IMODE(os.stat(b).st_mode) == 0o600
    doc = json.loads(b.read_text())
    assert doc["packageConfig"]["pkgConfSchema"][0]["configValue"] == 15
    assert len(doc["allConfigs"]) == 3


def test_restore_round_trip(server, capsys, tmp_path):
    run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    code, out, err = run([S, "--restore", str(tmp_path / "b.json"), "--yes",
                          *bk(tmp_path, "b2.json")], capsys)
    assert code == 0, err
    assert "wait-time (CInteger): 30 -> 15" in out
    assert value(server, "single-well-tflow", "wait-time") == 15


def test_restore_wrong_serial(server, capsys, tmp_path):
    run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    doc = json.loads((tmp_path / "b.json").read_text())
    doc["serial"] = fx.OTHER
    (tmp_path / "c.json").write_text(json.dumps(doc))
    n = len(server.posts())
    code, _, err = run([S, "--restore", str(tmp_path / "c.json"), "--yes"], capsys)
    assert code == 2 and "serial" in err and len(server.posts()) == n


def test_noop_skipped_unless_allowed(server, capsys, tmp_path):
    code, out, _ = run([S, *TF, "wait-time=15", "--yes", *bk(tmp_path)], capsys)
    assert code == 0 and "No value changes" in out and not server.posts()
    code, out, err = run([S, *TF, "wait-time=15", "--yes", "--allow-noop", *bk(tmp_path)], capsys)
    assert code == 0, err
    assert len(server.posts()) == 1 and "(unchanged)" in out


def test_not_owner(server, capsys, tmp_path):
    code, _, err = run([str(fx.OTHER), *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 3 and "Owner" in err and not server.posts()
    assert not any("configs" in c[1] for c in server.calls)


def test_unsynced_refused_then_allowed(server, capsys, tmp_path):
    server.synced[fx.SERIAL] = False
    code, out, err = run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 3 and "--allow-unsynced" in err and not server.posts()
    assert "storage synced: no" in out
    assert not (tmp_path / "b.json").exists()
    code, _, _ = run([S, *TF, "wait-time=30", "--yes", "--allow-unsynced", *bk(tmp_path)], capsys)
    assert code == 0 and len(server.posts()) == 1


def test_not_acknowledged_exits_4(server, capsys, tmp_path):
    server.ack_after_polls = None
    code, out, err = run([S, *TF, "wait-time=30", "--yes", "--wait", "4", *bk(tmp_path)], capsys)
    assert code == 4
    assert "saved in the cloud" in err and "undo:" in out
    polls = [c for c in server.calls if c[1].endswith("is-storage-synced")]
    assert len(polls) == 1 + 3  # preflight + attempts at 0, 2, 4 s


def test_concurrent_change_aborts(server, capsys, tmp_path):
    def bump(serial, n):
        if n == 2:
            server.pkg(serial, "single-well-tflow")["pkgConfSchema"][1]["configValue"] = 9
    server.on_get_configs = bump
    code, _, err = run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 1 and "changed since it was read" in err and not server.posts()


def test_read_back_mismatch(server, capsys, tmp_path):
    def clobber(serial, stored):
        stored["pkgConfSchema"][0]["configValue"] = 77
    server.on_post = clobber
    code, _, err = run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 1 and "MISMATCH" in err and "read back 77" in err


def test_post_failure(server, capsys, tmp_path):
    server.fail["POST /las/api/v1/lumberjack/configs"] = (
        500, fx.wrapped_500(404, "No configs for package single-well-tflow found for serial 9999"))
    code, _, err = run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 1 and "las-server answered 404" in err and "backup is" in err


# ------------------------------------------------------------- validation
def test_validation_reports_every_error(server, capsys, tmp_path):
    code, _, err = run([S, "--package", "zz-kitchen-sink", "ratio=abc", "enabled=yes",
                        "nope=1", "future=4", "hosts=a,b", "--yes", *bk(tmp_path)], capsys)
    assert code == 2 and not server.posts()
    for k in ("ratio", "enabled", "nope: no such key", "future", "hosts"):
        assert k in err


def test_port_range(server, capsys):
    code, _, err = run([S, "--package", "client-mosquitto-broker", "port=70000", "--yes"], capsys)
    assert code == 2 and "0-65535" in err and not server.posts()


def test_url_whitespace(server, capsys):
    code, _, err = run([S, "--package", "client-mosquitto-broker", "uri=mqtt://a b"], capsys)
    assert code == 2 and "whitespace" in err


def test_duplicate_key(server, capsys):
    code, _, err = run([S, *TF, "wait-time=1", "wait-time=2"], capsys)
    assert code == 2 and "more than once" in err


def test_raw_json_forms(server, capsys, tmp_path):
    code, out, err = run([S, "--package", "zz-kitchen-sink", 'maybe-port:=8080',
                          'hosts:=["a","b"]', "label:=null", *bk(tmp_path)], capsys)
    assert code == 2 and "label: expected text" in err  # CText is not CMaybe
    code, out, err = run([S, "--package", "zz-kitchen-sink", "maybe-port:=8080",
                          'hosts:=["a","b"]', "--yes", *bk(tmp_path)], capsys)
    assert code == 0, err
    assert value(server, "zz-kitchen-sink", "maybe-port") == 8080
    assert value(server, "zz-kitchen-sink", "hosts") == ["a", "b"]
    assert value(server, "zz-kitchen-sink", "future") == 3  # the unknown type is kept


def test_password_masked_in_preview(server, capsys):
    code, out, err = run([S, "--package", "client-mosquitto-broker", "password=newsecret"], capsys)
    assert code == 0
    assert '"********" -> "********" (changed)' in out
    assert "newsecret" not in out + err and fx.SECRET not in out + err
    assert "no monitor name" in out
    code, out, _ = run([S, "--package", "client-mosquitto-broker", "password=newsecret",
                        "--show-secrets"], capsys)
    assert "newsecret" in out


def test_from_yaml(server, capsys, tmp_path):
    y = tmp_path / "v.yaml"
    y.write_text("label: on\n")
    code, _, err = run([S, "--package", "zz-kitchen-sink", "--from-yaml", str(y)], capsys)
    assert code == 2 and "quote" in err
    y.write_text("label: 'on'\nratio: 3\nenabled: false\n")
    code, out, err = run([S, "--package", "zz-kitchen-sink", "--from-yaml", str(y), "--yes",
                          *bk(tmp_path)], capsys)
    assert code == 0, err
    assert value(server, "zz-kitchen-sink", "label") == "on"
    assert value(server, "zz-kitchen-sink", "enabled") is False


def test_from_yaml_export_round_trip(server, capsys, tmp_path):
    y = tmp_path / "v.yaml"
    y.write_text("multi-serial-wait-time: 1\nwait-time: 15\n")
    code, out, _ = run([S, *TF, "--from-yaml", str(y)], capsys)
    assert code == 0 and "No value changes" in out


def test_backup_path_must_be_new(server, capsys, tmp_path):
    (tmp_path / "b.json").write_text("{}")
    code, _, err = run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 2 and "exists" in err and server.calls == []


def test_usage(server):
    for argv in ([S, *TF], [S, "wait-time=1"],
                 [S, "--restore", "x", "wait-time=1"]):
        with pytest.raises(SystemExit) as e:
            mod.main(argv)
        assert e.value.code == 2


# ----------------------------------------------------- rate limit and token
def test_post_429_is_not_resent(server, capsys, tmp_path):
    server.fail["POST /las/api/v1/lumberjack/configs"] = (429, "Too Many Requests")
    code, _, err = run([S, *TF, "wait-time=30", "--yes", *bk(tmp_path)], capsys)
    assert code == 1 and "429" in err
    assert len(server.posts()) == 1


def test_token_never_printed(server, capsys, tmp_path, monkeypatch):
    secret = "tok-DISTINCT-0123456789"
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", secret)
    for argv in ([S, *TF, "wait-time=30"],
                 [S, *TF, "wait-time=30", "--yes", *bk(tmp_path)]):
        _, out, err = run(argv, capsys)
        assert secret not in out + err
    server.fail["POST /las/api/v1/lumberjack/configs"] = (500, fx.wrapped_500(404, "gone"))
    _, out, err = run([S, *TF, "wait-time=31", "--yes", *bk(tmp_path, "c.json")], capsys)
    assert secret not in out + err
