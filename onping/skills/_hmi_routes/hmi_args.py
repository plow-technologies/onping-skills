"""Command-line parsing shared by the onping-hmi-* skills: the token source and the HMI UUID check.

`parse(p, argv)` replaces `p.parse_args(argv)`. The token comes from `$ONPING_ACCESS_TOKEN` or
`--token-stdin` (see `_token_input.token_source`). A UUID-shaped first word is never read as a
legacy token. `uuid=True` also requires the `uuid` positional to be UUID-shaped, so a token given
in its slot is refused before it can be put in a URL.
"""

from __future__ import annotations

import argparse
import re

from _token_input import token_source

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def is_hmi_uuid(word: str) -> bool:
    return _UUID_RE.fullmatch(word) is not None


def parse(
    p: argparse.ArgumentParser,
    argv: list[str] | None,
    *,
    uuid: bool = False,
    reads_stdin: bool = False,
) -> argparse.Namespace:
    """`uuid`: the script has a `uuid` positional. `reads_stdin`: it reads its input from stdin without --input."""
    args = token_source.parse(
        p,
        argv,
        is_id=is_hmi_uuid,
        stdin_busy=(lambda a: not a.input) if reads_stdin else None,
    )
    if uuid and not is_hmi_uuid(args.uuid):
        p.error("uuid must be an HMI UUID (8-4-4-4-12 hex digits); use onping-hmi-list to find one")
    return args
