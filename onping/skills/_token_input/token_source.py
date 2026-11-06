"""Where an OnPing skill gets the access token.

The token never goes on argv, where `ps` shows it to every local user. It comes from
`$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin`. A token as the first command-line
word still works for now: it is deprecated and warns. The convention is the one
`ml-model-cost-sweep` set (htmlspec change move-cost-sweep-token-off-argv).

`parse(p, argv)` replaces `p.parse_args(argv)` in a skill script. The parser declares no token
argument. The returned namespace has `access_token` set, which the script reads, and
`access_token_source` (a name, never the value). Every usage failure is `p.error`, exit 2,
before any request. No message ever carries the token.

Hooks and options let a family of skills tune the parse without a copy of this module:

- `is_id(word)`: a first word for which it is true is an id of this family, never a legacy
  token, so a stray extra word cannot retarget a write by turning the real id into a "token".
- `stdin_busy(args)`: true when the script itself reads its input from stdin. `--token-stdin`
  then needs another source for that input, and the script says so with a usage error.
- `subcommands`: subcommand names whose old form was `script SUBCOMMAND TOKEN ...`. When the first
  word is one of them, the legacy candidate is the second word, and `is_id` is applied to that word.
  A subcommand outside the set never took a token and still needs none (`access_token` is None).
- `legacy="refuse"`: for a write or delete script whose first word cannot be told from a token by
  shape. A line that parses only without its first word exits 2 with a message that names the two
  supported token sources and never repeats the word. Nothing is sent.
- A failed parse is retried as the legacy form only when the first word (or the one after the subcommand)
  is token-shaped: no whitespace, only `A-Za-z0-9_.~+/=-`, and at least 20 characters. Any other word,
  such as a search query or a short name, keeps the error of the typed parse and is never read as a token.
- `stdin_hint`: the "how to give the input another way" text of the `stdin_busy` usage error.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Collection
from typing import Any

ACCESS_TOKEN_ENV = "ONPING_ACCESS_TOKEN"
TOKEN_STDIN = "--token-stdin"
LOGIN_HINT = "<skills-dir>/onping-login/scripts/login.py"


# A token-shaped word: no whitespace, only the characters of a JWT or other base64url-style token,
# and at least this long. A real access token is a dotted JWT of several hundred characters.
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_.~+/=-]+")
MIN_TOKEN_LENGTH = 20


def looks_like_token(word: str) -> bool:
    """True for a word that could be a legacy first-argument token, so a failed parse may be retried without it."""
    return len(word) >= MIN_TOKEN_LENGTH and _TOKEN_SHAPE.fullmatch(word) is not None


class _Usage(Exception):
    pass


_UNSET = object()


def _parsers(p: argparse.ArgumentParser) -> list[argparse.ArgumentParser]:
    found = [p]
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                found.extend(_parsers(sub))
    return found


def _attempt(p: argparse.ArgumentParser, argv: list[str], intermixed: bool = False) -> argparse.Namespace:
    """p.parse_args(argv) (or parse_intermixed_args) with a usage error raised as _Usage instead of printed.

    Sub-parsers report their own errors and exit, so they are patched as well."""
    def raise_usage(message: str):
        raise _Usage(message)

    parsers = _parsers(p)
    saved = [(each, each.__dict__.get("error", _UNSET)) for each in parsers]
    try:
        for each in parsers:
            each.error = raise_usage  # type: ignore[method-assign]
        return p.parse_intermixed_args(argv) if intermixed else p.parse_args(argv)
    finally:
        for each, previous in saved:
            if previous is _UNSET:
                each.__dict__.pop("error", None)
            else:
                each.error = previous  # type: ignore[method-assign]


def _chosen_subcommand(p: argparse.ArgumentParser, args: argparse.Namespace) -> str | None:
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction) and action.dest is not argparse.SUPPRESS:
            return getattr(args, action.dest, None)
    return None


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def parse(
    p: argparse.ArgumentParser,
    argv: list[str] | None,
    environ: Any = None,
    *,
    is_id: Callable[[str], bool] | None = None,
    stdin_busy: Callable[[argparse.Namespace], bool] | None = None,
    subcommands: Collection[str] | None = None,
    legacy: str = "warn",
    stdin_hint: str = "give the input as a file with --input",
    intermixed: bool = False,
) -> argparse.Namespace:
    if legacy not in ("warn", "refuse"):
        raise ValueError(f"legacy must be 'warn' or 'refuse', got {legacy!r}")
    argv = list(sys.argv[1:] if argv is None else argv)
    if is_id is None and subcommands is None:
        # a top-level subcommand name is never a token: `script SUBCOMMAND ...` is not the old form
        names = {n for a in p._actions if isinstance(a, argparse._SubParsersAction) for n in a.choices}
        if names:
            is_id = names.__contains__
    environ = os.environ if environ is None else environ
    # parse() may run twice on one parser (a test, a wrapper): add the flag only once
    stdin_help = f"read the OnPing access token from stdin instead of ${ACCESS_TOKEN_ENV}"
    if TOKEN_STDIN not in p._option_string_actions:
        p.add_argument(TOKEN_STDIN, action="store_true", help=stdin_help)
    for sub in _parsers(p)[1:]:  # accepted after a subcommand too; absent there, the top-level value stands
        if TOKEN_STDIN not in sub._option_string_actions:
            sub.add_argument(TOKEN_STDIN, action="store_true", default=argparse.SUPPRESS, help=stdin_help)
    p.epilog = (f"The access token (see onping-login) comes from ${ACCESS_TOKEN_ENV}, or from stdin with "
                f"{TOKEN_STDIN}. A token as the first argument is "
                + ("not accepted" if legacy == "refuse" else "deprecated") + ": ps shows it.")

    legacy_word: str | None = None
    try:
        args = _attempt(p, argv, intermixed)
    except _Usage as first:
        # The old form was `script TOKEN ...`, or `script SUBCOMMAND TOKEN ...` for the subcommands
        # given. Retry without that word; if that parses, it was a token. Only a token-shaped word is tried
        # (looks_like_token), so a query or name is never sent as a bearer. A word shaped like an id of
        # this family is never read as a token, so a stray extra word cannot retarget a write.
        # Otherwise report the error as typed.
        at = 1 if subcommands and argv and argv[0] in subcommands else 0
        if len(argv) <= at:
            p.error(str(first))
        word = argv[at]
        if word.startswith("-") or not looks_like_token(word) or (is_id is not None and is_id(word)):
            p.error(str(first))
        try:
            args = _attempt(p, argv[:at] + argv[at + 1:], intermixed)
        except _Usage:
            p.error(str(first).replace(word, "<value>"))
        if legacy == "refuse":
            p.error(f"a token as a command-line argument is not accepted by this command: ps shows it. "
                    f"Export ${ACCESS_TOKEN_ENV} or pass {TOKEN_STDIN}")
        legacy_word = word

    if subcommands is not None and _chosen_subcommand(p, args) not in subcommands:
        # a subcommand that never took a token (disable-all, normalize) still needs none
        args.access_token, args.access_token_source = None, None
        return args

    if args.token_stdin:
        if legacy_word is not None:
            p.error(f"pass the access token once: {TOKEN_STDIN} and a token as the first argument were both given")
        if stdin_busy is not None and stdin_busy(args):
            p.error(f"{TOKEN_STDIN} reads the access token from stdin, which this command also needs for its "
                    f"input: {stdin_hint}")
        words = sys.stdin.read().split()
        if len(words) != 1:
            p.error(f"{TOKEN_STDIN} needs exactly one access token on stdin, got {len(words)} words")
        args.access_token, args.access_token_source = words[0], TOKEN_STDIN
    elif legacy_word is not None:
        _warn("WARNING: an access token as the first argument is deprecated: any local user can read it with ps. "
              f"Export ${ACCESS_TOKEN_ENV} or pipe it with {TOKEN_STDIN} instead.")
        args.access_token, args.access_token_source = legacy_word, "argv (deprecated)"
    else:
        token = (environ.get(ACCESS_TOKEN_ENV) or "").strip()
        if not token:
            p.error(f"no OnPing access token: ${ACCESS_TOKEN_ENV} is unset or blank and {TOKEN_STDIN} was not given. "
                    f"Run `export {ACCESS_TOKEN_ENV}=$(uv run {LOGIN_HINT})`, or pipe `uv run {LOGIN_HINT}` "
                    f"into this script with {TOKEN_STDIN}")
        args.access_token, args.access_token_source = token, f"${ACCESS_TOKEN_ENV}"
    return args
