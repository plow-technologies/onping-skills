"""Token-input contract of onping-update-lufkin/update_location.py: the token comes from $ONPING_ACCESS_TOKEN or --token-stdin; a first-word token warns.

Run from onping/skills:
    uv run --with pytest --with requests pytest -q onping-update-lufkin/tests
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _token_input.contract import Contract  # noqa: E402

C = Contract(Path(__file__).resolve().parents[1] / "scripts" / "update_location.py",
    stray=['1', '2'],
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


def test_a_stray_extra_id_is_refused_not_read_as_a_token(monkeypatch, capsys):
    C.check_stray_extra_id_is_refused(monkeypatch, capsys)
