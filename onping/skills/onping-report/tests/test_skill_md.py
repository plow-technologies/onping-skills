"""SKILL.md and the two skill indexes say what the server really does.

Absent phrases are the exact false claims of the old text, not bare words, so a sentence that denies
a claim passes. The forbidden phrases are built from two pieces below, so this file does not itself
contain them as one string.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import SKILL_MD

REPO = Path(__file__).resolve().parents[4]
ONPING_INDEX = REPO / "onping" / "skills" / "SKILLS.md"
ROOT_INDEX = REPO / "SKILLS.md"

TEXT = SKILL_MD.read_text()
FALSE_CLAIMS = [
    "pre-signed" + " S3 download URL",
    "(no auth" + " needed)",
    "typically a pre-signed" + " S3 URL",
]
INDEX_CLAIMS = ["pre-signed" + " download URL", "pre-signed" + " S3"]


def front_matter(text: str) -> dict:
    block = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
    return dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)


def arguments_table_rows(text: str) -> list[str]:
    section = re.search(r"(?ms)^## Arguments\n(.*?)^## ", text).group(1)
    return [ln for ln in section.splitlines() if ln.startswith("|")]


# ---- absence ----------------------------------------------------------------------------------

@pytest.mark.parametrize("claim", FALSE_CLAIMS)
def test_the_false_claims_are_gone(claim):
    assert claim not in TEXT


def test_arguments_table_has_no_access_token_row():
    rows = arguments_table_rows(TEXT)
    assert rows, "no Arguments table"
    assert not [r for r in rows if re.match(r"\|\s*`?ACCESS_TOKEN`?\s*\|", r)]


def test_a_denying_sentence_is_allowed():
    assert "It is not a pre-signed" in TEXT  # the denial stays; only the claims are forbidden
    assert not any(c in "It is not a pre-signed S3 URL." for c in FALSE_CLAIMS)


def test_bearer_acceptance_on_the_route_is_left_open():
    # no claim either way until a live check has recorded the answer
    assert "has not been checked" in TEXT
    low = TEXT.lower()
    for claim in ("does not accept a bearer", "bearer token is accepted", "bearer token is rejected"):
        assert claim not in low


# ---- presence ---------------------------------------------------------------------------------

def test_description_names_both_formats():
    d = front_matter(TEXT)["description"].lower()
    assert "csv" in d and "xlsx" in d


def test_heading_usage_and_option_table_name_both_formats():
    assert re.search(r"(?m)^# .*", TEXT)
    intro = TEXT.split("## Usage")[0].lower()
    assert "csv" in intro and "xlsx" in intro
    assert "[--format csv|xlsx]" in TEXT
    assert re.search(r"(?m)^\| `--format` \| csv \|", TEXT)


def test_names_the_onping_route_and_owner_only_access():
    assert "/s3/availableFile/<user>/<date>/<file>" in TEXT
    assert "logged-in user who owns the file" in TEXT


def test_three_attempts_in_total():
    assert "3 attempts in total" in TEXT


def test_timeout_is_the_limit_of_the_request_not_of_generation():
    assert "limit of the request" in TEXT


def test_states_asynchronous_generation_and_its_consequences():
    assert "asynchronous" in TEXT or "after it answers" in TEXT
    assert "Failed to find Report, it may still be generating" in TEXT
    assert "HTTP 200 with an HTML page" in TEXT
    assert "A failed generation still leaves a URL" in TEXT
    assert "text/csv" in TEXT and "`PK`" in TEXT


def test_states_the_time_zone():
    assert "America/Chicago" in TEXT
    assert "UTC" in TEXT
    assert "no offset is written" in TEXT
    assert "cannot be chosen" in TEXT
    assert "duplicate timestamps" in TEXT
    dup = next(ln for ln in TEXT.splitlines() if "duplicate timestamps" in ln)
    assert "nferred" in dup  # marked as inferred


def test_states_the_known_limits():
    assert "does not quote or escape csv cells" in TEXT
    assert re.search(r"csv text value that starts with `=`, `\+`, `-` or `@`", TEXT)
    assert "1,048,576" in TEXT
    assert "dropped by the server without a message" in TEXT
    bom = next(ln for ln in TEXT.splitlines() if "byte-order mark" in ln)
    assert "nferred" in bom
    cap = next(ln for ln in TEXT.splitlines() if "1,048,576" in ln)
    assert "inferred" in cap


def test_does_not_document_a_download_option():
    # --output / --wait are a separate, gated change; the skill must not advertise them yet
    assert "--output" not in TEXT and "--wait" not in TEXT


# ---- indexes ----------------------------------------------------------------------------------

def _onping_entry() -> str:
    text = ONPING_INDEX.read_text()
    return re.search(r"(?ms)^#### onping-report\n(.*?)(?=^#{1,4} )", text).group(1)


def _root_line() -> str:
    return next(ln for ln in ROOT_INDEX.read_text().splitlines() if ln.startswith("- **onping-report**"))


@pytest.mark.skipif(not (ONPING_INDEX.exists() and ROOT_INDEX.exists()), reason="index files are not in this checkout")
@pytest.mark.parametrize("get_entry", [_onping_entry, _root_line], ids=["onping-index", "root-index"])
def test_indexes_name_both_formats_and_drop_the_presigned_claim(get_entry):
    entry = get_entry()
    low = entry.lower()
    assert "csv" in low and "xlsx" in low
    assert "--format" in entry
    for claim in INDEX_CLAIMS:
        assert claim not in entry


@pytest.mark.skipif(not ONPING_INDEX.exists(), reason="index file is not in this checkout")
def test_onping_index_matches_the_skill_md_defaults():
    entry = _onping_entry()
    assert "/s3/availableFile/" in entry
    assert "Report" in entry and "CSV Report" in entry
