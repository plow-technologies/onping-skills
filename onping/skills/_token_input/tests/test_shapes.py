"""Offline tests for the id shapes.

Run from onping/skills:
    uv run --with pytest pytest -q _token_input/tests
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _token_input import shapes  # noqa: E402

TOKEN = "eyJhbGciOi.payload.signature"


def test_shapes_accept_ids_and_reject_a_token_shaped_word():
    assert shapes.is_int("42") and not shapes.is_int(TOKEN) and not shapes.is_int("")
    assert shapes.is_uuid("11111111-2222-3333-4444-555555555555") and not shapes.is_uuid(TOKEN)
    assert shapes.is_oid("o" + "a" * 24) and shapes.is_oid("A" * 24) and not shapes.is_oid(TOKEN)
    assert shapes.is_script_hash("A" * 43 + "=") and shapes.is_script_hash("-" + "B" * 42 + "=")
    assert not shapes.is_script_hash(TOKEN)
    assert shapes.is_iso_date("2026-10-31") and shapes.is_iso_date("2026-10-31T00:00:00Z")
    assert not shapes.is_iso_date(TOKEN)


@pytest.mark.parametrize("arg", [shapes.uuid_arg, shapes.oid_arg, shapes.script_hash_arg, shapes.iso_date_arg])
def test_type_functions_never_repeat_the_value(arg):
    with pytest.raises(argparse.ArgumentTypeError) as e:
        arg(TOKEN)
    assert TOKEN not in str(e.value)


def test_type_functions_return_a_good_value_unchanged():
    assert shapes.oid_arg("o" + "a" * 24) == "o" + "a" * 24
    assert shapes.iso_date_arg("2026-10-31") == "2026-10-31"


@pytest.mark.parametrize("form", [
    "2026-10-29T06:00:00Z", "2026-10-29T06:00:00.000Z", "2026-10-29T06:00Z", "2026-10-29T06:00:00-05:00",
    "2026-10-29T06:00:00+00:00", "2026-10-29T06:00:00+0000", "2026-10-29 06:00:00Z",
])
def test_every_date_form_the_report_server_accepts_passes_iso_date_arg(form):
    # live-checked against /tachdb/report: these pass the server's date parse (HTTP 400 otherwise)
    assert shapes.is_iso_date(form) and shapes.iso_date_arg(form) == form


@pytest.mark.parametrize("form", ["tomorrow", "10/29/2026", "1793253600", "20261029T060000Z", ""])
def test_a_word_that_is_not_a_date_is_refused_without_echo(form):
    with pytest.raises(argparse.ArgumentTypeError) as e:
        shapes.iso_date_arg(form)
    assert form not in str(e.value) or form == ""
