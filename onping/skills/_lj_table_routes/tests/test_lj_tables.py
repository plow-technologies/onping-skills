"""Offline tests for the _lj_table_routes pure transforms.

Run: uv run --with pytest --with requests pytest onping/skills/_lj_table_routes/tests
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes import filters  # noqa: E402
from _lj_table_routes import logtable as lt  # noqa: E402
from _lj_table_routes import lj_http  # noqa: E402
from _lj_table_routes.pointers import (  # noqa: E402
    Pointer, from_cli, normalize_selector, parse_cell, parse_key, render_cell, render_key,
    try_parse_cell,
)
from _lj_table_routes.routes import ROUTES  # noqa: E402


# ------------------------------------------------------------------ pointers

@pytest.mark.parametrize("text,ptr", [("1234", Pointer("PID", 1234)),
                                      ("4321 VPID", Pointer("VPID", 4321)),
                                      ("0", Pointer("PID", 0))])
def test_cell_round_trip(text, ptr):
    assert parse_cell(text) == ptr
    assert render_cell(ptr) == text


@pytest.mark.parametrize("bad", ["", "TODO", "12a", " 12", "12 ", "12 vpid", "12  VPID",
                                 "-5", "+5", "12VPID", "VPID 12"])
def test_cell_rejects_what_the_server_rejects(bad):
    with pytest.raises(ValueError, match="Invalid PID or VPID format"):
        parse_cell(bad)
    assert try_parse_cell(bad) is None


@pytest.mark.parametrize("raw,ptr", [(600001, Pointer("PID", 600001)),
                                     ({"keyType": "VPID", "keyValue": 88}, Pointer("VPID", 88)),
                                     ({"keyType": "PID", "keyValue": 7}, Pointer("PID", 7))])
def test_key_round_trip(raw, ptr):
    assert parse_key(raw) == ptr
    assert parse_key(render_key(ptr)) == ptr


def test_key_rejects_bool_and_junk():
    for bad in (True, "1234", None, {"keyType": "X", "keyValue": 1}):
        with pytest.raises(ValueError):
            parse_key(bad)


def test_cell_key_cli_agree():
    for p in (Pointer("PID", 5), Pointer("VPID", 5)):
        assert parse_cell(render_cell(p)) == parse_key(render_key(p)) == p
    assert from_cli(pid=5) == Pointer("PID", 5)
    assert from_cli(vpid=5) == Pointer("VPID", 5)
    assert from_cli() is None
    with pytest.raises(ValueError):
        from_cli(pid=1, vpid=2)


def test_selector_names():
    assert normalize_selector("Result") == "ResultTagSelector"
    assert normalize_selector("lastupdatedatetime") == "LastUpdateDateTimeTagSelector"
    assert normalize_selector("PIDTagSelector") == "PIDTagSelector"
    with pytest.raises(ValueError):
        normalize_selector("Nope")


# -------------------------------------------------------------------- routes

def test_every_route_has_the_curated_fields():
    for key, r in ROUTES.items():
        method, path = r["endpoint"].split(" ", 1)
        assert method in ("GET", "POST"), key
        assert path.startswith(("/datatable/", "/logtable/")), key
        for field in ("handler", "response", "permission", "notes"):
            assert r.get(field), (key, field)
        assert ":" not in r["handler"].split("(")[0], "cite handler names, not file:line"


def test_slow_router_lists_get_a_longer_timeout():
    assert ROUTES["logtable_all"]["timeout"] >= 300
    assert ROUTES["datatable_all"]["timeout"] >= 300
    writes = [k for k, r in ROUTES.items() if k.endswith(("_update", "_upgrade", "_create", "_delete"))]
    assert writes and all("timeout" not in ROUTES[k] for k in writes), "writes keep the default"


def test_error_explanations():
    assert "OWNED" in lj_http.explain(500, "Permission Denied", "POST /x")
    assert "retry" in lj_http.explain(503, "RegenerationInProgress", "POST /x")
    assert "no routing" in lj_http.explain(404, "Routing index could not be found.\n", "GET /x")
    assert "onping-login" in lj_http.explain(401, "", "GET /x")
    assert lj_http.error_text('{"error":"boom"}') == "boom"
    assert lj_http.error_text('"bare"') == "bare"


# ----------------------------------------------------------------- datatable

def test_columns_follow_position_and_index():
    cols = dt.columns(fx.datatable())
    assert [c["name"] for c in cols] == ["Well", "Casing", "Tubing", "Updated"]
    assert [c["position"] for c in cols] == [1, 2, 3, 4]
    assert [c["index"] for c in cols] == [0, 1, 2, 3]
    assert [c["hidden"] for c in cols] == [False, False, True, False]


def test_resolve_column():
    src = fx.datatable()
    assert dt.resolve_column(src, "2")["id"] == fx.C_RES1
    assert dt.resolve_column(src, fx.C_RES2.upper())["name"] == "Tubing"
    assert dt.resolve_column(src, "tubing")["id"] == fx.C_RES2
    with pytest.raises(ValueError):
        dt.resolve_column(src, "9")
    with pytest.raises(ValueError):
        dt.resolve_column(src, "Nope")


def test_join_rows_matches_on_row_id_not_order():
    resp = {"queryResponseContent": [{"tableRowId": 1, "tableRowValues": ["a"]},
                                     {"tableRowId": 2, "tableRowValues": ["b"]}],
            "queryResponsePointers": [{"tableRowId": 2, "tableRowValues": ["p2"]},
                                      {"tableRowId": 1, "tableRowValues": ["p1"]}],
            "queryResponseCount": 2}
    rows = dt.join_rows(resp)
    assert [(r["rowId"], r["pointers"]) for r in rows] == [(1, ["p1"]), (2, ["p2"])]


def test_query_body_clears_filters_and_order():
    src = fx.datatable()
    src["tableHeader"]["tableHeaderFilters"] = [fx.single_filter(fx.C_RES1)]
    body = dt.query_body(src)
    assert body["tableHeader"]["tableHeaderFilters"] == []
    assert body["tableHeader"]["tableHeaderColumnsOrder"] == {}
    assert body["tablePagination"] is None
    assert src["tableHeader"]["tableHeaderFilters"], "the stored source is not mutated"
    assert dt.query_body(src, limit=5, offset=10)["tablePagination"] == \
        {"tablePaginationLimit": 5, "tablePaginationOffset": 10}


def test_row_cells_and_pointer_search():
    src, rows = fx.datatable(), fx.datatable_rows()
    cells = dt.row_cells(src, rows[1])
    assert cells[0]["text"] == "Bravo 2H" and cells[0]["pointer"] is None
    assert (cells[2]["pointerKind"], cells[2]["pointerValue"]) == ("VPID", 77)
    hits = dt.cells_pointing_at(src, rows, Pointer("PID", 500001))
    assert [(h["rowId"], h["name"]) for h in hits] == [(1, "Casing"), (1, "Updated")]
    assert dt.cells_pointing_at(src, rows, Pointer("PID", 77)) == []


def test_add_column_appends_by_default():
    src = fx.datatable()
    new, cid = dt.add_column(src, "Static", "ResultTagSelector")
    h = new["tableHeader"]
    assert h["tableHeaderColumns"][cid]["columnHeaderNewOrDuplicate"] == dt.NIL_UUID
    assert h["tableHeaderColumnsPosition"]["5"] == cid
    assert len(h["tableHeaderColumnsPosition"]) == 5
    assert cid not in src["tableHeader"]["tableHeaderColumns"], "pure"


def test_add_column_at_position_shifts_the_rest():
    new, cid = dt.add_column(fx.datatable(), "Static", "ResultTagSelector", at=2)
    assert [c["name"] for c in dt.columns(new)] == ["Well", "Static", "Casing", "Tubing", "Updated"]
    assert [c["position"] for c in dt.columns(new)] == [1, 2, 3, 4, 5]


def test_add_column_refuses_bad_input():
    with pytest.raises(ValueError):
        dt.add_column(fx.datatable(), "Casing", "ResultTagSelector")
    with pytest.raises(ValueError):
        dt.add_column(fx.datatable(), "X", "InvalidTagSelector")
    with pytest.raises(ValueError):
        dt.add_column(fx.datatable(), "X", "ResultTagSelector", at=9)


def test_delete_column_cleans_every_reference_and_repacks():
    new = dt.delete_column(fx.datatable(), fx.C_RES2)
    h = new["tableHeader"]
    assert fx.C_RES2 not in h["tableHeaderColumns"]
    assert h["tableHeaderColumnsPosition"] == {"1": fx.C_TEXT, "2": fx.C_RES1, "3": fx.C_TIME}
    assert h["tableHeaderColumnsOrder"] == {}
    assert h["tableHeaderHiddenColumns"] == []
    assert fx.C_RES2 not in new["tableDimensions"]["tableDimensionsCustomColumns"]
    assert fx.C_TEXT in new["tableDimensions"]["tableDimensionsCustomColumns"]
    assert new["tableFrozenColumn"] is None


def test_delete_column_repacks_from_zero_when_positions_start_at_zero():
    src = fx.datatable()
    h = src["tableHeader"]
    h["tableHeaderColumnsPosition"] = {str(int(p) - 1): c for p, c in h["tableHeaderColumnsPosition"].items()}
    new = dt.delete_column(src, fx.C_TEXT)
    assert sorted(new["tableHeader"]["tableHeaderColumnsPosition"]) == ["0", "1", "2"]


def test_delete_column_refuses_a_filtered_column_unless_dropped():
    src = fx.datatable()
    src["tableHeader"]["tableHeaderFilters"] = [fx.single_filter(fx.C_RES1),
                                                fx.group_filter(fx.C_RES1, fx.C_TIME),
                                                fx.single_filter(fx.C_TIME)]
    with pytest.raises(ValueError, match="--drop-filters"):
        dt.delete_column(src, fx.C_RES1)
    new = dt.delete_column(src, fx.C_RES1, drop_filters=True)
    kept = new["tableHeader"]["tableHeaderFilters"]
    assert len(kept) == 2
    assert filters.column_refs(kept) == {fx.C_TIME}


def test_filter_group_dropped_when_empty_and_legacy_refs_seen():
    legacy = {"filterRuleColumnRef": fx.C_RES1, "filterRuleOperator": "FilterIs"}
    assert filters.rules_referencing([legacy], fx.C_RES1) == [0]
    assert filters.drop_column([fx.group_filter(fx.C_RES1), legacy], fx.C_RES1) == []


def test_set_cells_keeps_row_length_and_sorts():
    src, rows = fx.datatable(), fx.datatable_rows()
    out = dt.set_cells(src, rows, [(2, fx.C_RES1, "4321 VPID"), (1, fx.C_RES2, None)])
    assert [r["tableRowId"] for r in out] == [1, 2]
    for r in out:
        assert len(r["tableRowValues"]) == 4
    assert out[0]["tableRowValues"] == ["Alpha 1H", "500001", None, "500001"]
    assert out[1]["tableRowValues"] == ["Bravo 2H", "4321 VPID", "77 VPID", "500011"]
    assert rows[1]["pointers"][1] == "500011", "pure"


def test_set_cells_type_checks():
    src, rows = fx.datatable(), fx.datatable_rows()
    # A Text column takes digits too (an ID column); intent is checked by the script.
    assert dt.set_cells(src, rows, [(1, fx.C_TEXT, "1234")])[0]["tableRowValues"][0] == "1234"
    with pytest.raises(ValueError, match="Invalid PID or VPID"):
        dt.set_cells(src, rows, [(1, fx.C_RES1, "Alpha")])
    with pytest.raises(ValueError, match="no row"):
        dt.set_cells(src, rows, [(42, fx.C_RES1, "1")])
    assert dt.set_cells(src, rows, [(1, fx.C_RES1, "500001")]) == [], "a no-op posts nothing"
    assert dt.set_cells(src, rows, [(1, fx.C_TEXT, "Renamed")])[0]["tableRowValues"][0] == "Renamed"


def test_set_cells_refuses_tables_with_an_invalid_column():
    src = fx.datatable()
    src["tableHeader"]["tableHeaderColumns"][fx.C_TIME]["columnHeaderSelector"] = "InvalidTagSelector"
    with pytest.raises(ValueError, match="InvalidTagSelector"):
        dt.set_cells(src, fx.datatable_rows(), [(1, fx.C_RES1, "1")])


def test_replace_pointer_edits():
    src, rows = fx.datatable(), fx.datatable_rows()
    edits = dt.replace_pointer_edits(src, rows, Pointer("PID", 500001), Pointer("PID", 9))
    assert edits == [(1, fx.C_RES1, "9"), (1, fx.C_TIME, "9")]
    only = dt.replace_pointer_edits(src, rows, Pointer("PID", 500001), Pointer("VPID", 9), fx.C_RES1)
    assert only == [(1, fx.C_RES1, "9 VPID")]


def test_header_mismatches_tolerates_server_rewrites():
    expected, cid = dt.add_column(fx.datatable(), "Static", "ResultTagSelector", at=1)
    actual = copy.deepcopy(expected)
    actual["tableHeader"]["tableHeaderColumns"][cid]["columnHeaderNewOrDuplicate"] = None
    pos = actual["tableHeader"]["tableHeaderColumnsPosition"]
    actual["tableHeader"]["tableHeaderColumnsPosition"] = {str(int(p) + 10): c for p, c in pos.items()}
    assert dt.header_mismatches(expected, actual) == []
    del actual["tableHeader"]["tableHeaderColumns"][cid]
    assert dt.header_mismatches(expected, actual)


def test_cell_mismatches():
    want = [{"tableRowId": 1, "tableRowValues": ["a", "1"]}]
    assert dt.cell_mismatches(want, [{"rowId": 1, "pointers": ["a", "1"]}]) == []
    assert dt.cell_mismatches(want, [{"rowId": 1, "pointers": ["a", "2"]}])


# ------------------------------------------------------------------ logtable

def test_schema_is_selected_by_version_not_index():
    src = fx.logtable()
    assert lt.schema(src)["logSchemaVersion"] == 2
    assert lt.schema(src, 1)["logSchemaVersion"] == 1
    src["logTableSourceSchemas"].reverse()
    assert lt.schema(src)["logSchemaVersion"] == 2
    with pytest.raises(ValueError, match="versions"):
        lt.schema(src, 7)


def test_columns_mark_the_event_column():
    cols = lt.columns(lt.schema(fx.logtable()))
    assert [(c["name"], c["event"]) for c in cols] == [("eventDateTime", True), ("flow", False),
                                                       ("message", False)]
    assert cols[2]["key"] == Pointer("VPID", 88) and cols[2]["hidden"]


def test_validate_schema_accepts_the_fixture():
    assert lt.validate_schema(lt.schema(fx.logtable())) == []


def test_validate_schema_rejects_missing_event_column():
    sch = copy.deepcopy(lt.schema(fx.logtable()))
    sch["logSchemaHeader"]["schemaHeaderEventSource"] = 123
    assert any("event PID" in e for e in lt.validate_schema(sch))


def test_validate_schema_rejects_position_mismatch():
    sch = copy.deepcopy(lt.schema(fx.logtable()))
    del sch["logSchemaHeader"]["schemaHeaderColumnsPosition"]["2"]
    assert any("disagree" in e for e in lt.validate_schema(sch))
    sch = copy.deepcopy(lt.schema(fx.logtable()))
    sch["logSchemaHeader"]["schemaHeaderColumnsPosition"] = {"0": fx.L_EVENT, "1": fx.L_FLOW, "5": fx.L_VP}
    assert any("without gaps" in e for e in lt.validate_schema(sch))


def test_validate_schema_rejects_text_selector():
    sch = copy.deepcopy(lt.schema(fx.logtable()))
    sch["logSchemaHeader"]["schemaHeaderColumns"][fx.L_FLOW]["columnSchemaSelector"] = "TextTagSelector"
    assert any("not allowed" in e for e in lt.validate_schema(sch))


def test_next_version_bumps_copies_and_keeps_uuids():
    stored = fx.logtable()
    stored["logTableSourceRequiresRestore"] = True
    body, new, cid = lt.next_version(
        stored, lambda s: lt.add_column(s, Pointer("PID", 600003), "pressure", at=1))
    assert body["logTableSourceSchemaVersion"] == 3
    assert new["logSchemaVersion"] == 3
    assert [s["logSchemaVersion"] for s in body["logTableSourceSchemas"]] == [3, 2, 1]
    for f in ("logTableSourceName", "logTableSourceGroupId", "logTableSourceDeleted",
              "logTableSourceRequiresRestore", "logTableSourceId", "logTableSourceLJSerial"):
        assert body[f] == stored[f]
    old_ids = set(lt.schema(stored)["logSchemaHeader"]["schemaHeaderColumns"])
    assert old_ids < set(new["logSchemaHeader"]["schemaHeaderColumns"])
    assert [c["name"] for c in lt.columns(new)] == ["eventDateTime", "pressure", "flow", "message"]
    assert new["logSchemaHeader"]["schemaHeaderColumns"][cid]["columnSchemaKey"] == 600003
    assert stored["logTableSourceSchemaVersion"] == 2, "pure"
    assert len(stored["logTableSourceSchemas"]) == 2, "pure"


def test_next_version_refuses_an_invalid_result():
    def break_it(s):
        s["logSchemaHeader"]["schemaHeaderEventSource"] = 1
    with pytest.raises(ValueError, match="invalid"):
        lt.next_version(fx.logtable(), break_it)


def test_logtable_add_column_rules():
    sch = copy.deepcopy(lt.schema(fx.logtable()))
    with pytest.raises(ValueError):
        lt.add_column(sch, Pointer("PID", 1), "x", selector="TextTagSelector")
    with pytest.raises(ValueError):
        lt.add_column(sch, Pointer("PID", 600002), "flow2")  # same key + selector
    lt.add_column(sch, Pointer("PID", 600002), "flowUnit", selector="UnitTagSelector")


def test_logtable_delete_column():
    body, new, _ = lt.next_version(fx.logtable(), lambda s: lt.delete_column(s, fx.L_FLOW))
    h = new["logSchemaHeader"]
    assert fx.L_FLOW not in h["schemaHeaderColumns"]
    assert h["schemaHeaderColumnsPosition"] == {"0": fx.L_EVENT, "1": fx.L_VP}
    assert fx.L_FLOW not in new["logSchemaDimensions"]["tableDimensionsCustomColumns"]


def test_logtable_delete_refuses_event_and_filtered_columns():
    with pytest.raises(ValueError, match="event"):
        lt.next_version(fx.logtable(), lambda s: lt.delete_column(s, fx.L_EVENT))
    src = fx.logtable()
    lt.schema(src)["logSchemaHeader"]["schemaHeaderFilters"] = [fx.single_filter(fx.L_FLOW)]
    with pytest.raises(ValueError, match="--drop-filters"):
        lt.next_version(src, lambda s: lt.delete_column(s, fx.L_FLOW))
    _, new, _ = lt.next_version(src, lambda s: lt.delete_column(s, fx.L_FLOW, drop_filters=True))
    assert new["logSchemaHeader"]["schemaHeaderFilters"] == []


def test_set_column_keeps_uuid_and_moves_the_trigger():
    _, new, notes = lt.next_version(
        fx.logtable(), lambda s: lt.set_column(s, fx.L_EVENT, pointer=Pointer("PID", 610000)))
    h = new["logSchemaHeader"]
    assert h["schemaHeaderEventSource"] == 610000
    assert h["schemaHeaderColumns"][fx.L_EVENT]["columnSchemaKey"] == 610000
    assert notes and "trigger" in notes[0]
    _, new, _ = lt.next_version(
        fx.logtable(), lambda s: lt.set_column(s, fx.L_FLOW, pointer=Pointer("VPID", 5), name="flowVP"))
    col = new["logSchemaHeader"]["schemaHeaderColumns"][fx.L_FLOW]
    assert col["columnSchemaKey"] == {"keyType": "VPID", "keyValue": 5}
    assert col["columnSchemaName"] == "flowVP"


def test_set_column_refusals():
    sch = copy.deepcopy(lt.schema(fx.logtable()))
    with pytest.raises(ValueError, match="PID, not a VPID"):
        lt.set_column(sch, fx.L_EVENT, pointer=Pointer("VPID", 1))
    with pytest.raises(ValueError, match="LastUpdateDateTime"):
        lt.set_column(sch, fx.L_EVENT, selector="ResultTagSelector")
    with pytest.raises(ValueError, match="nothing to change"):
        lt.set_column(sch, fx.L_FLOW)
    with pytest.raises(ValueError, match="already named"):
        lt.set_column(sch, fx.L_FLOW, name="message")


def test_resolve_logtable_column():
    sch = lt.schema(fx.logtable())
    assert lt.resolve_column(sch, "1")["id"] == fx.L_FLOW
    assert lt.resolve_column(sch, pointer=Pointer("VPID", 88))["id"] == fx.L_VP
    with pytest.raises(ValueError):
        lt.resolve_column(sch, pointer=Pointer("PID", 88))


def test_create_and_first_version_bodies_are_valid():
    body = lt.create_body(9999, "New", fx.GROUP)
    assert body["logTableSourceSchemas"] == [] and body["logTableSourceSchemaVersion"] == 0
    assert body["logTableSourceId"] == lt.NIL_UUID
    sch, cid = lt.empty_schema(600001)
    assert lt.validate_schema(sch) == []
    created = {**body, "logTableSourceId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
    up = lt.first_version_body(created, sch)
    assert up["logTableSourceSchemaVersion"] == 1 and up["logTableSourceSchemas"][0] is sch
    assert lt.upgrade_mismatches(up, copy.deepcopy(up)) == []


def test_upgrade_mismatches_detects_drift():
    body, _, _ = lt.next_version(fx.logtable(), lambda s: lt.set_column(s, fx.L_FLOW, name="flow2"))
    actual = copy.deepcopy(body)
    lt.schema(actual)["logSchemaHeader"]["schemaHeaderColumns"][fx.L_FLOW]["columnSchemaName"] = "flow"
    actual["logTableSourceName"] = "Other"
    problems = lt.upgrade_mismatches(body, actual)
    assert any("columns differ" in p for p in problems)
    assert any("logTableSourceName" in p for p in problems)


def test_query_body_newest_first_with_inclusive_minute_bounds():
    body, cols = lt.query_body(fx.logtable(), limit=3, since="2026-10-01 20:56:19",
                               until="2026-10-02T01:00:00Z")
    sch = body["logTableSourceSchemas"][0]
    h = sch["logSchemaHeader"]
    assert body["logTableSourceSchemaVersion"] == 2 and len(body["logTableSourceSchemas"]) == 1
    assert h["schemaHeaderHiddenColumns"] == []
    assert h["schemaHeaderColumnsOrder"] == {fx.L_EVENT: "ColumnOrderLexicographicDESC"}
    vals = [(f["contents"]["singleFilterOperator"], f["contents"]["singleFilterInputValue"])
            for f in h["schemaHeaderFilters"]]
    assert vals == [("FilterIsAbove", "2026-10-01 20:55"), ("FilterIsBelow", "2026-10-02 01:01")]
    assert sch["logSchemaPagination"] == {"tablePaginationLimit": 3, "tablePaginationOffset": 0}
    assert [c["name"] for c in cols] == ["eventDateTime", "flow", "message"]
    old, _ = lt.query_body(fx.logtable(), version=1)
    assert old["logTableSourceSchemaVersion"] == 1


# ------------------------------------------------------------------ the gate

@pytest.mark.parametrize("yes,dry_run,posts", [(False, False, False), (True, False, True),
                                               (False, True, False), (True, True, False)])
def test_gate_needs_yes_and_dry_run_wins(yes, dry_run, posts, capsys):
    import argparse

    from _lj_table_routes.mutate import should_post
    assert should_post(argparse.Namespace(yes=yes, dry_run=dry_run)) is posts
    out = capsys.readouterr().out
    assert ("nothing was posted" in out) is (not posts)


@pytest.mark.parametrize("yes,dry_run,final", [(False, False, False), (True, False, True),
                                               (True, True, False)])
def test_new_column_mark_flags_preview_uuid(yes, dry_run, final):
    import argparse

    from _lj_table_routes.mutate import new_column_mark
    mark = new_column_mark(argparse.Namespace(yes=yes, dry_run=dry_run), "new (empty)")
    assert mark.startswith("   <-- new (empty)")
    assert ("drawn again on --yes" in mark) is (not final)
