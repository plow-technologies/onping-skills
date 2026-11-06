"""Token-input contract of onping-mqtt-integrator-rule-parse/parse_rule.py: the token comes from $ONPING_ACCESS_TOKEN or --token-stdin; a first-word token warns.

Run from onping/skills:
    uv run --with pytest --with requests pytest -q onping-mqtt-integrator-rule-parse/tests
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _token_input.contract import Contract  # noqa: E402

C = Contract(Path(__file__).resolve().parents[1] / "scripts" / "parse_rule.py",
    valid=['x1'],
)


def test_help_names_the_token_sources_and_no_token_argument(monkeypatch, capsys):
    C.check_help(monkeypatch, capsys)


def test_no_token_exits_2(monkeypatch, capsys):
    C.check_no_token_exits_2(monkeypatch, capsys)


def test_env_token(monkeypatch, capsys):
    C.check_env_token(monkeypatch, capsys)


def test_stdin_token(monkeypatch, capsys):
    C.check_stdin_token(monkeypatch, capsys)


def test_a_token_in_the_id_slot_is_refused(monkeypatch, capsys):
    C.check_token_in_the_id_slot_is_refused(monkeypatch, capsys)


def test_a_first_word_token_is_not_recognised_for_free_text_rules(monkeypatch, capsys):
    """`rule ...` takes any number of free-text words, so `TOKEN RULE` parses as two rules: with no
    token supplied it exits 2 asking for $ONPING_ACCESS_TOKEN or --token-stdin, and never uses a word as a token."""
    kind, code, _ = C.run(["legacy-token.sample.value", "x1"], monkeypatch, env=None)
    err = capsys.readouterr().err
    assert (kind, code) == ("exit", 2)
    assert "ONPING_ACCESS_TOKEN" in err and "--token-stdin" in err

