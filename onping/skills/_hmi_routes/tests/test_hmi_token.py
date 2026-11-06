"""Offline tests for how the onping-hmi-* skills take the access token and the HMI UUID.

Run from onping/skills:
    uv run --with pytest --with requests pytest -q _hmi_routes/tests
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
import requests

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS))

SECRET = "tok-secret.legacy.sample-value"
U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"
DHALL = "{ _dashId = \"11111111-1111-1111-1111-111111111111\" }"
BINDINGS = "[ { from = { onpingKey = 1 }, to = None Natural } ]"

SCRIPTS = {
    "list": "onping-hmi-list/scripts/list_hmis.py",
    "export": "onping-hmi-export/scripts/export_hmi.py",
    "export-data": "onping-hmi-export-data/scripts/export_hmi_data.py",
    "import": "onping-hmi-import/scripts/import_hmi.py",
    "import-data": "onping-hmi-import-data/scripts/import_hmi_data.py",
    "delete": "onping-hmi-delete/scripts/delete_hmi.py",
}
UUID_SCRIPTS = ["export", "export-data", "import-data", "delete"]
READS_STDIN = ["import", "import-data"]


class Resp:
    def __init__(self, status, body, url):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.url = url
        self.history = []
        self._body = body

    def json(self):
        return json.loads(self.text)


class FakeOnPing:
    def __init__(self):
        self.calls = []  # (method, url, headers)

    def _answer(self, method, url):
        path = url.split("onping.plowtech.net", 1)[-1]
        if path.startswith("/hmi/export"):
            return Resp(200, DHALL, url)
        if path == "/hmi/list":
            return Resp(200, [{"hmiInfoUuid": U1, "hmiInfoName": "zz", "hmiInfoPanelName": "p"}], url)
        if path.startswith("/hmi/parse"):
            return Resp(200, {"dashId": U1, "dashName": "zz", "dashComponents": []}, url)
        if path.startswith("/hmi/upsert") or path.startswith("/hmi/import-data") or method == "DELETE":
            return Resp(200, {"ok": True}, url)
        if path.startswith("/hmi/"):
            return Resp(200, {"dashName": "zz", "dashDeleted": False}, url)
        return Resp(404, "no route", url)

    def install(self, monkeypatch):
        for method in ("get", "post", "delete"):
            def call(url, *, headers=None, _m=method.upper(), **kw):
                self.calls.append((_m, url, headers or {}))
                return self._answer(_m, url)
            monkeypatch.setattr(requests, method, call)


@pytest.fixture(autouse=True)
def _no_env_token(monkeypatch):
    monkeypatch.delenv("ONPING_ACCESS_TOKEN", raising=False)


@pytest.fixture
def fake(monkeypatch):
    f = FakeOnPing()
    f.install(monkeypatch)
    return f


def load(skill):
    path = SKILLS / SCRIPTS[skill]
    spec = importlib.util.spec_from_file_location(f"hmi_{skill.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def args_for(skill, *extra, uuid=U1):
    """A valid command line for each script: the UUID where it takes one, and --input where it needs a file."""
    a = [uuid] if skill in UUID_SCRIPTS else []
    return a + list(extra)


def run(skill, argv, capsys):
    with pytest.raises(SystemExit) as e:
        load(skill).main(argv)
    out = capsys.readouterr()
    return e.value.code, out.out, out.err


def finish(skill, argv, capsys):
    """Run main(); a clean return counts as exit 0."""
    try:
        load(skill).main(argv)
        code = 0
    except SystemExit as e:
        code = e.code or 0
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def dhall_file(tmp_path):
    p = tmp_path / "in.dhall"
    p.write_text(BINDINGS)
    return str(p)


MUTATING = ["import", "import-data", "delete"]


def full_args(skill, dhall_file, *extra, uuid=U1, yes=True):
    a = args_for(skill, uuid=uuid)
    if skill in READS_STDIN:
        a += ["--input", dhall_file]
    if yes and skill in MUTATING:
        a.append("--yes")
    return a + list(extra)


@pytest.mark.parametrize("skill", SCRIPTS)
def test_env_token_reaches_the_authorization_header(skill, fake, monkeypatch, capsys, dhall_file):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", f" {SECRET}\n")
    code, out, err = finish(skill, full_args(skill, dhall_file), capsys)
    assert code == 0, err
    assert fake.calls, "the skill made no request"
    assert {h["Authorization"] for _, _, h in fake.calls} == {f"Bearer {SECRET}"}
    assert SECRET not in out + err
    assert "deprecated" not in err


@pytest.mark.parametrize("skill", SCRIPTS)
def test_stdin_token(skill, fake, monkeypatch, capsys, dhall_file):
    monkeypatch.setattr(sys, "stdin", io.StringIO(SECRET + "\n"))
    code, out, err = finish(skill, full_args(skill, dhall_file, "--token-stdin"), capsys)
    assert code == 0, err
    assert {h["Authorization"] for _, _, h in fake.calls} == {f"Bearer {SECRET}"}
    assert SECRET not in out + err


@pytest.mark.parametrize("skill", SCRIPTS)
def test_first_word_token_still_works_and_warns(skill, fake, capsys, dhall_file):
    code, out, err = finish(skill, [SECRET] + full_args(skill, dhall_file), capsys)
    assert code == 0, err
    assert {h["Authorization"] for _, _, h in fake.calls} == {f"Bearer {SECRET}"}
    assert "deprecated" in err and "ps" in err
    assert SECRET not in out + err


@pytest.mark.parametrize("skill", SCRIPTS)
def test_no_token_is_exit_2_before_any_request(skill, fake, capsys, dhall_file):
    code, out, err = run(skill, full_args(skill, dhall_file), capsys)
    assert code == 2
    assert fake.calls == []
    assert "ONPING_ACCESS_TOKEN" in err and "--token-stdin" in err
    assert "<skills-dir>/onping-login/scripts/login.py" in err
    assert ".claude" not in err


@pytest.mark.parametrize("skill", SCRIPTS)
def test_stdin_and_first_word_together_is_exit_2(skill, fake, monkeypatch, capsys, dhall_file):
    monkeypatch.setattr(sys, "stdin", io.StringIO("other\n"))
    code, out, err = run(skill, [SECRET] + full_args(skill, dhall_file, "--token-stdin"), capsys)
    assert code == 2 and fake.calls == []
    assert SECRET not in out + err


@pytest.mark.parametrize("skill", SCRIPTS)
def test_the_parser_declares_no_token_argument(skill, fake, monkeypatch, capsys):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    code, out, err = run(skill, ["--help"], capsys)
    assert code == 0
    assert "access_token" not in out and "--token-stdin" in out


@pytest.mark.parametrize("skill", UUID_SCRIPTS)
def test_a_token_in_the_uuid_slot_is_refused_before_any_request(skill, fake, monkeypatch, capsys, dhall_file):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "envtok")
    argv = [SECRET] + (["--input", dhall_file] if skill in READS_STDIN else [])
    code, out, err = run(skill, argv, capsys)
    assert code == 2 and fake.calls == []
    assert SECRET not in out + err and "envtok" not in out + err


@pytest.mark.parametrize("skill", UUID_SCRIPTS)
def test_a_stray_word_before_the_uuid_is_never_retried_as_a_token(skill, fake, capsys, dhall_file):
    code, out, err = run(skill, ["stray"] + full_args(skill, dhall_file, uuid=U2) + [U1], capsys)
    assert code == 2 and fake.calls == []


@pytest.mark.parametrize("skill", UUID_SCRIPTS)
def test_two_uuids_are_not_read_as_token_and_uuid(skill, fake, monkeypatch, capsys, dhall_file):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    argv = [U1, U2] + (["--input", dhall_file] if skill in READS_STDIN else [])
    code, out, err = run(skill, argv, capsys)
    assert code == 2 and fake.calls == []


@pytest.mark.parametrize("skill", ["list", "import"])
def test_a_uuid_first_word_is_not_a_token_where_no_uuid_is_taken(skill, fake, monkeypatch, capsys, dhall_file):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    argv = [U1] + (["--input", dhall_file] if skill == "import" else [])
    code, out, err = run(skill, argv, capsys)
    assert code == 2 and fake.calls == []


@pytest.mark.parametrize("skill", READS_STDIN)
def test_token_stdin_without_input_is_exit_2_and_leaves_stdin_unread(skill, fake, monkeypatch, capsys):
    stdin = io.StringIO(SECRET + "\n" + BINDINGS)
    monkeypatch.setattr(sys, "stdin", stdin)
    code, out, err = run(skill, args_for(skill, "--token-stdin"), capsys)
    assert code == 2 and fake.calls == []
    assert "--input" in err and stdin.tell() == 0
    assert SECRET not in out + err


@pytest.mark.parametrize("skill", READS_STDIN)
def test_env_token_with_the_dhall_on_stdin(skill, fake, monkeypatch, capsys):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    monkeypatch.setattr(sys, "stdin", io.StringIO(BINDINGS))
    code, out, err = finish(skill, args_for(skill, "--yes"), capsys)
    assert code == 0, err
    assert fake.calls and {h["Authorization"] for _, _, h in fake.calls} == {f"Bearer {SECRET}"}


def test_import_data_preview_makes_no_request_and_prints_no_token(fake, monkeypatch, capsys, dhall_file):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    code, out, err = finish("import-data", full_args("import-data", dhall_file, "--json", yes=False), capsys)
    assert code == 0 and fake.calls == []
    assert SECRET not in out + err


@pytest.mark.parametrize("flags", [[], ["--json"], ["--yes"], ["--yes", "--json"]])
def test_delete_output_never_carries_the_token(flags, fake, monkeypatch, capsys):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    code, out, err = finish("delete", [U1, *flags], capsys)
    assert code == 0, err
    assert SECRET not in out + err
    deleted = [m for m, _, _ in fake.calls if m == "DELETE"]
    assert bool(deleted) == ("--yes" in flags)


def test_export_writes_the_file_and_no_token_lands_in_it(fake, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    target = tmp_path / "hmi.dhall"
    code, out, err = finish("export", [U1, "--output", str(target)], capsys)
    assert code == 0, err
    assert target.read_text() == DHALL
    assert SECRET not in target.read_text() + out + err


def test_the_namespace_names_the_source_never_the_value(monkeypatch):
    from _hmi_routes import hmi_args
    import argparse

    monkeypatch.setenv("ONPING_ACCESS_TOKEN", SECRET)
    p = argparse.ArgumentParser()
    p.add_argument("uuid")
    a = hmi_args.parse(p, [U1], uuid=True)
    assert a.access_token == SECRET and a.access_token_source == "$ONPING_ACCESS_TOKEN"


@pytest.mark.parametrize("word", ["tok-secret", "o00000000000000000000a001", "1111-1111", U1 + "0", "g" * 8 + U1[8:]])
def test_only_a_uuid_is_accepted_as_an_hmi_uuid(word):
    from _hmi_routes.hmi_args import is_hmi_uuid

    assert not is_hmi_uuid(word)


@pytest.mark.parametrize("word", [U1, U1.upper(), "abcdef01-2345-6789-abcd-ef0123456789"])
def test_uuid_shapes(word):
    from _hmi_routes.hmi_args import is_hmi_uuid

    assert is_hmi_uuid(word)
