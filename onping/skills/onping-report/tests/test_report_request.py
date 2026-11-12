"""Request body of onping-report per format.

The csv golden strings were recorded from generate_report.py as it was on main before --format
was added (json.dumps of the body, default key order). A csv request must stay byte-identical.

Run from the repository root:
    uv run --with pytest --with requests pytest onping/skills/onping-report/tests
"""

from __future__ import annotations

import json

import pytest

from conftest import END, START, ok

BASE = [START, END, "500019", "500020"]

GOLDEN_DEFAULT = (
    '{"title": "CSV Report", "step": 60, "resolution": 8, "startDate": "2026-02-22T06:00:00Z", '
    '"endDate": "2026-02-25T06:00:00Z", "pidList": [500019, 500020]}'
)
GOLDEN_VPID = (
    '{"title": "CSV Report", "step": 60, "resolution": 8, "startDate": "2026-02-22T06:00:00Z", '
    '"endDate": "2026-02-25T06:00:00Z", "pidList": [{"keyType": "VPID", "keyValue": 500019}, '
    '{"keyType": "VPID", "keyValue": 500020}]}'
)
GOLDEN_TITLE = (
    '{"title": "Wells", "step": 60, "resolution": 8, "startDate": "2026-02-22T06:00:00Z", '
    '"endDate": "2026-02-25T06:00:00Z", "pidList": [500019, 500020]}'
)
GOLDEN_STEP = (
    '{"title": "CSV Report", "step": 3600, "resolution": 4, "startDate": "2026-02-22T06:00:00Z", '
    '"endDate": "2026-02-25T06:00:00Z", "pidList": [500019, 500020]}'
)
CSV_KEYS = ["title", "step", "resolution", "startDate", "endDate", "pidList"]


def body_of(run, extra):
    r = run([*BASE, *extra], [ok()])
    assert r.code == 0 and len(r.calls) == 1
    return r.calls[0]["json"]


@pytest.mark.parametrize(
    "extra, golden",
    [
        ([], GOLDEN_DEFAULT),
        (["--format", "csv"], GOLDEN_DEFAULT),
        (["--vpid"], GOLDEN_VPID),
        (["--vpid", "--format", "csv"], GOLDEN_VPID),
        (["--title", "Wells"], GOLDEN_TITLE),
        (["--title", "Wells", "--format", "csv"], GOLDEN_TITLE),
        (["--step", "3600", "--resolution", "4"], GOLDEN_STEP),
    ],
)
def test_csv_body_equals_the_golden_string(run, extra, golden):
    assert json.dumps(body_of(run, extra)) == golden


def test_csv_body_has_no_format_key_and_the_keys_in_order(run):
    for extra in ([], ["--format", "csv"]):
        body = body_of(run, extra)
        assert list(body) == CSV_KEYS
        assert "format" not in body


def test_xlsx_body_adds_format_after_pidlist_and_changes_the_default_title(run):
    body = body_of(run, ["--format", "xlsx"])
    assert list(body) == [*CSV_KEYS, "format"]
    assert body["format"] == "xlsx"
    assert body["title"] == "Report"
    assert {k: v for k, v in body.items() if k not in ("format", "title")} == {
        k: v for k, v in json.loads(GOLDEN_DEFAULT).items() if k != "title"
    }


def test_xlsx_with_an_explicit_title_sends_it_unchanged(run):
    assert body_of(run, ["--format", "xlsx", "--title", "Wells"])["title"] == "Wells"
    assert body_of(run, ["--format", "csv", "--title", "Wells"])["title"] == "Wells"


def test_xlsx_vpid_pid_list_keeps_the_csv_shape(run):
    body = body_of(run, ["--format", "xlsx", "--vpid"])
    assert body["pidList"] == [{"keyType": "VPID", "keyValue": 500019}, {"keyType": "VPID", "keyValue": 500020}]


@pytest.mark.parametrize("extra", [[], ["--format", "csv"], ["--format", "xlsx"], ["--format", "xlsx", "--title", "T"]])
def test_no_header_or_report_options_key_under_any_option(run, extra):
    body = body_of(run, extra)
    assert "header" not in body and "reportOptions" not in body


def test_unknown_format_exits_2_and_sends_nothing(run):
    r = run([*BASE, "--format", "pdf"])
    assert r.code == 2
    assert r.calls == []
    assert "--format" in r.err and "pdf" in r.err
    assert r.out == ""


def test_formats_are_case_sensitive_and_xlsm_is_refused(run):
    for bad in ("XLSX", "xlsm", ""):
        r = run([*BASE, "--format", bad])
        assert r.code == 2 and r.calls == []
