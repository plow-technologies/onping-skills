"""Token-input contract of cp-import-json/cp_import_json.py: the token comes from $ONPING_ACCESS_TOKEN or --token-stdin; a first-word token warns.

Run from onping/skills:
    uv run --with pytest --with requests pytest -q cp-import-json/tests
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _token_input.contract import Contract  # noqa: E402

C = Contract(Path(__file__).resolve().parents[1] / "scripts" / "cp_import_json.py",
    after_subcommand='fetch-normalize',
    valid=['fetch-normalize', '1001'],
)


def test_help_names_the_token_sources_and_no_token_argument(monkeypatch, capsys):
    C.check_help(monkeypatch, capsys)


def test_no_token_exits_2(monkeypatch, capsys):
    C.check_no_token_exits_2(monkeypatch, capsys)


def test_env_token(monkeypatch, capsys):
    C.check_env_token(monkeypatch, capsys)


def test_stdin_token(monkeypatch, capsys):
    C.check_stdin_token(monkeypatch, capsys)


def test_first_word_token_warns_and_is_not_echoed(monkeypatch, capsys):
    C.check_legacy_form(monkeypatch, capsys)


def test_first_word_token_with_token_stdin_exits_2(monkeypatch, capsys):
    C.check_legacy_with_stdin_is_refused(monkeypatch, capsys)


def test_a_token_in_the_id_slot_is_refused(monkeypatch, capsys):
    C.check_token_in_the_id_slot_is_refused(monkeypatch, capsys)


def test_normalize_needs_no_token(monkeypatch, capsys):
    kind, args, _ = C.run(['normalize'], monkeypatch, env=None)
    assert kind == "parsed" and args.access_token is None
    assert capsys.readouterr().err == ""
