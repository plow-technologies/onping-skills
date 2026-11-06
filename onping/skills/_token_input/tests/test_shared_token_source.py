"""Offline tests for the shared token source.

Run from onping/skills:
    uv run --with pytest pytest -q _token_input/tests
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _token_input import token_source as ts  # noqa: E402

SECRET = "tok-secret.legacy.sample-value"


def parser():
    p = argparse.ArgumentParser(prog="x")
    p.add_argument("ident", nargs="?")
    p.add_argument("--input")
    return p


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ts.ACCESS_TOKEN_ENV, raising=False)


def test_env_token(monkeypatch, capsys):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, f"  {SECRET}\n")
    a = ts.parse(parser(), ["I1"])
    assert (a.access_token, a.ident, a.access_token_source) == (SECRET, "I1", "$ONPING_ACCESS_TOKEN")
    assert capsys.readouterr().err == ""


def test_stdin_token_beats_env(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, "from-env")
    monkeypatch.setattr(sys, "stdin", io.StringIO(SECRET + "\n"))
    a = ts.parse(parser(), ["I1", "--token-stdin"])
    assert (a.access_token, a.access_token_source) == (SECRET, "--token-stdin")


@pytest.mark.parametrize("text", ["", " \n", "two words\n"])
def test_stdin_needs_exactly_one_word(monkeypatch, capsys, text):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), ["--token-stdin"])
    assert e.value.code == 2 and "exactly one access token" in capsys.readouterr().err


def test_first_word_token_warns_and_the_message_names_no_value(capsys):
    a = ts.parse(parser(), [SECRET, "I1"])
    err = capsys.readouterr().err
    assert (a.access_token, a.ident, a.access_token_source) == (SECRET, "I1", "argv (deprecated)")
    assert "deprecated" in err and SECRET not in err


def test_a_usage_error_replaces_the_first_word(capsys):
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), [SECRET, "I1", "I2"])
    assert e.value.code == 2
    assert SECRET not in capsys.readouterr().err


def test_flag_first_is_never_a_token(capsys):
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), ["--bogus", "I1"])
    assert e.value.code == 2


def test_both_stdin_and_first_word_is_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("other"))
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), [SECRET, "I1", "--token-stdin"])
    assert e.value.code == 2 and SECRET not in capsys.readouterr().err


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_missing_token_hint_has_no_home_path(monkeypatch, capsys, blank):
    if blank is not None:
        monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, blank)
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), ["I1"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and ts.LOGIN_HINT in err and ".claude" not in err


def test_is_id_blocks_the_legacy_retry(monkeypatch, capsys):
    is_id = lambda w: w.startswith("ID-")  # noqa: E731
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), ["ID-1", "ID-2"], is_id=is_id)
    assert e.value.code == 2
    # an id-shaped first word is never retried as a token, so no deprecation warning appears
    assert "deprecated" not in capsys.readouterr().err


def test_is_id_leaves_other_first_words_to_the_legacy_retry(capsys):
    a = ts.parse(parser(), [SECRET, "ID-1"], is_id=lambda w: w.startswith("ID-"))
    assert (a.access_token, a.ident) == (SECRET, "ID-1")


def test_stdin_busy_refuses_token_stdin_and_leaves_stdin_unread(monkeypatch, capsys):
    stdin = io.StringIO(SECRET + "\npayload")
    monkeypatch.setattr(sys, "stdin", stdin)
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), ["--token-stdin"], stdin_busy=lambda a: not a.input)
    assert e.value.code == 2 and stdin.tell() == 0
    err = capsys.readouterr().err
    assert "--input" in err and SECRET not in err


def test_stdin_busy_allows_token_stdin_with_a_file(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(SECRET))
    a = ts.parse(parser(), ["--token-stdin", "--input", "f"], stdin_busy=lambda a: not a.input)
    assert a.access_token == SECRET


def test_stdin_busy_does_not_apply_to_the_env_token(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    a = ts.parse(parser(), [], stdin_busy=lambda a: not a.input)
    assert a.access_token == SECRET


def sub_parser():
    p = argparse.ArgumentParser(prog="x")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("delete")
    d.add_argument("serial", type=int)
    sub.add_parser("list")
    return p


SUBS = {"delete", "list"}


def test_subcommand_new_form(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    a = ts.parse(sub_parser(), ["delete", "3"], is_id=str.isdigit, subcommands=SUBS)
    assert (a.cmd, a.serial, a.access_token) == ("delete", 3, SECRET)


def test_subcommand_legacy_token_follows_the_subcommand(capsys):
    a = ts.parse(sub_parser(), ["delete", SECRET, "3"], is_id=str.isdigit, subcommands=SUBS)
    err = capsys.readouterr().err
    assert (a.cmd, a.serial, a.access_token, a.access_token_source) == ("delete", 3, SECRET, "argv (deprecated)")
    assert "deprecated" in err and SECRET not in err


def test_subcommand_stray_second_serial_is_not_a_token(monkeypatch, capsys):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, "from-env")
    with pytest.raises(SystemExit) as e:
        ts.parse(sub_parser(), ["delete", "1", "2"], is_id=str.isdigit, subcommands=SUBS)
    assert e.value.code == 2 and "deprecated" not in capsys.readouterr().err


def test_subcommand_failure_masks_the_candidate(capsys):
    with pytest.raises(SystemExit) as e:
        ts.parse(sub_parser(), ["delete", SECRET, "x", "y"], is_id=str.isdigit, subcommands=SUBS)
    assert e.value.code == 2 and SECRET not in capsys.readouterr().err


def test_a_lone_word_that_is_not_a_subcommand_is_an_error(monkeypatch, capsys):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, "from-env")
    with pytest.raises(SystemExit) as e:
        ts.parse(sub_parser(), [SECRET], subcommands=SUBS)
    assert e.value.code == 2 and SECRET not in capsys.readouterr().err


def test_subcommand_legacy_with_token_stdin_is_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("other"))
    with pytest.raises(SystemExit) as e:
        ts.parse(sub_parser(), ["delete", SECRET, "3", "--token-stdin"], subcommands=SUBS)
    assert e.value.code == 2 and SECRET not in capsys.readouterr().err


def test_refuse_mode_exits_2_without_echoing_the_word(monkeypatch, capsys):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, "from-env")
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), [SECRET, "I1"], legacy="refuse")
    err = capsys.readouterr().err
    assert e.value.code == 2 and SECRET not in err
    assert ts.ACCESS_TOKEN_ENV in err and "--token-stdin" in err


def test_refuse_mode_leaves_the_new_form_alone(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    assert ts.parse(parser(), ["I1"], legacy="refuse").access_token == SECRET


def test_refuse_mode_failure_masks_the_word(capsys):
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), [SECRET, "I1", "I2"], legacy="refuse")
    assert e.value.code == 2 and SECRET not in capsys.readouterr().err


def test_unknown_legacy_mode_is_a_programming_error():
    with pytest.raises(ValueError):
        ts.parse(parser(), [], legacy="allow")


def test_stdin_hint_is_in_the_busy_message(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(SECRET))
    with pytest.raises(SystemExit):
        ts.parse(parser(), ["--token-stdin"], stdin_busy=lambda a: True, stdin_hint="pass the ids as arguments")
    assert "pass the ids as arguments" in capsys.readouterr().err


def test_top_level_subcommand_name_is_never_read_as_a_token(monkeypatch, capsys):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    with pytest.raises(SystemExit) as e:
        ts.parse(sub_parser(), ["list", "delete", "3"])
    assert e.value.code == 2
    assert "deprecated" not in capsys.readouterr().err


def test_top_level_legacy_token_before_a_subcommand_still_warns(monkeypatch, capsys):
    monkeypatch.delenv(ts.ACCESS_TOKEN_ENV, raising=False)
    a = ts.parse(sub_parser(), [SECRET, "delete", "3"])
    assert a.access_token == SECRET and "deprecated" in capsys.readouterr().err


def test_token_stdin_is_accepted_before_and_after_a_subcommand(monkeypatch):
    for argv in (["--token-stdin", "delete", "3"], ["delete", "3", "--token-stdin"]):
        monkeypatch.delenv(ts.ACCESS_TOKEN_ENV, raising=False)
        monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
        a = ts.parse(sub_parser(), argv, subcommands=SUBS, is_id=str.isdigit)
        assert (a.cmd, a.serial, a.access_token, a.access_token_source) == ("delete", 3, SECRET, "--token-stdin")


def test_a_subcommand_outside_the_set_needs_no_token(monkeypatch):
    monkeypatch.delenv(ts.ACCESS_TOKEN_ENV, raising=False)
    a = ts.parse(sub_parser(), ["list"], subcommands={"delete"})
    assert (a.cmd, a.access_token, a.access_token_source) == ("list", None, None)


def test_a_subcommand_in_the_set_still_needs_a_token(monkeypatch, capsys):
    monkeypatch.delenv(ts.ACCESS_TOKEN_ENV, raising=False)
    with pytest.raises(SystemExit) as e:
        ts.parse(sub_parser(), ["delete", "3"], subcommands={"delete"})
    assert e.value.code == 2
    assert "no OnPing access token" in capsys.readouterr().err


@pytest.mark.parametrize("word", [
    "pump trip", "pump", "separator", "tok-secret", "a" * 19, "has space in it and is long enough",
    "eyJ.abc def.ghi" + "x" * 20, "semi;colon" + "x" * 20, "tab\there" + "x" * 20, "",
])
def test_looks_like_token_rejects_queries_names_and_short_words(word):
    assert not ts.looks_like_token(word)


@pytest.mark.parametrize("word", [
    "a" * 20, "eyJhbGciOiJIUzI1NiJ9.sample.signature", "eyJ" + "A1_-" * 150 + "." + "b" * 40 + ".sig=", SECRET,
])
def test_looks_like_token_accepts_a_jwt_shaped_word(word):
    assert ts.looks_like_token(word)


@pytest.mark.parametrize("first", ["pump trip", "pump", "separator", "tok-secret", "a" * 19])
def test_a_failed_parse_is_not_retried_with_a_non_token_first_word(first, monkeypatch, capsys):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, "from-env")
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), [first, "I1", "I2"])
    cap = capsys.readouterr()
    assert e.value.code == 2 and "deprecated" not in cap.err and "unrecognized" in cap.err


def test_a_spaced_first_word_without_a_token_gets_the_missing_token_hint(capsys):
    with pytest.raises(SystemExit) as e:
        ts.parse(parser(), ["pump trip", "--input", "f"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and ts.ACCESS_TOKEN_ENV in err and "--token-stdin" in err
    assert "deprecated" not in err


def test_a_token_shaped_first_word_still_works_when_the_typed_parse_fails():
    a = ts.parse(parser(), [SECRET, "I1"])
    assert (a.access_token, a.ident, a.access_token_source) == (SECRET, "I1", "argv (deprecated)")


def test_a_second_parse_on_the_same_parser_is_safe(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    p = parser()
    first = ts.parse(p, ["I1"])
    second = ts.parse(p, ["I2"])
    assert (first.ident, second.ident) == ("I1", "I2")
    assert sum(1 for a in p._actions if "--token-stdin" in a.option_strings) == 1


def test_a_second_parse_on_a_subcommand_parser_adds_the_flag_once(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    p = sub_parser()
    ts.parse(p, ["delete", "3"], is_id=str.isdigit, subcommands=SUBS)
    ts.parse(p, ["delete", "4"], is_id=str.isdigit, subcommands=SUBS)
    for each in ts._parsers(p):
        assert sum(1 for a in each._actions if "--token-stdin" in a.option_strings) == 1


def test_error_is_the_class_method_again_after_a_parse_and_after_a_usage_exit(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    p = sub_parser()
    ts.parse(p, ["delete", "3"], subcommands=SUBS)
    with pytest.raises(SystemExit):
        ts.parse(p, ["delete", "x", "y"], subcommands=SUBS)
    for each in ts._parsers(p):
        assert "error" not in vars(each)


def test_error_is_restored_when_a_type_function_raises_something_else(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)

    def boom(word):
        raise RuntimeError("not a usage error")

    p = argparse.ArgumentParser(prog="x")
    p.add_argument("ident", type=boom)
    with pytest.raises(RuntimeError):
        ts.parse(p, ["I1"])
    assert "error" not in vars(p)


def test_an_error_override_set_by_the_caller_survives_a_parse(monkeypatch):
    monkeypatch.setenv(ts.ACCESS_TOKEN_ENV, SECRET)
    p = parser()
    mine = lambda message: (_ for _ in ()).throw(ValueError(message))  # noqa: E731
    p.error = mine
    ts.parse(p, ["I1"])
    assert p.error is mine
