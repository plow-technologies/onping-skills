"""Offline tests for onping-delete-singlewell-manual (no network).

    uv run --with pytest --with requests pytest onping/skills/onping-delete-singlewell-manual/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(SKILLS / "_singlewell_manual_routes" / "tests"))
import swm_fakes as F  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "delete_location", SKILLS / "onping-delete-singlewell-manual" / "scripts" / "delete_location.py"
)
delete = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(delete)

REF = 40050


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "tok")
    f = F.FakeOnPing().install(monkeypatch)
    f.seed(REF, "zz-skill-test-unit")
    return f


def deletes(fake) -> list[dict]:
    return [c for c in fake.calls if c["path"] == "/singlewellmanual/delete"]


def run(tmp_path, *extra: str, ref: int = REF) -> int:
    return delete.main([str(ref), "--backup", str(tmp_path / "b.json"), *extra])


# ─────────────────────────────── preview ───────────────────────────────


def test_preview_sends_nothing_and_writes_no_backup(fake, tmp_path, capsys):
    assert run(tmp_path) == 0
    assert deletes(fake) == []
    assert not (tmp_path / "b.json").exists()
    out = capsys.readouterr().out
    assert "Preview only" in out and "no undo" in out
    assert "switcher routing index" in out  # residue named up front


def test_dry_run_wins_over_yes(fake, tmp_path):
    assert run(tmp_path, "--yes", "--dry-run") == 0
    assert deletes(fake) == []


# ─────────────────────────────── refusals ───────────────────────────────


def test_missing_location_is_refused(fake, tmp_path):
    assert run(tmp_path, "--yes", ref=49999) == 3
    assert deletes(fake) == []


def test_group_not_owned_is_refused(fake, tmp_path, capsys):
    fake.seed(40060, "zz-other", group=F.G_OTHER)
    assert run(tmp_path, "--yes", ref=40060) == 3
    assert deletes(fake) == []
    assert "not one of your owned groups" in capsys.readouterr().out


def test_parameters_are_refused_without_the_flag(fake, tmp_path, capsys):
    assert run(tmp_path, "--yes", ref=F.EXISTING) == 3
    assert deletes(fake) == []
    assert "--allow-parameters" in capsys.readouterr().out


def test_parameters_allowed_with_the_flag(fake, tmp_path, capsys):
    assert run(tmp_path, "--yes", "--allow-parameters", "--json", ref=F.EXISTING) == 0
    rep = json.loads(capsys.readouterr().out)
    assert any("PIDs are orphaned" in x for x in rep["leaves"])


def test_partial_record_is_refused(fake, tmp_path, capsys):
    del fake.extras[REF]
    assert run(tmp_path, "--yes") == 3
    assert deletes(fake) == []


def test_unreadable_location_exits_1(fake, tmp_path):
    fake.fail_reads.add("/singlewellmanual/get/loc")
    assert run(tmp_path, "--yes") == 1
    assert deletes(fake) == []


def test_existing_backup_is_never_overwritten(fake, tmp_path):
    (tmp_path / "b.json").write_text("keep me")
    assert run(tmp_path, "--yes") == 1
    assert deletes(fake) == []
    assert (tmp_path / "b.json").read_text() == "keep me"


# ─────────────────────────────── writes ───────────────────────────────


def test_verified_delete(fake, tmp_path, capsys):
    assert run(tmp_path, "--yes") == 0
    sent = deletes(fake)
    assert len(sent) == 1 and sent[0]["body"] == [REF]
    backup = json.loads((tmp_path / "b.json").read_text())
    assert backup["location_id"] == REF
    assert backup["config"]["manualLocationRefId"] == REF
    assert REF not in fake.manual and REF not in fake.mongo
    # the server's delete leaves these, and the skill says so
    assert REF in fake.mysql and REF in fake.extras and REF in fake.group_join and REF in fake.switcher
    out = capsys.readouterr().out
    assert "Verified gone" in out and "left behind" in out


def test_success_body_but_nothing_deleted(fake, tmp_path, capsys):
    fake.delete_mode = "noop"
    assert run(tmp_path, "--yes") == 4
    assert "NOT DELETED" in capsys.readouterr().out


def test_manual_delete_fails_but_mongo_removed(fake, tmp_path, capsys):
    fake.delete_mode = "manual_fails"
    assert run(tmp_path, "--yes") == 4
    assert "PARTLY DELETED" in capsys.readouterr().out


def test_mongo_location_survives(fake, tmp_path, capsys):
    fake.delete_mode = "keep_mongo"
    assert run(tmp_path, "--yes") == 4
    assert "Mongo location survives" in capsys.readouterr().out


def test_lost_response_read_back_decides(fake, tmp_path, capsys):
    fake.delete_lose_response = True
    assert run(tmp_path, "--yes") == 0
    assert len(deletes(fake)) == 1
    assert "Verified gone" in capsys.readouterr().out


def test_unreachable_lj_gone_with_failure_body_is_flagged(fake, tmp_path, capsys, monkeypatch):
    fake.delete_mode = "manual_fails"
    original = fake._delete

    def then_unreachable(body, url):
        resp = original(body, url)
        fake.lj_unreachable = True
        return resp

    monkeypatch.setattr(fake, "_delete", then_unreachable)
    assert run(tmp_path, "--yes", "--json") == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["note"].startswith("gone by read-back, but the delete body was not Success")


def test_listing_unreadable_after_delete_is_unknown(fake, tmp_path, monkeypatch, capsys):
    original = fake._delete

    def then_fail(body, url):
        resp = original(body, url)
        fake.fail_reads.add("/singlewellmanual/locations")
        return resp

    monkeypatch.setattr(fake, "_delete", then_fail)
    assert run(tmp_path, "--yes") == 4
    assert "could not be read" in capsys.readouterr().out
