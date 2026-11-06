"""Test harness: the access-token contract of one skill script.

A skill's test file builds a `Contract` for its script and calls the `check_*` methods from test
functions (pass pytest's `monkeypatch` and `capsys`). The harness runs the script's real `main` with
`token_source.parse` wrapped, so the parse is real but nothing after it runs: no request is sent, no
file is written. Nothing here imports pytest.

The valid command line is derived from the script's own parser (required positionals and options get
a sample value), and can be overridden with `valid=[...]` for the odd script.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import io
import sys
from pathlib import Path

from _token_input import shapes, token_source

_REAL_PARSE = token_source.parse
ENV_TOKEN = "env-token.sample.value"
LEGACY_TOKEN = "legacy-token.sample.value"
STDIN_TOKEN = "stdin-token.sample.value"
UUID = "11111111-2222-3333-4444-555555555555"
OID = "o" + "a" * 24
HASH = "A" * 43 + "="

_SAMPLES = {
    "uuid": UUID, "widget_id": OID, "ctable_id": OID, "script_hash": HASH, "script_id": HASH,
    "start_date": "2026-01-01", "end_date": "2026-01-02",
}


class _Parsed(Exception):
    def __init__(self, args, parser, kwargs):
        self.args_ns, self.parser, self.kwargs = args, parser, kwargs


def _sample(action: argparse.Action) -> str:
    if action.choices:
        return str(next(iter(action.choices)))
    if action.dest in _SAMPLES:
        return _SAMPLES[action.dest]
    if action.type is int or action.type is shapes.int_arg:
        return "1"
    return "x1"


def _valid_for(p: argparse.ArgumentParser) -> list[str]:
    out: list[str] = []
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            name = next(iter(a.choices))
            out += [name] + _valid_for(a.choices[name])
        elif a.option_strings:
            if a.required:
                out += [a.option_strings[0], _sample(a)]
        elif a.nargs is None or a.nargs == "+" or isinstance(a.nargs, int):
            out += [_sample(a)] * (a.nargs if isinstance(a.nargs, int) else 1)
    return out


class Contract:
    def __init__(
        self,
        script: Path | str,
        *,
        valid: list[str] | None = None,
        legacy: str = "warn",
        after_subcommand: str | None = None,
        payload_flag: str | None = None,
        typed_first: bool = True,
        stray: list[str] | None = None,
    ):
        """`legacy`: "warn" or "refuse". `after_subcommand`: the old form puts the token after this
        subcommand name (the valid line starts with it). `payload_flag`: a flag whose absence means the
        script reads its input from stdin (`--input`), so `--token-stdin` is refused without it.
        `typed_first`: the first positional is typed, so a token in its slot fails the parse.
        `stray`: a command line with one extra id before the real arguments, which must exit 2."""
        self.script = Path(script)
        self.valid_override = valid
        self.legacy = legacy
        self.after_subcommand = after_subcommand
        self.payload_flag = payload_flag
        self.typed_first = typed_first
        self.stray_argv = stray
        self._mod = None

    # ------------------------------------------------------------------ plumbing
    def module(self):
        if self._mod is None:
            name = f"_contract_{self.script.parent.parent.name}_{self.script.stem}".replace("-", "_")
            spec = importlib.util.spec_from_file_location(name, self.script)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            self._mod = mod
        return self._mod

    def _call_main(self, argv: list[str], monkeypatch):
        mod = self.module()
        monkeypatch.setattr(sys, "argv", [str(self.script), *argv])
        params = inspect.signature(mod.main).parameters
        return mod.main(list(argv)) if params else mod.main()

    def run(self, argv: list[str], monkeypatch, *, env: str | None = ENV_TOKEN, introspect: bool = False):
        """Run main(argv). Returns ('parsed', namespace) or ('exit', code)."""
        real = _REAL_PARSE

        def fake(p, a, environ=None, **kw):
            if introspect:
                raise _Parsed(None, p, kw)
            raise _Parsed(real(p, a, environ, **kw), p, kw)

        monkeypatch.setattr(token_source, "parse", fake)
        if env is None:
            monkeypatch.delenv(token_source.ACCESS_TOKEN_ENV, raising=False)
        else:
            monkeypatch.setenv(token_source.ACCESS_TOKEN_ENV, env)
        try:
            code = self._call_main(argv, monkeypatch)
        except _Parsed as done:
            return ("parsed", done.args_ns, done)
        except SystemExit as e:
            return ("exit", e.code, None)
        if isinstance(code, int):  # a main that reports a usage error as its return code
            return ("exit", code, None)
        raise AssertionError("main returned without calling token_source.parse")

    def valid(self, monkeypatch) -> list[str]:
        if self.valid_override is not None:
            return list(self.valid_override)
        kind, _, done = self.run([], monkeypatch, introspect=True)
        assert kind == "parsed", "could not introspect the parser"
        return _valid_for(done.parser)

    def _legacy_argv(self, valid: list[str]) -> list[str]:
        if self.after_subcommand and valid[:1] == [self.after_subcommand]:
            return [valid[0], LEGACY_TOKEN, *valid[1:]]
        return [LEGACY_TOKEN, *valid]

    # ------------------------------------------------------------------ checks
    def check_help(self, monkeypatch, capsys):
        kind, code, _ = self.run(["--help"], monkeypatch)
        out = capsys.readouterr().out
        assert (kind, code) == ("exit", 0)
        assert "--token-stdin" in out and "ONPING_ACCESS_TOKEN" in out
        assert "access_token" not in out.replace("--token-stdin", "")

    def check_no_token_exits_2(self, monkeypatch, capsys):
        valid = self.valid(monkeypatch)
        kind, code, _ = self.run(valid, monkeypatch, env=None)
        err = capsys.readouterr().err
        assert (kind, code) == ("exit", 2)
        assert token_source.ACCESS_TOKEN_ENV in err and "--token-stdin" in err

    def check_env_token(self, monkeypatch, capsys):
        valid = self.valid(monkeypatch)
        kind, args, _ = self.run(valid, monkeypatch)
        assert kind == "parsed", f"valid line {valid} did not parse: exit {args}\n{capsys.readouterr().err}"
        assert args.access_token == ENV_TOKEN and args.access_token_source == "$ONPING_ACCESS_TOKEN"
        assert capsys.readouterr().err == ""

    def check_stdin_token(self, monkeypatch, capsys):
        valid = self.valid(monkeypatch)
        monkeypatch.setattr(sys, "stdin", io.StringIO(STDIN_TOKEN + "\n"))
        kind, args, _ = self.run([*valid, "--token-stdin"], monkeypatch)
        if self.payload_flag is not None:
            # the script reads its input from stdin unless given the input flag
            assert (kind, args) == ("exit", 2)
            assert self.payload_flag in capsys.readouterr().err
            monkeypatch.setattr(sys, "stdin", io.StringIO(STDIN_TOKEN + "\n"))
            kind, args, _ = self.run([*valid, self.payload_flag, "in.json", "--token-stdin"], monkeypatch)
        assert kind == "parsed", capsys.readouterr().err
        assert args.access_token == STDIN_TOKEN and args.access_token_source == "--token-stdin"

    def check_legacy_form(self, monkeypatch, capsys):
        valid = self.valid(monkeypatch)
        argv = self._legacy_argv(valid)
        kind, args, _ = self.run(argv, monkeypatch, env=None)
        cap = capsys.readouterr()
        if self.legacy == "refuse":
            assert (kind, args) == ("exit", 2)
            assert LEGACY_TOKEN not in cap.err + cap.out
            assert token_source.ACCESS_TOKEN_ENV in cap.err and "--token-stdin" in cap.err
        else:
            assert kind == "parsed", cap.err
            assert args.access_token == LEGACY_TOKEN and args.access_token_source == "argv (deprecated)"
            assert "deprecated" in cap.err and LEGACY_TOKEN not in cap.err + cap.out

    def check_legacy_with_stdin_is_refused(self, monkeypatch, capsys):
        valid = self.valid(monkeypatch)
        monkeypatch.setattr(sys, "stdin", io.StringIO(STDIN_TOKEN))
        argv = self._legacy_argv(valid)
        flags = [self.payload_flag, "in.json"] if self.payload_flag else []
        kind, code, _ = self.run([*argv, *flags, "--token-stdin"], monkeypatch, env=None)
        cap = capsys.readouterr()
        assert (kind, code) == ("exit", 2)
        assert LEGACY_TOKEN not in cap.err + cap.out

    def check_token_in_the_id_slot_is_refused(self, monkeypatch, capsys):
        """With the token in the environment, a token-shaped word where the id goes exits 2, unrepeated."""
        valid = self.valid(monkeypatch)
        first = next((i for i, w in enumerate(valid) if not w.startswith("-")), None)
        if first is None:
            return
        bad = [*valid[:first], LEGACY_TOKEN, *valid[first + 1:]]
        kind, code, _ = self.run(bad, monkeypatch)
        cap = capsys.readouterr()
        if self.typed_first and valid[first] != "x1":
            assert (kind, code) == ("exit", 2)
            assert LEGACY_TOKEN not in cap.err + cap.out

    def check_stray_extra_id_is_refused(self, monkeypatch, capsys):
        if self.stray_argv is None:
            return
        kind, code, _ = self.run(self.stray_argv, monkeypatch)
        cap = capsys.readouterr()
        assert (kind, code) == ("exit", 2)
        assert "deprecated" not in cap.err
