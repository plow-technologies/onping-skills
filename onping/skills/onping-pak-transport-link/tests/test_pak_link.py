"""Offline tests for scripts/pak_link.py.

Every request goes to pak_fakes.FakeOnPing through a patched `requests.request`.
Run:
    uv run --with pytest --with requests pytest onping/skills/onping-pak-transport-link/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pak_fakes as fx  # noqa: E402

SCRIPT = SKILL / "scripts" / "pak_link.py"
spec = importlib.util.spec_from_file_location("pak_link", SCRIPT)
pl = importlib.util.module_from_spec(spec)
sys.modules["pak_link"] = pl
spec.loader.exec_module(pl)
pr = pl.pr

A, B, C, F = fx.LJ_A, fx.LJ_B, fx.LJ_C, fx.LJ_FOREIGN


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "TOKEN")
    return fx.install(monkeypatch)


@pytest.fixture
def bdir(tmp_path):
    return str(tmp_path / "backups")


def run(argv, capsys):
    code = pl.main([*argv])
    out, err = capsys.readouterr()
    return code, out, err


def run_json(argv, capsys):
    code, out, err = run([*argv, "--json"], capsys)
    return code, (json.loads(out) if out.strip() else None), err


def backups(bdir):
    return sorted(Path(bdir).glob("*.json")) if Path(bdir).exists() else []


# ─────────────────────────────── usage errors ───────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["list"],
        ["list", "--serial", "abc"],
        ["list", "--serial", "0"],
        ["get"],
        ["get", "--id", "not-a-uuid"],
        ["set", "--id", fx.CFG_A, "--map", "38"],
        ["set", "--id", fx.CFG_A, "--map", "38=1=2"],
        ["set", "--id", fx.CFG_A, "--map", "-1=2"],
        ["set", "--id", fx.CFG_A, "--map", "38=x"],
        ["set", "--id", fx.CFG_A, "--map", f"{2**64}=1"],
        ["set", "--id", fx.CFG_A, "--port", "eighty"],
        ["delete"],
        ["frobnicate"],
    ],
)
def test_usage_errors_send_nothing(server, capsys, argv):
    code, _, _ = run(argv, capsys)
    assert code == 2
    assert server.calls == []


def test_create_needs_fields(server, capsys, bdir):
    code, _, err = run(["set", "--serial", str(B), "--map", "1=1", "--backup-dir", bdir], capsys)
    assert code == 2 and "--facility-id" in err
    assert server.writes() == []


def test_new_id_needs_from(server, capsys):
    code, _, _ = run(["set", "--id", fx.CFG_A, "--new-id"], capsys)
    assert code == 2 and server.writes() == []


def test_word64_max_accepted(server, capsys):
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--map", f"{2**64 - 1}=1"], capsys)
    assert code == 0 and doc["status"] == "preview"


# ─────────────────────────────── reads ───────────────────────────────


def test_list_owned_and_missing(server, capsys):
    code, doc, _ = run_json(["list", "--serial", str(A), str(B), str(F)], capsys)
    assert code == 0
    assert [c["pakTransportConfigId"] for c in doc["configs"]] == [fx.CFG_A]
    reasons = {m["serial"]: m["reason"] for m in doc["missing"]}
    assert reasons[B] == "no link"
    assert reasons[F].startswith("not owned")


def test_list_all_owned_never_shows_foreign(server, capsys):
    code, doc, _ = run_json(["list", "--all-owned"], capsys)
    assert code == 0
    assert {c["pakTransportLumberjackId"] for c in doc["configs"]} == {A}
    list_call = [c for c in server.calls if (c["method"], c["path"]) == fx.LIST][0]
    assert F not in list_call["body"]


def test_get_by_id(server, capsys):
    code, doc, _ = run_json(["get", "--id", fx.CFG_A], capsys)
    assert code == 0 and doc["config"]["pakTransportLumberjackId"] == A


def test_get_foreign_refused(server, capsys):
    code, _, err = run(["get", "--id", fx.CFG_FOREIGN], capsys)
    assert code == 3 and "on an LJ you own" in err


def test_export_writes_array_and_refuses_overwrite(server, capsys, tmp_path):
    out = tmp_path / "links.json"
    code, _, _ = run(["export", "--serial", str(A), "-o", str(out)], capsys)
    assert code == 0
    data = json.loads(out.read_text())
    assert isinstance(data, list) and data[0]["pakTransportConfigId"] == fx.CFG_A
    code, _, _ = run(["export", "--serial", str(A), "-o", str(out)], capsys)
    assert code == 2


def test_old_shape_refused(server, capsys):
    old = {"pakTransportConfigId": fx.CFG_A, "pakTransportLumberjackId": A, "pakTransportExchangeName": "x"}
    server.list_override = (200, [old])
    code, _, err = run(["list", "--serial", str(A)], capsys)
    assert code == 3 and "OLD link record" in err
    code, _, _ = run(["set", "--id", fx.CFG_A, "--facility-name", "zz-x", "--yes"], capsys)
    assert code == 3 and server.writes() == []


def test_expired_token_redirect(server, capsys):
    server.redirect_all = True
    code, _, err = run(["list", "--serial", str(A)], capsys)
    assert code == 1 and "expired" in err


def test_list_http_error(server, capsys):
    server.list_override = (500, "boom")
    code, _, _ = run(["list", "--serial", str(A)], capsys)
    assert code == 1


# ─────────────────────────────── address check ───────────────────────────────


@pytest.mark.parametrize(
    "host,port",
    [
        ("10.0.0.5", 13180),
        ("0.0.0.0", 1),
        ("255.255.255.255", 65535),
        ("lj-b.example.net", 80),
        ("localhost", 13180),
        ("a" * 63 + ".example", 1),
        ("host1.9a", 1),
    ],
)
def test_address_ok(host, port):
    assert pr.address_error(host, port) is None


@pytest.mark.parametrize(
    "host,port",
    [
        ("10.0.0.5", 0),
        ("10.0.0.5", 65536),
        ("10.0.0.5", True),
        ("", 13180),
        ("10.0.0", 1),
        ("10.0.0.256", 1),
        ("10.0.0.05", 1),
        ("10.0.0.0005", 1),
        ("1.2.3.4.5", 1),
        ("-bad.example", 1),
        ("bad-.example", 1),
        ("a..b", 1),
        ("a" * 64 + ".example", 1),
        ("x." * 127 + "ab", 1),
        ("under_score.example", 1),
        ("http://10.0.0.5", 1),
        ("host.123", 1),
        ("hést.example", 1),
    ],
)
def test_address_rejected(host, port):
    assert pr.address_error(host, port) is not None


# ─────────────────────────────── preflight ───────────────────────────────


@pytest.mark.parametrize(
    "argv,needle",
    [
        (["set", "--id", fx.CFG_A, "--map", "1=1", "--map", "1=2"], "must not repeat a bay ID"),
        (["set", "--id", fx.CFG_A, "--url", "10.0.0.256"], "invalid lumberjack address"),
        (["set", "--id", fx.CFG_A, "--port", "0"], "invalid lumberjack address"),
        (["set", "--serial", str(A), "--facility-id", "F", "--facility-name", "zz-skill-test-n", "--map", "9=1"],
         "another configuration already exists for this lumberjack"),
        (["set", "--serial", str(B), "--facility-id", "F", "--facility-name", "zz-skill-test-n", "--map", "38=1"],
         "bay ID(s) already mapped by another configuration"),
        (["set", "--serial", str(F), "--facility-id", "F", "--facility-name", "zz-skill-test-n", "--map", "1=1", "--url", "h.example"],
         "you do not own LJ"),
        (["set", "--serial", str(B), "--facility-id", "F", "--facility-name", "zz-skill-test-n"], "must not be empty"),
    ],
)
def test_preflight_refuses_without_writing(server, capsys, bdir, argv, needle):
    code, _, err = run([*argv, "--yes", "--backup-dir", bdir], capsys)
    assert code == 3
    assert needle in err
    assert server.writes() == []
    assert backups(bdir) == []


def test_create_without_profile_url_needs_url(server, capsys, bdir):
    code, _, err = run(["set", "--serial", str(C), "--facility-id", "F", "--facility-name", "n", "--map", "1=1", "--yes"], capsys)
    assert code == 3 and "--url" in err and server.writes() == []


def test_shared_lane_is_fine(server, capsys):
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--map", "38=1", "--map", "39=1"], capsys)
    assert code == 0 and doc["status"] == "preview"


# ─────────────────────────────── ownership guard ───────────────────────────────


def test_edit_of_foreign_id_refused(server, capsys, bdir):
    # The record belongs to an LJ the caller does not own. The skill's guard
    # refuses before any write.
    argv = ["set", "--id", fx.CFG_FOREIGN, "--serial", str(B), "--allow-move", "--map", "77=1", "--yes", "--backup-dir", bdir]
    code, _, err = run(argv, capsys)
    assert code == 3 and "on an LJ you own" in err
    assert server.writes() == []
    assert server.store[fx.CFG_FOREIGN]["pakTransportLumberjackId"] == F


def test_from_file_with_foreign_id_refused(server, capsys, tmp_path, bdir):
    f = tmp_path / "rec.json"
    f.write_text(json.dumps(fx.record(fx.CFG_FOREIGN, B, [(77, 1)])))
    code, _, err = run(["set", "--from", str(f), "--yes", "--backup-dir", bdir], capsys)
    assert code == 3 and "--new-id" in err
    assert server.writes() == []


@pytest.mark.parametrize("bay", [[38], {"id": 38}, "38", 1.5, True])
def test_from_file_with_bad_mapping_value_refused(server, capsys, tmp_path, bdir, bay):
    # Any JSON value can sit in a --from file; a list or dict must not crash
    # the bay checks, and nothing may be sent.
    rec = json.loads(json.dumps(server.store[fx.CFG_A]))
    rec["pakTransportBayLaneMappings"] = [{"bayLaneBayId": bay, "bayLaneLaneNumber": 1}]
    f = tmp_path / "rec.json"
    f.write_text(json.dumps(rec))
    code, _, err = run(["set", "--from", str(f), "--yes", "--backup-dir", bdir], capsys)
    assert code == 3
    assert "bayLaneBayId" in err and "not a whole number" in err
    assert "Traceback" not in err
    assert server.writes() == [] and backups(bdir) == []


def test_from_file_with_new_id_creates(server, capsys, tmp_path, bdir):
    f = tmp_path / "rec.json"
    f.write_text(json.dumps(fx.record(fx.CFG_FOREIGN, B, [(77, 1)], url="lj-b.example.net")))
    code, doc, _ = run_json(["set", "--from", str(f), "--new-id", "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["action"] == "create"
    assert doc["configId"] != fx.CFG_FOREIGN
    assert server.store[fx.CFG_FOREIGN]["pakTransportLumberjackId"] == F


def test_move_needs_allow_move(server, capsys, bdir):
    code, _, err = run(["set", "--id", fx.CFG_A, "--serial", str(B), "--yes", "--backup-dir", bdir], capsys)
    assert code == 2 and "--allow-move" in err and server.writes() == []


def test_move_with_allow_move(server, capsys, bdir):
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--serial", str(B), "--allow-move", "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["readBack"]["pakTransportLumberjackId"] == B
    list_bodies = [c["body"] for c in server.calls if (c["method"], c["path"]) == fx.LIST]
    assert list_bodies[-1] == sorted([A, B])


def test_move_undo_moves_back(server, capsys, bdir):
    # Undoing a move is a move back, so the printed undo must carry --allow-move.
    original = json.loads(json.dumps(server.store[fx.CFG_A]))
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--serial", str(B), "--allow-move", "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "saved"
    (bk,) = backups(bdir)
    assert doc["undo"].endswith(f"set --from {bk} --allow-move --yes")
    undo_argv = doc["undo"].split(" set ", 1)[1].split()
    code, doc, _ = run_json(["set", *undo_argv, "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "saved"
    assert server.store[fx.CFG_A] == original


# ─────────────────────────────── writes ───────────────────────────────


def test_preview_by_default(server, capsys, bdir):
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz-skill-test-x", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "preview"
    assert doc["changes"] == [{"field": "pakTransportFacilityName", "old": "Example Facility", "new": "zz-skill-test-x"}]
    assert server.writes() == [] and backups(bdir) == []


def test_dry_run_wins(server, capsys, bdir):
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz", "--yes", "--dry-run", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "preview" and server.writes() == []


def test_no_op(server, capsys, bdir):
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--map", "38=1", "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "no-op" and server.writes() == [] and backups(bdir) == []


def test_edit_backup_readback_and_restore(server, capsys, bdir):
    original = json.loads(json.dumps(server.store[fx.CFG_A]))
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz-skill-test-x", "--map", "39=2", "--map", "38=1",
                             "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "saved"
    sent = server.writes()[0]["body"]
    assert [m["bayLaneBayId"] for m in sent["pakTransportBayLaneMappings"]] == [38, 39]
    (bk,) = backups(bdir)
    saved = json.loads(bk.read_text())
    assert saved["kind"] == pl.BACKUP_KIND and saved["before"] == original and saved["action"] == "update"
    assert doc["undo"].endswith(f"set --from {bk} --yes")
    # The backup was on disk before the write was sent.
    order = [f"{c['method']} {c['path']}" for c in server.calls]
    assert order.index("POST /pak-transport-ticket-permissive/config/repsert") > 0
    code, doc, _ = run_json(["set", "--from", str(bk), "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "saved"
    assert server.store[fx.CFG_A] == original


def test_create_then_delete(server, capsys, bdir):
    code, doc, _ = run_json(["set", "--serial", str(B), "--facility-id", "F", "--facility-name", "zz-skill-test-new",
                             "--map", "5=1", "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["action"] == "create"
    new_id = doc["configId"]
    assert pr.is_uuid(new_id) and new_id in server.store
    assert server.store[new_id]["pakTransportLumberjackUrl"] == "lj-b.example.net"  # LAS profile default
    assert server.store[new_id]["pakTransportLumberjackPort"] == 13180
    assert "delete --id" in doc["undo"]
    create_backup = backups(bdir)[0]
    code, _, err = run(["set", "--from", str(create_backup), "--yes"], capsys)
    assert code == 2 and "delete --id" in err
    code, doc, _ = run_json(["delete", "--id", new_id, "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "deleted" and new_id not in server.store
    assert "--new-id" in doc["undo"]


def test_delete_preview_and_foreign(server, capsys, bdir):
    code, doc, _ = run_json(["delete", "--id", fx.CFG_A, "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "preview" and server.writes() == []
    code, _, _ = run(["delete", "--id", fx.CFG_FOREIGN, "--yes", "--backup-dir", bdir], capsys)
    assert code == 3 and server.writes() == []


def test_delete_restore_with_new_id(server, capsys, bdir):
    code, _, _ = run(["delete", "--id", fx.CFG_A, "--yes", "--backup-dir", bdir], capsys)
    assert code == 0
    (bk,) = backups(bdir)
    code, _, err = run(["set", "--from", str(bk), "--yes", "--backup-dir", bdir], capsys)
    assert code == 3 and "--new-id" in err
    code, doc, _ = run_json(["set", "--from", str(bk), "--new-id", "--yes", "--backup-dir", bdir], capsys)
    assert code == 0
    restored = server.store[doc["configId"]]
    assert {k: v for k, v in restored.items() if k != "pakTransportConfigId"} == {
        k: v for k, v in json.loads(bk.read_text())["before"].items() if k != "pakTransportConfigId"
    }


def test_switcher_502_nothing_saved(server, capsys, bdir):
    server.switcher_fails = True
    code, doc, err = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz-skill-test-x", "--yes", "--backup-dir", bdir], capsys)
    assert code == 1 and doc["status"] == "not-saved" and "nothing was saved" in err
    assert server.store[fx.CFG_A]["pakTransportFacilityName"] == "Example Facility"


def test_cloud_400_is_unwrapped(server, capsys, bdir, monkeypatch):
    # Skip the local preflight so the fake cloud's own check answers.
    monkeypatch.setattr(pr, "preflight", lambda *a: [])
    code, doc, err = run_json(["set", "--id", fx.CFG_A, "--map", "1=1", "--map", "1=2", "--yes", "--backup-dir", bdir], capsys)
    assert code == 1 and doc["status"] == "not-saved"
    assert doc["http"]["status"] == 500 and doc["http"]["cloudStatus"] == 400
    assert doc["http"]["cloudMessage"] == "pakTransportBayLaneMappings must not repeat a bay ID"
    assert "the cloud app answered 400: pakTransportBayLaneMappings must not repeat a bay ID" in err


def test_cloud_error_parser_handles_quotes():
    resp = fx.FakeResponse(500, fx.wrapped(400, 'invalid lumberjack address: not "x"'), "u")
    assert pr.cloud_error(resp) == (400, 'invalid lumberjack address: not "x"')
    assert pr.cloud_error(fx.FakeResponse(500, {"error": "other"}, "u")) == (None, None)
    assert pr.cloud_error(fx.FakeResponse(500, "plain", "u")) == (None, None)


def test_literal_502_hint(server, capsys, bdir):
    server.write_override = (502, "could not register the lumberjack in the switcher")
    code, out, err = run(["set", "--id", fx.CFG_A, "--facility-name", "zz", "--yes", "--backup-dir", bdir], capsys)
    assert code == 1 and "nothing was saved" in err
    assert "a 502 means a cloud call failed" in out  # the 502 hint; prose goes to stdout without --json


def test_server_403_is_refusal(server, capsys, bdir):
    server.write_override = (403, "Insufficient permissions for this lumberjack")
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz", "--yes", "--backup-dir", bdir], capsys)
    assert code == 3 and doc["status"] == "not-saved"


def test_transport_error_on_write_then_unchanged(server, capsys, bdir):
    server.write_override = requests.ConnectionError("reset")
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz", "--yes", "--backup-dir", bdir], capsys)
    assert code == 1 and doc["status"] == "not-saved"


def test_readback_mismatch(server, capsys, bdir):
    def tamper(fake):
        fake.store[fx.CFG_A]["pakTransportFacilityName"] = "someone else"
    server.after_write = tamper
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz", "--yes", "--backup-dir", bdir], capsys)
    assert code == 4 and doc["status"] == "mismatch"


def test_200_but_readback_unchanged_is_unverified(server, capsys, bdir):
    server.write_override = (200, [])
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz", "--yes", "--backup-dir", bdir], capsys)
    assert code == 4 and doc["status"] == "mismatch"


def test_readback_failure_is_unverified(server, capsys, bdir):
    def break_list(fake):
        fake.list_override = (500, "down")
    server.after_write = break_list
    code, doc, _ = run_json(["set", "--id", fx.CFG_A, "--facility-name", "zz", "--yes", "--backup-dir", bdir], capsys)
    assert code == 4 and doc["status"] == "unverified"


def test_export_round_trip_into_set(server, capsys, tmp_path, bdir):
    out = tmp_path / "links.json"
    assert run(["export", "--id", fx.CFG_A, "-o", str(out)], capsys)[0] == 0
    code, doc, _ = run_json(["set", "--from", str(out), "--yes", "--backup-dir", bdir], capsys)
    assert code == 0 and doc["status"] == "no-op"


def test_skill_md_mentions_every_subcommand():
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---\nname: onping-pak-transport-link\n")
    for cmd in ("list", "get", "export", "set", "delete"):
        assert f'"$LINK" {cmd}' in text
    assert "WARNING" in text.split("\n## ")[0]
