"""Post-parse smoke tests: each family's main() runs with HTTP faked and the real typed arguments.

The token-contract tests stop at the parse. These keep going, so a typed id (now an int) that meets
`str.replace`, a string join or a helper signature fails here rather than in front of a user.

Run from onping/skills:  uv run --with pytest --with requests pytest -q _token_input/tests
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from _token_input.smoke import TOKEN, run_main  # noqa: E402

XLSX = b"PK\x03\x04 synthetic workbook"
EXPORT_SCRIPTS = sorted(glob.glob(str(ROOT / "onping-export-*" / "scripts" / "export_tags.py")))
UPDATE_SCRIPTS = sorted(glob.glob(str(ROOT / "onping-update-*" / "scripts" / "update_location.py")))


def _ok(res):
    assert res.exc is None, f"crashed after the parse: {res.exc!r}"


def test_the_export_family_is_all_twelve():
    assert len(EXPORT_SCRIPTS) == 12


@pytest.mark.parametrize("script", EXPORT_SCRIPTS, ids=lambda p: Path(p).parents[1].name)
@pytest.mark.parametrize("ident", ["1234", "0"])
def test_export_tags_builds_the_path_from_an_int_id(script, ident, monkeypatch, tmp_path):
    out = tmp_path / "tags.xlsx"
    res = run_main(script, [ident, "--output", str(out)], monkeypatch, responder=lambda m, u, kw: XLSX)
    _ok(res)
    assert res.code in (None, 0)
    assert res.calls and f"/{ident}/" in res.calls[0].url
    assert "{" not in res.calls[0].url
    assert out.read_bytes() == XLSX
    assert res.calls[0].kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("script", EXPORT_SCRIPTS, ids=lambda p: Path(p).parents[1].name)
def test_export_tags_default_output_name_carries_the_id(script, monkeypatch, tmp_path):
    res = run_main(script, ["77"], monkeypatch, responder=lambda m, u, kw: XLSX, cwd=tmp_path)
    _ok(res)
    assert any("-77-" in p.name for p in tmp_path.iterdir())


@pytest.mark.parametrize(
    "skill, script, argv, needle",
    [
        ("onping-logtable-list", "list_logtables.py", ["1234"], "/1234/"),
        ("onping-logtable-get", "get_logtable.py", ["1234", "11111111-2222-3333-4444-555555555555"], "/1234/"),
        ("onping-logtable-fetch", "fetch_logtable.py", ["1234", "11111111-2222-3333-4444-555555555555"], "/1234/"),
        ("onping-logtable-delete", "delete_logtable.py", ["1234", "11111111-2222-3333-4444-555555555555", "--dry-run"], "/1234/"),
        ("onping-datatable-list", "list_datatables.py", ["1234"], "/1234/"),
        ("onping-datatable-get", "get_datatable.py", ["1234", "11111111-2222-3333-4444-555555555555"], "/1234/"),
        ("onping-datatable-fetch", "fetch_datatable.py", ["1234", "11111111-2222-3333-4444-555555555555"], "/1234/"),
        ("onping-logtable-list", "list_logtables.py", ["1234", "--references-pid", "500001"], "/1234/"),
    ],
)
def test_table_family_reaches_the_server_with_the_int_serial(skill, script, argv, needle, monkeypatch, tmp_path):
    res = run_main(ROOT / skill / "scripts" / script, argv, monkeypatch, responder=lambda m, u, kw: [], cwd=tmp_path)
    _ok(res)
    assert res.calls and needle in res.calls[0].url


@pytest.mark.parametrize("script", UPDATE_SCRIPTS, ids=lambda p: Path(p).parents[1].name)
def test_update_family_fetches_the_int_ref_id(script, monkeypatch, tmp_path):
    res = run_main(script, ["4321", "--dry-run"], monkeypatch, responder=lambda m, u, kw: {}, cwd=tmp_path)
    _ok(res)


@pytest.mark.parametrize(
    "skill, script, argv, needle",
    [
        ("onping-sites", "fetch_sites.py", ["12"], "12"),
        ("onping-locations", "fetch_locations.py", ["12", "13"], "13"),
        ("onping-parameters", "fetch_parameters.py", ["5", "6"], "5"),
        ("lj-profile", "lj_profile.py", ["20004"], "20004"),
        ("cp-list", "list_control_parameters.py", ["3484"], "3484"),
        ("vp-show", "show_vp.py", ["99"], "/99"),
        ("classic-cp-list", "list_classic_cps.py", ["19"], "19"),
        ("onping-mqtt-integrator-rules-export", "export_rules.py", ["3484", "--json"], "/3484/"),
        ("onping-mqtt-integrator-reports", "reports.py", ["3484"], "/3484/"),
        ("onping-mqtt-integrator-unprocessed", "unprocessed.py", ["3484"], "/3484/"),
        ("onping-driver-resolve", "resolve_driver.py", ["20006", "--json"], "20006"),
    ],
)
def test_reader_family_runs_past_the_parse(skill, script, argv, needle, monkeypatch, tmp_path):
    res = run_main(ROOT / skill / "scripts" / script, argv, monkeypatch, responder=lambda m, u, kw: [], cwd=tmp_path)
    _ok(res)
    assert res.calls, "no request was made"
    assert any(needle in f"{c.url} {c.kwargs}" for c in res.calls)


def test_report_sends_int_pids_and_the_dates_as_given(monkeypatch, tmp_path):
    seen = {}

    def responder(m, u, kw):
        seen.update(kw.get("json") or {})
        return {"url": "https://example.invalid/r.csv"}

    res = run_main(ROOT / "onping-report" / "scripts" / "generate_report.py",
                   ["2026-02-22T06:00:00Z", "2026-02-25T06:00:00Z", "500001", "500002"], monkeypatch,
                   responder=responder, cwd=tmp_path)
    _ok(res)
    assert seen["pidList"] == [500001, 500002]
    assert seen["startDate"] == "2026-02-22T06:00:00Z"


def test_report_vpid_keys_are_ints(monkeypatch, tmp_path):
    seen = {}

    def responder(m, u, kw):
        seen.update(kw.get("json") or {})
        return {}

    res = run_main(ROOT / "onping-report" / "scripts" / "generate_report.py",
                   ["2026-02-22T06:00:00Z", "2026-02-25T06:00:00Z", "7", "--vpid"], monkeypatch,
                   responder=responder, cwd=tmp_path)
    _ok(res)
    assert seen["pidList"] == [{"keyType": "VPID", "keyValue": 7}]


LOCATE = ROOT / "onping-pid-locate" / "scripts" / "locate_pid.py"


def test_pid_locate_runs_past_the_parse_with_int_pids(monkeypatch, tmp_path):
    res = run_main(LOCATE, ["500001", "500002", "500001", "--json"], monkeypatch, responder=lambda m, u, kw: [], cwd=tmp_path)
    _ok(res)
    assert res.calls
    assert res.calls[0].kwargs["json"] == [500001, 500002] or "500001" in str(res.calls[0].kwargs)


@pytest.mark.parametrize("bad", ["-5", "12_000", "٣", "+7", " 7", "1.5", "0x10"])
def test_pid_locate_refuses_a_malformed_pid_before_any_request(bad, monkeypatch, tmp_path, capsys):
    res = run_main(LOCATE, [bad], monkeypatch, cwd=tmp_path)
    assert res.exc is None and res.code == 2
    assert not res.calls
    assert bad not in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["-5", "12_000", "٣"])
def test_parameters_and_report_refuse_a_malformed_id(bad, monkeypatch, tmp_path):
    for skill, script, argv in [
        ("onping-parameters", "fetch_parameters.py", [bad]),
        ("onping-report", "generate_report.py", ["2026-02-22", "2026-02-23", bad]),
        ("vp-show", "show_vp.py", [bad]),
    ]:
        res = run_main(ROOT / skill / "scripts" / script, argv, monkeypatch, cwd=tmp_path)
        assert res.exc is None and res.code == 2 and not res.calls, skill


SEARCH = ROOT / "onping-search" / "scripts" / "search.py"


@pytest.mark.parametrize("argv", [["pump trip", "extra"], ["pump trip", "--size", "5", "extra"], ["pump", "extra"]])
def test_search_never_sends_a_query_as_the_bearer(argv, monkeypatch, tmp_path):
    res = run_main(SEARCH, argv, monkeypatch, cwd=tmp_path)
    assert res.exc is None and res.code == 2 and not res.calls


def test_search_with_a_spaced_query_and_no_token_gets_the_hint_and_sends_nothing(monkeypatch, tmp_path, capsys):
    res = run_main(SEARCH, ["pump trip", "--size", "5"], monkeypatch, cwd=tmp_path, env_token=None)
    assert res.exc is None and res.code == 2 and not res.calls
    assert "--token-stdin" in capsys.readouterr().err
