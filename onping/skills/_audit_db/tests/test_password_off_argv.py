"""Offline tests: the postgres password never reaches a command line.

A fake `ssh` on PATH records its argv, then runs the remote command locally
with `sh -c`, so the real shell snippet is exercised. A fake `psql` records
the PGPASSWORD it sees. Nothing touches a network or a real database.

Run from onping/skills:
    uv run --with pytest pytest -q _audit_db/tests
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _audit_db import audit_db  # noqa: E402

FAKE_SSH = """#!/bin/sh
printf '%s\\n' "$@" >> "$FAKE_LOG/ssh-argv"
eval "last=\\${$#}"
exec sh -c "$last"
"""

FAKE_PSQL = """#!/bin/sh
printf '%s' "$PGPASSWORD" > "$FAKE_LOG/seen-password"
printf '%s\\n' "$@" > "$FAKE_LOG/psql-argv"
echo result-row
"""


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("ssh", FAKE_SSH), ("psql", FAKE_PSQL)):
        f = bindir / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "log"
    log.mkdir()
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    return log


def target(password: str) -> audit_db.PgTarget:
    return audit_db.PgTarget("audit.example", "db.example", "5432", "u", "d", password)


PASSWORDS = [
    "pw-simple-value-0123",
    "has space and $dollar `tick` 'quote' \"dq\" ; & |",
    "  leading-and-trailing  ",
    "back\\slash\\",
    "",
]


@pytest.mark.parametrize("password", PASSWORDS)
def test_password_reaches_psql_but_not_argv(fakes, password):
    out = audit_db._psql(target(password), "select 1")
    assert out.strip() == "result-row"
    assert (fakes / "seen-password").read_text() == password
    assert (fakes / "ssh-argv").read_text() != ""
    if password.strip():
        for log in ("ssh-argv", "psql-argv"):
            assert password not in (fakes / log).read_text(), log


def test_ssh_argv_has_no_password_marker(fakes):
    audit_db._psql(target("pw-simple-value-0123"), "select 1")
    argv = (fakes / "ssh-argv").read_text()
    assert "PGPASSWORD=" not in argv
    assert "pw-simple-value-0123" not in argv
    assert "psql" in argv


def test_sql_and_connection_args_unchanged(fakes):
    audit_db._psql(target("pw-simple-value-0123"), "select 'a b'")
    args = (fakes / "psql-argv").read_text().split("\n")
    assert args[:8] == ["-h", "db.example", "-p", "5432", "-U", "u", "-d", "d"]
    assert "select 'a b'" in args


def test_password_with_newline_is_refused(fakes, capsys):
    with pytest.raises(SystemExit) as e:
        audit_db._psql(target("line1\nline2"), "select 1")
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "newline" in err
    assert "line1" not in err and "line2" not in err
    assert not (fakes / "ssh-argv").exists()


def test_ssh_stdin_text_is_passed_through(monkeypatch):
    seen = []

    def fake_run(argv, **kw):
        seen.append(kw)

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    monkeypatch.setattr(audit_db.subprocess, "run", fake_run)
    audit_db._ssh("h", "true")
    audit_db._ssh("h", "cat", stdin_text="x\n")
    assert seen[0]["input"] is None
    assert seen[1]["input"] == "x\n"


def test_failure_message_does_not_echo_password(fakes, capsys):
    pw = "pw-secret-must-not-print"
    ssh = fakes.parent / "bin" / "ssh"
    ssh.write_text("#!/bin/sh\necho 'boom' >&2\nexit 255\n")
    with pytest.raises(SystemExit):
        audit_db._psql(target(pw), "select 1")
    assert pw not in capsys.readouterr().err
