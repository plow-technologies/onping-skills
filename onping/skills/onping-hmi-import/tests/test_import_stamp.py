"""Offline tests for onping-hmi-import: the overwrite concurrency stamp and --new orphan recording.

Run from onping/skills:
    uv run --with pytest --with requests pytest -q onping-hmi-import/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS))

SECRET = "tok-secret.stamp.sample-value"
U1 = "11111111-1111-1111-1111-111111111111"
FILE_STAMP = 111
STORED = 500
DHALL = "{ _dashId = \"11111111-1111-1111-1111-111111111111\" }"


class Resp:
    def __init__(self, status, body, url):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.url = url
        self.history = []

    def json(self):
        return json.loads(self.text)


class FakeOnPing:
    """Stateful HMI store: an upsert of an existing dashId must carry the stored stamp, else 400."""

    def __init__(self):
        self.stored = {U1: STORED}
        self.json_has_stamp = True
        self.export_has_stamp = False
        self.race = False  # the stored stamp moves right after the first stamp read
        self.always_reject = False
        self.calls = []  # (method, path)
        self.upserts = []  # bodies
        self._reads = 0

    def _answer(self, method, url, kw):
        path = url.split("onping.plowtech.net", 1)[-1]
        self.calls.append((method, path))
        if path.startswith("/hmi/parse"):
            return Resp(200, {"dashId": U1, "dashName": "zz", "dashComponents": [1, 2], "dashLastUpdate": FILE_STAMP}, url)
        if path.startswith("/hmi/export/"):
            text = DHALL + (f", _dashLastUpdate = {self.stored[U1]}" if self.export_has_stamp else "")
            return Resp(200, text, url)
        if path == "/hmi/upsert":
            body = kw["json"]
            self.upserts.append(json.loads(json.dumps(body)))
            did = body["dashId"]
            if self.always_reject or (did in self.stored and body.get("dashLastUpdate") != self.stored[did]):
                return Resp(400, "Internal Server Error", url)
            self.stored[did] = self.stored.get(did, 0) + 1000
            return Resp(200, {"dashId": did, "dashLastUpdate": self.stored[did]}, url)
        if path.startswith("/hmi/"):
            did = path.rsplit("/", 1)[-1]
            if did not in self.stored:
                return Resp(404, "not found", url)
            body = {"dashId": did, "dashName": "zz"}
            if self.json_has_stamp:
                body["dashLastUpdate"] = self.stored[did]
            self._reads += 1
            if self.race and self._reads == 1:
                self.stored[did] += 7
            return Resp(200, body, url)
        return Resp(404, "no route", url)

    def install(self, monkeypatch):
        for method in ("get", "post"):
            def call(url, *, headers=None, _m=method.upper(), **kw):
                return self._answer(_m, url, kw)
            monkeypatch.setattr(requests, method, call)

    def gets_of(self, prefix):
        return [p for m, p in self.calls if m == "GET" and p.startswith(prefix)]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)


@pytest.fixture
def fake(monkeypatch):
    f = FakeOnPing()
    f.install(monkeypatch)
    return f


@pytest.fixture
def dhall_file(tmp_path):
    p = tmp_path / "in.dhall"
    p.write_text(DHALL)
    return str(p)


def run(argv, capsys):
    path = SKILLS / "onping-hmi-import/scripts/import_hmi.py"
    spec = importlib.util.spec_from_file_location("import_hmi_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.main(argv)
        code = 0
    except SystemExit as e:
        code = e.code or 0
    c = capsys.readouterr()
    assert SECRET not in c.out + c.err
    return code, c.out, c.err


def test_overwrite_stamps_the_live_value_before_upserting(fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file, "--yes"], capsys)
    assert code == 0, err
    assert [b["dashLastUpdate"] for b in fake.upserts] == [STORED]
    order = [p for _, p in fake.calls]
    assert order.index(f"/hmi/{U1}") < order.index("/hmi/upsert")
    assert "Overwrote HMI" in out


def test_preview_does_not_read_the_stamp_or_upsert(fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file], capsys)
    assert code == 0
    assert [p for _, p in fake.calls] == [f"/hmi/parse/00000000-0000-0000-0000-000000000000"]
    assert "live dashLastUpdate" in err


def test_dry_run_wins_over_yes(fake, dhall_file, capsys):
    code, _, _ = run(["--input", dhall_file, "--yes", "--dry-run"], capsys)
    assert code == 0 and fake.upserts == []


def test_a_json_without_the_stamp_falls_back_to_the_export_dhall(fake, dhall_file, capsys):
    fake.json_has_stamp = False
    fake.export_has_stamp = True
    code, out, err = run(["--input", dhall_file, "--yes"], capsys)
    assert code == 0, err
    assert fake.upserts[0]["dashLastUpdate"] == STORED
    assert fake.gets_of(f"/hmi/export/{U1}")


def test_no_readable_stamp_warns_and_submits_the_files_own_value(fake, dhall_file, capsys):
    fake.json_has_stamp = False
    code, out, err = run(["--input", dhall_file, "--yes"], capsys)
    assert fake.upserts[0]["dashLastUpdate"] == FILE_STAMP
    assert "could not read the live dashLastUpdate" in err
    assert code == 1 and "stale dashLastUpdate" in err  # the fake rejects it, so the hint shows


def test_an_absent_target_is_created_without_a_stamp(fake, dhall_file, capsys):
    del fake.stored[U1]
    code, out, err = run(["--input", dhall_file, "--yes"], capsys)
    assert code == 0, err
    assert fake.upserts[0]["dashLastUpdate"] == FILE_STAMP
    assert "does not exist yet" in err


def test_a_wrong_explicit_stamp_gets_the_hint_and_no_retry(fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file, "--yes", "--concurrency-stamp", "42"], capsys)
    assert code == 1
    assert [b["dashLastUpdate"] for b in fake.upserts] == [42]
    assert "stale dashLastUpdate" in err and "not replaced and not retried" in err
    assert fake.gets_of(f"/hmi/{U1}") == []


def test_an_explicit_correct_stamp_succeeds_without_a_read(fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file, "--yes", "--concurrency-stamp", str(STORED)], capsys)
    assert code == 0, err
    assert fake.gets_of(f"/hmi/{U1}") == []


def test_no_concurrency_stamp_reproduces_the_400_and_hint(fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file, "--yes", "--no-concurrency-stamp"], capsys)
    assert code == 1
    assert [b["dashLastUpdate"] for b in fake.upserts] == [FILE_STAMP]
    assert "stale dashLastUpdate" in err and "Internal Server Error" in err
    assert fake.gets_of(f"/hmi/{U1}") == []
    assert "Import FAILED" in err


def test_a_stamp_that_moved_between_read_and_upsert_is_retried_once(fake, dhall_file, capsys):
    fake.race = True
    code, out, err = run(["--input", dhall_file, "--yes", "--json"], capsys)
    assert code == 0, err
    assert [b["dashLastUpdate"] for b in fake.upserts] == [STORED, STORED + 7]
    report = json.loads(out)
    assert report["concurrencyStamp"] == {"mode": "fetched", "value": STORED + 7, "retried": True}
    assert "retrying once" in err


def test_an_unchanged_stamp_is_not_retried(fake, dhall_file, capsys):
    fake.always_reject = True
    code, out, err = run(["--input", dhall_file, "--yes"], capsys)
    assert code == 1
    assert len(fake.upserts) == 1
    assert "not retrying" in err


def test_a_changed_stamp_that_is_rejected_again_fails_after_one_retry(fake, dhall_file, capsys):
    fake.race = True
    fake.always_reject = True
    code, out, err = run(["--input", dhall_file, "--yes"], capsys)
    assert code == 1 and len(fake.upserts) == 2


def test_new_creates_without_reading_a_stamp_and_prints_the_uuid(fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file, "--new", "--yes"], capsys)
    assert code == 0, err
    new_id = fake.upserts[0]["dashId"]
    assert new_id != U1
    assert fake.gets_of("/hmi/export") == [] and fake.gets_of(f"/hmi/{new_id}") == []
    assert f"NEW HMI UUID: {new_id}" in out.splitlines()
    assert "onping-hmi-list will not show it" in out


def test_record_new_appends_the_uuid_and_a_timestamp(fake, dhall_file, tmp_path, capsys):
    rec = tmp_path / "copies.txt"
    rec.write_text("older\t2026-01-01T00:00:00Z\n")
    code, out, err = run(["--input", dhall_file, "--new", "--yes", "--record-new", str(rec), "--json"], capsys)
    assert code == 0, err
    new_id = fake.upserts[0]["dashId"]
    lines = rec.read_text().splitlines()
    assert lines[0].startswith("older") and len(lines) == 2
    uuid_, stamp = lines[1].split("\t")
    assert uuid_ == new_id and stamp.endswith("Z")
    assert json.loads(out)["recordedTo"] == str(rec)


def test_record_new_is_not_written_when_the_create_fails(fake, dhall_file, tmp_path, capsys):
    fake.always_reject = True
    rec = tmp_path / "copies.txt"
    code, out, err = run(["--input", dhall_file, "--new", "--yes", "--record-new", str(rec)], capsys)
    assert code == 1 and rec.read_text() == ""


def test_preview_with_record_new_touches_no_file(fake, dhall_file, tmp_path, capsys):
    rec = tmp_path / "copies.txt"
    code, out, err = run(["--input", dhall_file, "--new", "--record-new", str(rec)], capsys)
    assert code == 0 and not rec.exists() and fake.upserts == []


def test_an_unwritable_record_path_is_exit_2_before_the_upsert(fake, dhall_file, tmp_path, capsys):
    code, out, err = run(["--input", dhall_file, "--new", "--yes", "--record-new", str(tmp_path / "no" / "c.txt")], capsys)
    assert code == 2 and fake.upserts == []
    assert "nothing was imported" in err


@pytest.mark.parametrize(
    "extra",
    [
        ["--concurrency-stamp", "1", "--no-concurrency-stamp"],
        ["--new", "--concurrency-stamp", "1"],
        ["--new", "--no-concurrency-stamp"],
        ["--record-new", "c.txt"],
        ["--concurrency-stamp", "-5"],
        ["--concurrency-stamp", "12x"],
        ["--concurrency-stamp", "1.5"],
    ],
)
def test_usage_errors_are_exit_2_before_any_request(extra, fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file, "--yes", *extra], capsys)
    assert code == 2 and fake.calls == []


@pytest.mark.parametrize("old", [["--concurrency-token", "5"], ["--no-token"]])
def test_the_unshipped_working_names_are_not_accepted(old, fake, dhall_file, capsys):
    code, out, err = run(["--input", dhall_file, "--yes", *old], capsys)
    assert code == 2 and fake.calls == []


def test_help_names_the_new_flags_only(capsys):
    code, out, err = run(["--help"], capsys)
    assert code == 0
    assert "--concurrency-stamp" in out and "--no-concurrency-stamp" in out and "--record-new" in out
    assert "--concurrency-token" not in out and "--no-token" not in out
