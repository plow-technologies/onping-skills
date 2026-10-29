"""Offline tests for logtable_template and onping-logtable-create's --column / --from.

Run: uv run --with pytest --with requests --with openpyxl pytest onping/skills/_lj_table_routes/tests
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes import logtable_template as tpl  # noqa: E402
from _lj_table_routes.pointers import EVENT_SELECTOR, Pointer  # noqa: E402

CREATE = Path(__file__).resolve().parents[2] / "onping-logtable-create" / "scripts" / "create_logtable.py"
NEW_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


# ------------------------------------------------------------------ --column

@pytest.mark.parametrize("text,name,ptr,sel", [
    ("Casing=500002", "Casing", Pointer("PID", 500002), "ResultTagSelector"),
    ("Mode=7 VPID", "Mode", Pointer("VPID", 7), "ResultTagSelector"),
    ("Mode = 7 VPID : unit", "Mode", Pointer("VPID", 7), "UnitTagSelector"),
    ("Seen=500002:dateTime", "Seen", Pointer("PID", 500002), "LastUpdateDateTimeTagSelector"),
    ("Seen=500002:DATETIME", "Seen", Pointer("PID", 500002), "LastUpdateDateTimeTagSelector"),
    ("Who=500002:Description", "Who", Pointer("PID", 500002), "DescriptionTagSelector"),
    ("W=500002:WriteabilityTagSelector", "W", Pointer("PID", 500002), "WriteabilityTagSelector"),
    ("a=b: c=500002:writeable", "a=b: c", Pointer("PID", 500002), "WriteabilityTagSelector"),
])
def test_column_flag_forms(text, name, ptr, sel):
    spec = tpl.parse_column_spec(text)
    assert (spec.name, spec.pointer, spec.selector, spec.event) == (name, ptr, sel, False)


@pytest.mark.parametrize("text,needle", [
    ("Casing", "expected NAME=SOURCE[:TAG]"),
    ("=500002", "name is empty"),
    ("Casing=TODO", "is not '<n>' (a PID) or '<n> VPID'"),
    ("Casing=500002 vpid", "is not '<n>'"),
    ("Casing=-5", "is not '<n>'"),
    ("Casing=500002:bogus", "unknown tag 'bogus'"),
    ("Casing=500002:text", "cannot hold a 'text' column"),
    ("Casing=500002:invalid", "cannot hold a 'invalid' column"),
])
def test_column_flag_refusals(text, needle):
    with pytest.raises(ValueError, match="--column") as e:
        tpl.parse_column_spec(text)
    assert needle in str(e.value)


# ------------------------------------------------------------------ build_schema

def _cols(sch):
    return [(c["position"], c["name"], c["key"], c["selector"], c["event"]) for c in lt.columns(sch)]


def test_build_schema_keeps_order_and_is_valid():
    specs = [tpl.event_spec(600001), tpl.parse_column_spec("Casing=600002"),
             tpl.parse_column_spec("Mode=7 VPID:unit")]
    sch, cids = tpl.build_schema(specs)
    assert lt.validate_schema(sch) == []
    assert sch["logSchemaVersion"] == 1
    assert sch["logSchemaHeader"]["schemaHeaderEventSource"] == 600001
    assert _cols(sch) == [
        (0, "eventDateTime", Pointer("PID", 600001), EVENT_SELECTOR, True),
        (1, "Casing", Pointer("PID", 600002), "ResultTagSelector", False),
        (2, "Mode", Pointer("VPID", 7), "UnitTagSelector", False),
    ]
    assert cids == [c["id"] for c in lt.columns(sch)]


def test_build_schema_places_the_event_column_at_its_file_index():
    specs = [tpl.parse_column_spec("A=1"), tpl.parse_column_spec("B=2"),
             tpl.event_spec(600001, "when"), tpl.parse_column_spec("C=3")]
    sch, cids = tpl.build_schema(specs)
    assert [c[1] for c in _cols(sch)] == ["A", "B", "when", "C"]
    assert [c[4] for c in _cols(sch)] == [False, False, True, False]
    assert cids == [c["id"] for c in lt.columns(sch)]
    assert lt.validate_schema(sch) == []


@pytest.mark.parametrize("extra,needle", [
    ("eventDateTime=5", "already exists"),             # same name as the event column
    ("Again=600001:dateTime", "already exists"),       # same key and selector as the event column
])
def test_build_schema_refuses_duplicates(extra, needle):
    with pytest.raises(ValueError, match=needle):
        tpl.build_schema([tpl.event_spec(600001), tpl.parse_column_spec(extra)])


def test_build_schema_needs_one_pid_event_column():
    with pytest.raises(ValueError, match="exactly one event column"):
        tpl.build_schema([tpl.parse_column_spec("A=1")])
    bad = tpl.ColumnSpec("e", Pointer("VPID", 1), EVENT_SELECTOR, event=True)
    with pytest.raises(ValueError, match="LastUpdateDateTime of a PID"):
        tpl.build_schema([bad])


def test_build_schema_body_round_trips_through_the_create_helpers():
    sch, _ = tpl.build_schema([tpl.event_spec(600001), tpl.parse_column_spec("A=600002")])
    created = {**lt.create_body(9999, "New", fx.GROUP), "logTableSourceId": NEW_ID}
    body = lt.first_version_body(created, sch)
    assert body["logTableSourceSchemaVersion"] == 1
    assert lt.upgrade_mismatches(body, copy.deepcopy(body)) == []


# ------------------------------------------------------------------ export header

EXPORT_ROWS = [
    ["event", None, None, None],
    ["name: eventDateTime", "name: Casing PSI", "name: Mode", "name: Unit of casing"],
    ["tag: dateTime", "tag: result", "tag: result", "tag: unit"],
    ["source: 600001", "source: 600002", "source: 7 VPID", "source: 600002"],
]


def _xlsx(tmp_path, rows, *, sheet="Sheet1", name="t.xlsx"):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    path = tmp_path / name
    wb.save(path)
    return path


def test_read_header_round_trips_an_export(tmp_path):
    h = tpl.read_header(_xlsx(tmp_path, EXPORT_ROWS))
    assert h.sheet == "Sheet1" and h.data_rows == 0 and h.notes == []
    assert [(c.name, c.pointer, c.selector, c.event) for c in h.columns] == [
        ("eventDateTime", Pointer("PID", 600001), EVENT_SELECTOR, True),
        ("Casing PSI", Pointer("PID", 600002), "ResultTagSelector", False),
        ("Mode", Pointer("VPID", 7), "ResultTagSelector", False),
        ("Unit of casing", Pointer("PID", 600002), "UnitTagSelector", False),
    ]
    assert h.event.pointer == Pointer("PID", 600001)
    sch, cids = tpl.build_schema(h.columns)
    assert len(cids) == 4 and lt.validate_schema(sch) == []


def test_read_header_counts_and_ignores_data_rows(tmp_path):
    rows = EXPORT_ROWS + [["2026-10-01 00:00:00", 1.5, 2, "psi"], [None, None, None, None],
                          ["2026-10-01 00:01:00", 1.6, 2, "psi"]]
    h = tpl.read_header(_xlsx(tmp_path, rows))
    assert h.data_rows == 2
    assert any("2 data row(s)" in n and "ignored" in n for n in h.notes)
    assert len(h.columns) == 4


def test_read_header_takes_the_event_column_anywhere(tmp_path):
    rows = [[None, " event "], ["name: A", "name: when"], ["tag: result", "tag: dateTime"],
            ["source: 1", "source: 600001"]]
    h = tpl.read_header(_xlsx(tmp_path, rows))
    assert [c.event for c in h.columns] == [False, True]
    sch, _ = tpl.build_schema(h.columns)
    assert [c[1] for c in _cols(sch)] == ["A", "when"]


def test_read_header_uses_the_first_sheet_without_sheet1(tmp_path):
    h = tpl.read_header(_xlsx(tmp_path, EXPORT_ROWS, sheet="Export"))
    assert h.sheet == "Export" and any("no 'Sheet1'" in n for n in h.notes)


@pytest.mark.parametrize("edit,needle", [
    (lambda r: r[0].__setitem__(0, None), "no column is marked 'event'"),
    (lambda r: r[0].__setitem__(1, "event"), "marks 2 columns 'event' (C1, C2)"),
    (lambda r: r[3].__setitem__(0, "source: 600001 VPID"), "R4C1: the column marked 'event' must have a PID"),
    (lambda r: r[2].__setitem__(0, "tag: result"), "R3C1: the column marked 'event' must have 'tag: dateTime'"),
    (lambda r: r[1].__setitem__(1, "label: Casing"), "R2C2: expected key 'name' but found 'label'"),
    (lambda r: r[1].__setitem__(1, "name: Casing: PSI"), "R2C2: expected exactly one ':'"),
    (lambda r: r[1].__setitem__(1, "name: Casing: PSI"), "cannot contain ':'"),
    (lambda r: r[2].__setitem__(1, None), "R3C2: missing cell"),
    (lambda r: r[2].__setitem__(1, "tag: average"), "R3C2: unknown tag selector 'average'"),
    (lambda r: r[2].__setitem__(1, "tag: Result"), "case-sensitive: use 'result'"),
    (lambda r: r[2].__setitem__(1, "tag: text"), "R3C2: a log table cannot hold a 'text' column"),
    (lambda r: r[3].__setitem__(2, "source: TODO"), "R4C3: invalid source 'TODO'"),
    (lambda r: r[3].__setitem__(2, 7), "R4C3: expected the text 'source: <value>'"),
    (lambda r: r[1].__setitem__(2, "name:"), "R2C3: the column name is empty"),
])
def test_read_header_refusals_name_the_cell(tmp_path, edit, needle):
    rows = copy.deepcopy(EXPORT_ROWS)
    edit(rows)
    with pytest.raises(ValueError, match="header is invalid") as e:
        tpl.read_header(_xlsx(tmp_path, rows))
    assert needle in str(e.value)


def test_read_header_reports_every_problem_at_once():
    rows = copy.deepcopy(EXPORT_ROWS)
    rows[2][1] = "tag: average"
    rows[3][2] = "source: TODO"
    with pytest.raises(ValueError) as e:
        tpl.parse_header_rows(rows)
    assert "R3C2" in str(e.value) and "R4C3" in str(e.value)


def test_read_header_refuses_an_empty_or_unreadable_file(tmp_path):
    pytest.importorskip("openpyxl")
    with pytest.raises(ValueError, match="rows 1-4 are empty"):
        tpl.parse_header_rows([])
    bad = tmp_path / "not.xlsx"
    bad.write_text("hello")
    with pytest.raises(ValueError, match="not a readable XLSX"):
        tpl.read_header(bad)
    with pytest.raises(ValueError, match="cannot read"):
        tpl.read_header(tmp_path / "missing.xlsx")


def test_read_header_then_duplicate_names_are_refused_by_build(tmp_path):
    rows = copy.deepcopy(EXPORT_ROWS)
    rows[1][2] = "name: Casing PSI"
    h = tpl.read_header(_xlsx(tmp_path, rows))
    with pytest.raises(ValueError, match="column 3 .*already exists"):
        tpl.build_schema(h.columns)


# ------------------------------------------------------------------ the create script

@pytest.fixture()
def create(monkeypatch):
    spec = importlib.util.spec_from_file_location("create_logtable_under_test", CREATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = {"list": 0, "post": [], "upgrade": []}
    store = {}

    def list_sources(token, lj):
        calls["list"] += 1
        return [s for s in store.values()]

    def post_json(token, route, body, **kw):
        calls["post"].append((route, body))
        assert route == "logtable_create"
        store[NEW_ID] = {**copy.deepcopy(body), "logTableSourceId": NEW_ID}
        return NEW_ID

    def find_source(token, lj, table_id):
        return copy.deepcopy(store[table_id])

    def post_upgrade(token, body):
        calls["upgrade"].append(body)
        store[body["logTableSourceId"]] = copy.deepcopy(body)
        return body

    monkeypatch.setattr(mod.lt, "list_sources", list_sources)
    monkeypatch.setattr(mod.lt, "find_source", find_source)
    monkeypatch.setattr(mod.lt, "post_upgrade", post_upgrade)
    monkeypatch.setattr(mod, "post_json", post_json)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["create_logtable.py", "TOKEN", "9999", *argv])
        try:
            mod.main()
        except SystemExit as e:
            return e.code
        return 0

    mod.run, mod.calls, mod.store = run, calls, store
    return mod


def test_create_preview_with_columns_posts_nothing(create, capsys):
    code = create.run("--name", "zz", "--group", fx.GROUP, "--event-pid", "600001",
                      "--column", "Casing=600002", "--column", "Tubing=600003",
                      "--column", "Mode=7 VPID")
    out = capsys.readouterr().out
    assert code == 0
    assert create.calls["post"] == [] and create.calls["upgrade"] == []
    assert "Schema version 1 (4 column(s))" in out
    assert out.count("<-- new") == 4
    assert "nothing was posted" in out


def test_create_applied_sends_every_column_in_version_1(create, capsys):
    code = create.run("--name", "zz", "--group", fx.GROUP, "--event-pid", "600001",
                      "--column", "Casing=600002", "--column", "Mode=7 VPID:unit", "--yes")
    out = capsys.readouterr().out
    assert code == 0, out
    assert len(create.calls["post"]) == 1 and len(create.calls["upgrade"]) == 1
    body = create.calls["upgrade"][0]
    assert body["logTableSourceSchemaVersion"] == 1
    assert [c["name"] for c in lt.columns(lt.schema(body))] == ["eventDateTime", "Casing", "Mode"]
    assert f"Read-back matches (3 column(s) at version 1). New log table: LJ 9999 {NEW_ID}" in out


def test_create_from_file_with_extra_column(create, capsys, tmp_path):
    rows = EXPORT_ROWS + [["2026-10-01 00:00:00", 1, 2, "psi"]]
    path = _xlsx(tmp_path, rows)
    code = create.run("--name", "zz", "--group", fx.GROUP, "--from", str(path),
                      "--column", "Extra=600009", "--yes")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "1 data row(s) from row 5 on are ignored" in out
    body = create.calls["upgrade"][0]
    names = [c["name"] for c in lt.columns(lt.schema(body))]
    assert names == ["eventDateTime", "Casing PSI", "Mode", "Unit of casing", "Extra"]
    assert lt.schema(body)["logSchemaHeader"]["schemaHeaderEventSource"] == 600001


@pytest.mark.parametrize("argv", [
    ("--from", "x.xlsx", "--event-pid", "1"),
    ("--from", "x.xlsx", "--event-name", "when"),
    (),
])
def test_create_event_flag_rules_exit_2(create, capsys, argv):
    assert create.run("--name", "zz", "--group", fx.GROUP, *argv) == 2
    assert create.calls["list"] == 0


def test_create_bad_column_fails_before_any_request(create, capsys):
    code = create.run("--name", "zz", "--event-pid", "600001", "--column", "Casing=TODO")
    assert code == 1
    assert "is not '<n>' (a PID)" in capsys.readouterr().err
    assert create.calls["list"] == 0


def test_create_still_lists_groups_and_refuses_a_used_name(create, capsys):
    create.store["x"] = {**lt.create_body(9999, "Taken", fx.GROUP), "logTableSourceId": "x"}
    assert create.run("--name", "zz", "--event-pid", "600001") == 2
    assert fx.GROUP in capsys.readouterr().err
    assert create.run("--name", "Taken", "--group", fx.GROUP, "--event-pid", "600001") == 1
    assert "already has a log table named 'Taken'" in capsys.readouterr().err
