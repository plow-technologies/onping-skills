"""Id shapes for the first-word guard and for argparse `type=` checks.

An access token is a dotted string, so none of these shapes can match one. `is_*` take the first
word for `token_source.parse(is_id=...)`. The `*_arg` functions are argparse `type=` callables that
check the shape and return the value unchanged; their errors never repeat the value, so a token
typed in an id slot cannot reach a URL, a query parameter or a usage message.
"""

from __future__ import annotations

import argparse
import re

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_OID = re.compile(r"o?[0-9a-fA-F]{24}")
_HASH = re.compile(r"[A-Za-z0-9_-]{43}=")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}([T ].*)?")


def is_int(word: str) -> bool:
    return word.isascii() and word.isdigit()


def is_uuid(word: str) -> bool:
    return _UUID.fullmatch(word) is not None


def is_oid(word: str) -> bool:
    return _OID.fullmatch(word) is not None


def is_script_hash(word: str) -> bool:
    return _HASH.fullmatch(word) is not None


def is_iso_date(word: str) -> bool:
    return _DATE.fullmatch(word) is not None


def _checker(test, what: str):
    def check(value: str) -> str:
        if not test(value):
            raise argparse.ArgumentTypeError(what)
        return value

    return check


def int_arg(value: str) -> int:
    """An id, serial or PID: ASCII digits only, so `-5`, `1_000`, ` 7` and non-ASCII digits are refused."""
    if not is_int(value):
        raise argparse.ArgumentTypeError("must be a whole number written with the digits 0-9")
    return int(value)


uuid_arg = _checker(is_uuid, "must be a UUID (8-4-4-4-12 hex digits)")
oid_arg = _checker(is_oid, "must be a Mongo object id (24 hex digits, optionally o-prefixed)")
script_hash_arg = _checker(is_script_hash, "must be a script hash (43 URL-safe base64 characters and '=')")
iso_date_arg = _checker(is_iso_date, "must be an ISO 8601 date (YYYY-MM-DD, optionally followed by a time)")
