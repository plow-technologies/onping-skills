"""Offline tests for the Data Table helper (lane H): the new routes, lj_http additions, row and view
helpers, and the fake Lumberjack itself. No network."""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402
from _lj_table_routes import datatable as dt  # noqa: E402
from _lj_table_routes import datatable_rows as rows  # noqa: E402
from _lj_table_routes import datatable_view as dv  # noqa: E402
from _lj_table_routes import lj_http, pace  # noqa: E402
from _lj_table_routes.routes import ROUTES  # noqa: E402

TOKEN = "test-token"
SKILLS_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lj(monkeypatch):
    return fx.FakeLumberjack().install(monkeypatch)


@pytest.fixture
def table(lj):
    return lj.add_source()


def pointers(lj, table_id):
    return [r["pointers"] for r in lj.rows(table_id)]


# ------------------------------------------------------------------- routes

NEW_SOURCE = ["datatable_create", "datatable_delete", "datatable_content_add", "datatable_content_delete",
              "datatable_content_delete_by_table", "datatable_column_upsert", "datatable_import",
              "datatable_import_template", "datatable_template", "datatable_export_dump",
              "datatable_sync_request", "datatable_sync_status"]
NEW_VIEW = ["datatable_view_all", "datatable_widget_create", "datatable_widget_get", "datatable_view_create",
            "datatable_view_delete", "datatable_view_get", "datatable_view_query",
            "datatable_view_sync_status", "datatable_view_sync", "datatable_view_metadata_update"]


def test_twelve_source_and_ten_view_routes_are_listed():
    assert all(k in ROUTES for k in NEW_SOURCE + NEW_VIEW)
    for k in NEW_SOURCE + NEW_VIEW:
        spec = ROUTES[k]
        for field in ("endpoint", "handler", "response", "permission", "notes"):
            assert spec.get(field), f"{k} lacks {field}"
        assert spec["endpoint"].split(" ", 1)[0] in ("GET", "POST")


def test_only_delete_by_table_is_forbidden_and_every_writer_is_paced():
    assert [k for k, v in ROUTES.items() if v.get("forbidden")] == ["datatable_content_delete_by_table"]
    for k in ("datatable_content_add", "datatable_content_delete", "datatable_create", "datatable_delete",
              "datatable_import", "datatable_view_create", "datatable_view_delete", "datatable_view_sync",
              "datatable_view_metadata_update", "datatable_content_update", "datatable_metadata_update"):
        assert ROUTES[k].get("writes"), k
    for k in ("datatable_query", "datatable_view_get", "datatable_view_query", "datatable_view_sync_status",
              "datatable_export_dump", "datatable_template", "datatable_widget_get"):
        assert not ROUTES[k].get("writes"), k


def test_helper_modules_only_use_listed_routes():
    for name in ("datatable_rows.py", "datatable_view.py"):
        text = (SKILLS_ROOT / "_lj_table_routes" / name).read_text()
        for key in set(re.findall(r'"(datatable_[a-z_]+)"', text)):
            assert key in ROUTES, f"{name} uses unlisted route {key}"


def test_no_script_outside_the_helper_names_the_delete_everything_route():
    bad = []
    for path in SKILLS_ROOT.rglob("*.py"):
        rel = path.relative_to(SKILLS_ROOT).as_posix()
        if rel.startswith("_lj_table_routes/routes.py") or "/tests/" in rel or rel.startswith("_lj_table_routes/tests"):
            continue
        text = path.read_text()
        if "delete_by_table" in text or "delete/by/table" in text:
            bad.append(rel)
    assert bad == []


# ------------------------------------------------------------------ lj_http

def test_forbidden_route_is_refused_without_a_request(lj):
    with pytest.raises(lj_http.ForbiddenRoute) as e:
        lj_http.post_json(TOKEN, "datatable_content_delete_by_table", ["x", False], lj=9999)
    assert "forbidden" in str(e.value)
    assert lj.calls == [] and lj.forbidden_calls == []


# ---------------------------------------------------- path-parameter validation (lane H2)

BAD_LJ = ["", "-1", "12/../3", "3484?x=1", "3484#f", "34 84", "3484\n", "0x10", "٣٤٨٤", "../3484", True, None, 3.5, "3484/"]
BAD_WIDGET = ["", "o1/../x", "o1?a=b", "o1#", "o1%2e", "o1\\x", "o1 ", "o1\n", "..", "a/b", "é1", None, 12]
BAD_NAME = ["", " ", ".", "..", "a/b", "a?b", "a#b", "a%2fb", "a%00", "a\\b", "a..b", "../x", "a\x00b", "a\nb",
            "a\x7fb", None, 5]


@pytest.mark.parametrize("bad", BAD_LJ)
def test_bad_lj_is_refused_before_any_request(lj, bad):
    with pytest.raises(lj_http.PathParamError):
        lj_http.get_json(TOKEN, "datatable_list", lj=bad)
    assert lj.calls == []


@pytest.mark.parametrize("bad", BAD_WIDGET)
def test_bad_widget_id_is_refused_before_any_request(lj, bad):
    with pytest.raises(lj_http.PathParamError):
        lj_http.get_json(TOKEN, "datatable_widget_get", widget=bad)
    with pytest.raises(lj_http.PathParamError):
        lj_http.post_json(TOKEN, "datatable_view_delete", None, widget=bad)
    assert lj.calls == []


@pytest.mark.parametrize("bad", BAD_NAME)
def test_bad_export_name_is_refused_before_any_request(lj, bad):
    for route in ("datatable_export_dump", "datatable_template"):
        if "{name}" not in ROUTES[route]["endpoint"]:
            continue
        with pytest.raises(lj_http.PathParamError):
            lj_http.post_bytes(TOKEN, route, "x", lj=lj.lj, name=bad)
    assert lj.calls == []


def test_path_param_error_exits_2():
    assert lj_http.exit_code(lj_http.PathParamError("x")) == 2
    assert lj_http.exit_code(lj_http.LJTableError("x")) == 1


def test_missing_and_extra_path_params_are_refused(lj):
    with pytest.raises(lj_http.PathParamError):
        lj_http.get_json(TOKEN, "datatable_list")
    with pytest.raises(lj_http.PathParamError):
        lj_http.get_json(TOKEN, "datatable_list", lj=lj.lj, widget="o1")
    assert lj.calls == []


def test_good_params_build_the_expected_url():
    ep = ROUTES["datatable_list"]["endpoint"]
    tail = ep.split(" ", 1)[1].replace("{lj}", "3484")
    assert lj_http._url(ep, lj=3484) == lj_http.BASE_URL + tail == lj_http._url(ep, lj="3484")
    w = ROUTES["datatable_widget_get"]["endpoint"]
    assert lj_http._url(w, widget="oAbC123").endswith("/oAbC123")


def test_a_plain_export_name_with_a_space_is_encoded_once():
    for route in ("datatable_export_dump", "datatable_template"):
        ep = ROUTES[route]["endpoint"]
        if "{name}" in ep:
            assert lj_http._url(ep, lj=1, name="my table").endswith("/my%20table")


def test_check_uuid_accepts_only_uuids():
    good = "123e4567-e89b-12d3-a456-426614174000"
    assert lj_http.check_uuid(good) == good
    for bad in ["", "x", good + "/", good[:-1], good.replace("-", ""), None, 5, good + "\n", "../" + good]:
        with pytest.raises(lj_http.PathParamError):
            lj_http.check_uuid(bad)


def test_forbidden_route_is_refused_on_the_final_path_too(lj, monkeypatch):
    # A different route name whose template resolves to the forbidden path still sends nothing.
    forbidden = ROUTES["datatable_content_delete_by_table"]["endpoint"]
    sneaky = dict(ROUTES["datatable_content_add"], endpoint=forbidden, forbidden=False)
    monkeypatch.setitem(ROUTES, "sneaky", sneaky)
    with pytest.raises(lj_http.ForbiddenRoute):
        lj_http.post_json(TOKEN, "sneaky", ["x", []], lj=lj.lj)
    assert lj.calls == [] and lj.forbidden_calls == []


def test_every_route_resolves_with_valid_params():
    values = {"lj": 3484, "widget": "oAbC123", "name": "dump"}
    for key, spec in ROUTES.items():
        template = spec["endpoint"].split(" ", 1)[1]
        params = {n: values[n] for n in lj_http._PLACEHOLDER_RE.findall(template)}
        assert lj_http._url(spec["endpoint"], **params).startswith(lj_http.BASE_URL), key


def test_permission_denied_for_each_new_write_route(lj, table):
    lj.deny_writes = True
    attempts = [
        ("datatable_content_add", [table["tableId"], [[None] * 4]], {"lj": 9999}),
        ("datatable_content_delete", [table["tableId"], [1]], {"lj": 9999}),
        ("datatable_delete", table["tableId"], {"lj": 9999}),
        ("datatable_create", fx.copy.deepcopy(table), {}),
    ]
    for route, body, path in attempts:
        with pytest.raises(lj_http.LJTableError) as e:
            lj_http.post_json(TOKEN, route, body, **path)
        assert e.value.status == 500 and "OWNED" in str(e.value), route
    assert len(pointers(lj, table["tableId"])) == 3


def test_503_and_missing_routing_messages(lj, table):
    lj.fail_next(503)
    with pytest.raises(lj_http.LJTableError) as e:
        rows.post_add(TOKEN, table, [[None] * 4])
    assert e.value.status == 503 and "retry" in str(e.value)
    lj.routed = False
    with pytest.raises(lj_http.LJTableError) as e:
        lj_http.get_json(TOKEN, "datatable_list", lj=9999)
    assert e.value.status == 404 and "no routing" in str(e.value)


def test_429_is_never_resent_and_exits_6(lj, table, capsys):
    lj.rate_limit_after = 1
    rows.post_add(TOKEN, table, [[None] * 4])
    with pytest.raises(lj_http.RateLimited) as e:
        rows.post_add(TOKEN, table, [[None] * 4])
    assert lj.write_count == 2 and len(lj.rows(table["tableId"])) == 4
    assert lj_http.exit_code(e.value) == 6 and lj_http.exit_code(lj_http.LJTableError("x")) == 1
    assert "Nothing is resent" in lj_http.stop_message(e.value, "One batch landed.")
    with pytest.raises(SystemExit) as x:
        lj_http.die(e.value)
    assert x.value.code == 6


def test_writes_are_paced_and_reads_are_not(lj, table, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(pace, "clock", lambda: now[0])
    rows.post_add(TOKEN, table, [[None] * 4])
    dt.query(TOKEN, table)
    assert lj.sleeps == []
    now[0] += 3
    rows.post_add(TOKEN, table, [[None] * 4])
    assert lj.sleeps == [pytest.approx(pace.MIN_GAP_S - 3)]
    assert pace.sent() == 2


def test_bearer_token_is_required(lj):
    with pytest.raises(lj_http.LJTableError) as e:
        lj_http.get_json("wrong", "datatable_list", lj=9999)
    assert e.value.status == 401


def test_export_returns_xlsx_bytes_and_rejects_html(lj, table, monkeypatch):
    data = rows.export_file(TOKEN, table, "t.xlsx")
    assert data.startswith(b"PK\x03\x04")
    assert rows.export_file(TOKEN, table, "t.xlsx", template=True).startswith(b"PK")
    monkeypatch.setattr(lj, "_datatable_export_dump",
                        lambda b, lj, name: fx.FakeResponse(200, "<html>login</html>"))
    with pytest.raises(lj_http.LJTableError):
        rows.export_file(TOKEN, table, "t.xlsx")


def test_import_sends_f1_and_f2_and_appends(lj, table):
    lj.import_preset = [["Zulu", "500003", "500004", "500003"]]
    rows.import_file(TOKEN, table, b"PK\x03\x04stub", "rows.xlsx")
    assert lj.calls[-1][2]["data"] == {"f2": table["tableId"]}
    assert list(lj.calls[-1][2]["files"]) == ["f1"]
    assert pointers(lj, table["tableId"])[-1] == ["Zulu", "500003", "500004", "500003"]
    with pytest.raises(ValueError):
        rows.import_file(TOKEN, table, b"not xlsx", "x.xlsx")


def test_import_with_a_real_workbook(lj, table):
    pytest.importorskip("openpyxl")
    lj.import_preset = None
    book = fx.make_xlsx(["a", "b", "c", "d"], [["Yank", "500005", None, "500005"]])
    rows.import_file(TOKEN, table, book, "rows.xlsx")
    assert pointers(lj, table["tableId"])[-1] == ["Yank", "500005", None, "500005"]
    lj.sleeps.clear()
    bad = fx.make_xlsx(["a"], [["x"]], sheet="Data")
    with pytest.raises(lj_http.LJTableError):
        rows.import_file(TOKEN, table, bad, "rows.xlsx")


# -------------------------------------------------------------- row helpers

HEADERS = ["Well", "Casing", "Tubing", "Updated"]


def test_header_map_handles_reorder_and_refuses_bad_files(table):
    cols = rows.header_map(table, ["Updated", "Well", "Tubing", "Casing"])
    assert [c["name"] for c in cols] == ["Updated", "Well", "Tubing", "Casing"]
    with pytest.raises(ValueError, match="Nope"):
        rows.header_map(table, ["Well", "Nope", "Tubing", "Updated"])
    with pytest.raises(ValueError, match="no column for"):
        rows.header_map(table, ["Well", "Casing"])
    with pytest.raises(ValueError, match="already covers"):
        rows.header_map(table, ["Well", "Well", "Casing", "Tubing", "Updated"])


def test_build_rows_reorders_to_position_order_and_checks_cells(table):
    recs = [["500009", "Quebec 5H", "500001", "500002"]]
    built = rows.build_rows(table, ["Updated", "Well", "Casing", "Tubing"], recs)
    assert built == [["Quebec 5H", "500001", "500002", "500009"]]
    bad = [["2026-01-01", "Quebec 5H", "500001", "500002"]]      # Updated is a pointer column
    with pytest.raises(ValueError, match="record 1, column 'Updated'"):
        rows.build_rows(table, ["Updated", "Well", "Casing", "Tubing"], bad)
    with pytest.raises(ValueError, match="2 cells"):
        rows.build_rows(table, HEADERS, [["a", "b"]])


def test_build_rows_names_record_31_and_accepts_vpid_and_null(table):
    recs = [["W%d" % i, "500001", "77 VPID", "500002"] for i in range(30)]
    recs.append(["W30", "abc", None, ""])
    with pytest.raises(ValueError, match="record 31, column 'Casing'"):
        rows.build_rows(table, HEADERS, recs)
    ok = rows.build_rows(table, HEADERS, [["A", "500001", "77 VPID", ""]])
    assert ok == [["A", "500001", "77 VPID", None]]


def test_zero_column_and_invalid_selector_tables_are_refused(table):
    empty = rows.create_body("x", 9999, fx.GROUP)
    with pytest.raises(ValueError, match="no columns"):
        rows.writable_columns(empty)
    bad = copy.deepcopy(table)
    bad["tableHeader"]["tableHeaderColumns"][fx.C_RES1]["columnHeaderSelector"] = "InvalidTagSelector"
    with pytest.raises(ValueError, match="InvalidTagSelector"):
        rows.writable_columns(bad)


def test_split_batches_250_rows_in_100_100_50_and_size_limits():
    data = [[str(i)] for i in range(250)]
    assert [len(b) for b in rows.split_batches(data)] == [100, 100, 50]
    assert [len(b) for b in rows.split_batches(data, 30)] == [30] * 8 + [10]
    for size in (0, 101):
        with pytest.raises(ValueError):
            rows.split_batches(data, size)


def test_add_in_batches_reads_back_exactly_the_sent_rows(lj, table):
    tid = table["tableId"]
    before = dt.query_all(TOKEN, table)
    data = [[f"W{i}", "500001", "500002", "500003"] for i in range(250)]
    for batch in rows.split_batches(data):
        rows.post_add(TOKEN, table, batch)
    after = dt.query_all(TOKEN, table)
    assert rows.add_mismatches(before, after, data) == []
    assert len(after) == 253 and len(lj.writes()) == 3
    assert tid in lj.sources


def test_add_mismatches_catch_a_dropped_a_duplicated_and_a_foreign_row(lj, table):
    before = dt.query_all(TOKEN, table)
    data = [["A", "500001", None, None], ["B", "500002", None, None], ["C", "500003", None, None]]
    lj.drop_add_index = 1
    rows.post_add(TOKEN, table, data)
    problems = rows.add_mismatches(before, dt.query_all(TOKEN, table), data)
    assert any("did not land" in p for p in problems) and any("grew by 2" in p for p in problems)
    lj2 = fx.FakeLumberjack()
    lj.duplicate_add_index = 0
    before = dt.query_all(TOKEN, table)
    rows.post_add(TOKEN, table, data)
    problems = rows.add_mismatches(before, dt.query_all(TOKEN, table), data)
    assert any("unexpected new row" in p for p in problems)
    del lj2


def test_short_row_is_rejected_or_padded_per_switch(lj, table):
    with pytest.raises(lj_http.LJTableError):
        rows.post_add(TOKEN, table, [["only", "one"]])
    lj.short_rows = "pad"
    rows.post_add(TOKEN, table, [["only", "500001"]])
    assert pointers(lj, table["tableId"])[-1] == ["only", "500001", None, None]


def test_check_rows_rejects_bad_width_and_pointer(table):
    rows.check_rows(table, [["a", "1", "2 VPID", None]])
    with pytest.raises(ValueError, match="row 1 has 2 values"):
        rows.check_rows(table, [["a", "b"]])
    with pytest.raises(ValueError, match="row 2"):
        rows.check_rows(table, [["a", "1", "2", "3"], ["a", "x", "2", "3"]])


def test_resume_after_a_failure_that_applied_does_not_duplicate(lj, table):
    base = dt.query_all(TOKEN, table)
    data = [[f"W{i}", "500001", None, None] for i in range(5)]
    state = rows.make_state(table, base, data)
    batches = rows.split_batches(data, 2)
    rows.post_add(TOKEN, table, batches[0])
    lj.apply_then_fail_next(500, "gateway timeout")
    with pytest.raises(lj_http.LJTableError):
        rows.post_add(TOKEN, table, batches[1])           # landed, but the answer was an error
    plan = rows.plan_resume(state, dt.query_all(TOKEN, table))
    assert plan["safe"] and plan["done"] == [0, 1, 2, 3] and [i for i, _ in plan["pending"]] == [4]
    for batch in rows.split_batches([r for _i, r in plan["pending"]], 2):
        rows.post_add(TOKEN, table, batch)
    final = dt.query_all(TOKEN, table)
    assert rows.add_mismatches(base, final, data) == []
    assert rows.plan_resume(state, final)["pending"] == []


def test_resume_with_identical_rows_counts_each_once(lj, table):
    base = dt.query_all(TOKEN, table)
    data = [["same", "500001", None, None]] * 3
    state = rows.make_state(table, base, data)
    rows.post_add(TOKEN, table, data[:2])
    plan = rows.plan_resume(state, dt.query_all(TOKEN, table))
    assert plan["done"] == [0, 1] and [i for i, _ in plan["pending"]] == [2]


def test_resume_refuses_foreign_rows_and_lost_rows(lj, table):
    base = dt.query_all(TOKEN, table)
    state = rows.make_state(table, base, [["mine", None, None, None]])
    rows.post_add(TOKEN, table, [["someone else", None, None, None]])
    plan = rows.plan_resume(state, dt.query_all(TOKEN, table))
    assert not plan["safe"] and plan["foreign"] == [["someone else", None, None, None]]
    rows.post_delete(TOKEN, table, [1])
    assert rows.plan_resume(state, dt.query_all(TOKEN, table))["lost"] == [1]


def test_state_file_must_match_the_table(table):
    state = rows.make_state(table, [], [["a", None, None, None]])
    assert rows.load_state(state, table) is state
    other = copy.deepcopy(table)
    other["tableId"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    with pytest.raises(ValueError, match="is for table"):
        rows.load_state(state, other)
    with pytest.raises(ValueError):
        rows.load_state({"kind": "x"}, table)


def test_delete_by_id_and_mismatch_detection(lj, table):
    before = dt.query_all(TOKEN, table)
    rows.post_delete(TOKEN, table, [2])
    after = dt.query_all(TOKEN, table)
    assert rows.delete_mismatches(before, after, [2]) == []
    assert [r["rowId"] for r in after] == [1, 3]
    assert any("still present" in p for p in rows.delete_mismatches(before, before, [2]))
    assert any("not on the delete list" in p for p in rows.delete_mismatches(before, [after[0]], [2]))
    with pytest.raises(lj_http.LJTableError):
        rows.post_delete(TOKEN, table, [])
    assert lj.forbidden_calls == []


def test_rows_hash_is_stable_and_changes_with_content(lj, table):
    r = dt.query_all(TOKEN, table)
    assert rows.rows_hash(r) == rows.rows_hash(list(reversed(r)))
    r2 = copy.deepcopy(r)
    r2[0]["pointers"][0] = "changed"
    assert rows.rows_hash(r) != rows.rows_hash(r2)


def test_backup_round_trips_through_add(lj, table):
    before = dt.query_all(TOKEN, table)
    doc = rows.backup_doc(table, before)
    rows.post_delete(TOKEN, table, [1, 2, 3])
    assert pointers(lj, table["tableId"]) == []
    readd = rows.rows_from_backup(doc, table)
    rows.post_add(TOKEN, table, readd)
    assert [r["pointers"] for r in dt.query_all(TOKEN, table)] == [r["pointers"] for r in before]
    drifted = copy.deepcopy(table)
    drifted["tableHeader"]["tableHeaderColumns"][fx.C_RES1]["columnHeaderSelector"] = "TextTagSelector"
    with pytest.raises(ValueError, match="differ"):
        rows.rows_from_backup(doc, drifted)


def test_create_then_delete_a_source(lj):
    body = rows.create_body("New table", 9999, fx.GROUP)
    new_id = rows.post_create(TOKEN, body)
    assert new_id != fx.NIL and lj.sources[new_id]["tableHeader"]["tableHeaderColumns"] == {}
    assert dt.list_sources(TOKEN, 9999)[0]["tableId"] == new_id
    other = rows.create_body("Nope", 9999, fx.OTHER_GROUP)
    with pytest.raises(lj_http.LJTableError, match="OWNED"):
        rows.post_create(TOKEN, other)
    lj_http.post_json(TOKEN, "datatable_delete", new_id, lj=9999)
    assert dt.list_sources(TOKEN, 9999) == []


def test_fake_query_joins_pointers_by_row_id_despite_reversed_order(lj, table):
    got = dt.query_all(TOKEN, table)
    assert [r["rowId"] for r in got] == [1, 2, 3]
    assert got[0]["pointers"][0] == "Alpha 1H" and got[1]["pointers"][0] == "Bravo 2H"


def test_fake_delete_by_table_records_and_wipes_when_called_directly(lj, table):
    lj.request("POST", f"{lj._base}/datatable/9999/source/content/delete/by/table",
               headers={"Authorization": f"Bearer {TOKEN}"}, data='["%s",false]' % table["tableId"])
    assert len(lj.forbidden_calls) == 1 and pointers(lj, table["tableId"]) == []


def test_metadata_update_drops_and_adds_columns_like_the_server(lj, table):
    new, _cid = dt.add_column(table, "Extra", "ResultTagSelector")
    dt.post_metadata(TOKEN, new)
    assert all(len(p) == 5 for p in pointers(lj, table["tableId"]))
    stored = dt.find_source(TOKEN, 9999, table["tableId"])
    assert dt.header_mismatches(new, stored) == []


# ------------------------------------------------------------- view helpers

@pytest.fixture
def view(lj, table):
    v, wid = lj.add_view(table["tableId"])
    return v


def test_edits_never_change_columns_filters_or_dimensions(view):
    view["tableViewHeader"]["tableHeaderFilters"] = [fx.single_filter(fx.C_RES1)]
    edits = [dv.set_hidden(view, ["Casing"], True), dv.set_hidden(view, ["Tubing"], False),
             dv.reorder(view, ["Updated", "Well"]), dv.set_page_size(view, 50),
             dv.set_frozen_column(view, "Well"), dv.set_frozen_column(view, None)]
    for new in edits:
        assert dv.preserved_problems(view, new) == []
        assert new is not view
    assert fx.C_RES1 in dv.set_hidden(view, ["Casing"], True)["tableViewHeader"]["tableHeaderHiddenColumns"]
    assert fx.C_RES2 not in dv.set_hidden(view, ["Tubing"], False)["tableViewHeader"]["tableHeaderHiddenColumns"]
    order = [c["name"] for c in dv.columns(dv.reorder(view, ["Updated", "Well"]))]
    assert order == ["Updated", "Well", "Casing", "Tubing"]
    assert dv.set_page_size(view, 50)["tableViewPagination"]["tablePaginationLimit"] == 50
    assert dv.set_frozen_column(view, "Well")["tableViewFrozenColumn"] == fx.C_TEXT


def test_edit_errors_name_the_column(view):
    with pytest.raises(ValueError, match="Missing"):
        dv.set_hidden(view, ["Missing"], True)
    with pytest.raises(ValueError, match="twice"):
        dv.reorder(view, ["Well", "well"])
    for bad in (0, -1, True, "5"):
        with pytest.raises(ValueError):
            dv.set_page_size(view, bad)


def test_preserved_problems_flags_each_forbidden_change(view):
    cases = {}
    a = copy.deepcopy(view); a["tableViewHeader"]["tableHeaderFilters"] = [fx.single_filter(fx.C_RES1)]
    cases["the filters changed"] = a
    b = copy.deepcopy(view); del b["tableViewHeader"]["tableHeaderColumns"][fx.C_TIME]
    cases["the column set changed"] = b
    c = copy.deepcopy(view); c["tableViewDimensions"]["tableDimensionsCellWidth"] = 9
    cases["the dimensions changed"] = c
    d = copy.deepcopy(view); d["tableViewName"] = "renamed"
    cases["tableViewName changed"] = d
    for expect, new in cases.items():
        assert expect in dv.preserved_problems(view, new)


def test_view_hash_is_stable_and_sensitive(view):
    assert dv.view_hash(view) == dv.view_hash(copy.deepcopy(view))
    assert dv.view_hash(view) != dv.view_hash(dv.set_page_size(view, 77))


def test_update_round_trip_through_the_fake_and_filters_survive(lj, table, view):
    view["tableViewHeader"]["tableHeaderFilters"] = [fx.single_filter(fx.C_RES1)]
    lj.views[view["tableViewId"]] = copy.deepcopy(view)
    stored = dv.read_view(TOKEN, 9999, view["tableViewId"])
    new = dv.set_page_size(dv.set_hidden(stored, ["Casing"], True), 40)
    assert dv.preserved_problems(stored, new) == []
    dv.post_view_update(TOKEN, new)
    back = dv.read_view(TOKEN, 9999, view["tableViewId"])
    assert dv.view_mismatches(new, back) == []
    assert back["tableViewHeader"]["tableHeaderFilters"] == stored["tableViewHeader"]["tableHeaderFilters"]


def test_view_mismatches_catch_a_dropped_field_and_an_ignored_update(lj, table, view):
    new = dv.set_page_size(view, 33)
    lj.view_drop_fields = {"tableViewFrozenRows"}
    new["tableViewFrozenRows"] = [1]
    dv.post_view_update(TOKEN, new)
    back = dv.read_view(TOKEN, 9999, view["tableViewId"])
    assert any("tableViewFrozenRows" in p for p in dv.view_mismatches(new, back))
    lj.view_drop_fields = set()
    lj.view_ignore_update = True
    new2 = dv.set_page_size(view, 44)
    dv.post_view_update(TOKEN, new2)
    assert any("tableViewPagination" in p for p in dv.view_mismatches(new2, dv.read_view(TOKEN, 9999, view["tableViewId"])))


def test_fake_view_update_strips_unknown_columns_and_keeps_the_column_set(lj, view):
    sent = copy.deepcopy(view)
    sent["tableViewHeader"]["tableHeaderColumnsPosition"]["9"] = "99999999-9999-4999-8999-999999999999"
    del sent["tableViewHeader"]["tableHeaderColumns"][fx.C_TIME]
    dv.post_view_update(TOKEN, sent)
    back = dv.read_view(TOKEN, 9999, view["tableViewId"])
    assert dv.column_set(back) == dv.column_set(view)
    assert "9" not in back["tableViewHeader"]["tableHeaderColumnsPosition"]


def test_sync_status_then_sync(lj, table, view):
    assert dv.sync_state(dv.read_sync_status(TOKEN, 9999, view["tableViewId"])) == "synced"
    new_src, _ = dt.add_column(table, "Extra", "ResultTagSelector")
    dt.post_metadata(TOKEN, new_src)
    status = dv.read_sync_status(TOKEN, 9999, view["tableViewId"])
    assert dv.sync_state(status) == "unsynced" and status["contents"]["columnsAddedInSource"]
    dv.post_sync(TOKEN, 9999, view["tableViewId"])
    assert dv.sync_state(dv.read_sync_status(TOKEN, 9999, view["tableViewId"])) == "synced"
    lj.sources[table["tableId"]]["tableDeleted"] = True
    assert dv.sync_state(dv.read_sync_status(TOKEN, 9999, view["tableViewId"])) == "deprecated"
    with pytest.raises(lj_http.LJTableError):
        dv.sync_state({"tag": "Wat"})


def test_widget_then_view_lifecycle_and_leftover(lj, table):
    wid = dv.create_widget(TOKEN)
    assert dv.widget_state(dv.read_widget(TOKEN, wid), "dash1") == "empty"
    vid = dv.create_view(TOKEN, wid, table)
    widget = dv.read_widget(TOKEN, wid)
    assert widget["dataTableWidgetTableViewId"] == vid and dv.widget_state(widget, "dash1") == "unclaimed"
    assert dv.read_view(TOKEN, 9999, vid)["tableViewTableSourceId"] == table["tableId"]
    assert [v["tableViewId"] for v in dv.all_views(TOKEN)] == [vid]
    dv.delete_widget_view(TOKEN, wid)
    assert dv.read_widget(TOKEN, wid) is None and dv.widget_state(None, "d") == "missing"
    assert lj.views[vid]["tableViewDeleted"] is True
    dv.delete_widget_view(TOKEN, wid)          # a missing widget is success


def test_view_create_needs_the_source_group_owned_and_leaves_an_empty_widget(lj):
    other = lj.add_source(fx.datatable() | {"tableId": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                                            "tableGroupId": fx.OTHER_GROUP})
    wid = dv.create_widget(TOKEN)
    with pytest.raises(lj_http.LJTableError, match="OWNED"):
        dv.create_view(TOKEN, wid, other)
    assert dv.widget_state(dv.read_widget(TOKEN, wid), "d") == "empty"


def test_widget_state_distinguishes_own_and_foreign(lj, table):
    v, wid = lj.add_view(table["tableId"], widget_dashboard_id="dashA")
    widget = dv.read_widget(TOKEN, wid)
    assert dv.widget_state(widget, "dashA") == "own" and dv.widget_state(widget, "DASHA") == "own"
    assert dv.widget_state(widget, "dashB") == "foreign"


def test_copy_on_save_forks_a_foreign_widget_and_duplication_is_reported(lj, table):
    v, wid = lj.add_view(table["tableId"], widget_dashboard_id="dashA")
    before = dv.all_views(TOKEN)
    assert lj.save_card("dashA", wid) == wid                       # own: in place
    assert lj.save_card("dashB", wid) != wid                       # foreign: copied
    assert dv.duplication_failures(before, dv.all_views(TOKEN), []) != []
    after = dv.all_views(TOKEN)
    assert len(after) == 2
    assert any("unexpected new view" in p for p in dv.duplication_failures(before, after))
    new_id = [x["tableViewId"] for x in after if x["tableViewId"] != v["tableViewId"]][0]
    assert dv.duplication_failures(before, after, [new_id]) == []


def test_copy_on_save_claims_an_unclaimed_widget_in_place_and_new_insert_always_copies(lj, table):
    v, wid = lj.add_view(table["tableId"])
    assert lj.save_card("dashA", wid) == wid
    assert lj.widgets[wid]["dataTableWidgetDashboardId"] == "dashA"
    assert lj.save_card("dashA", wid, insert="new") != wid
    empty = lj.add_widget()
    assert lj.save_card("dashC", empty, insert="new") == empty


def test_view_routes_deny_readers_without_membership_and_writers_without_ownership(lj, table, view):
    lj.owned, lj.member = set(), {fx.GROUP}
    assert dv.read_view(TOKEN, 9999, view["tableViewId"])["tableViewId"] == view["tableViewId"]
    with pytest.raises(lj_http.LJTableError, match="OWNED"):
        dv.post_view_update(TOKEN, view)
    with pytest.raises(lj_http.LJTableError, match="OWNED"):
        dv.post_sync(TOKEN, 9999, view["tableViewId"])
    lj.member = set()
    with pytest.raises(lj_http.LJTableError):
        dv.read_view(TOKEN, 9999, view["tableViewId"])


def test_no_view_helper_calls_a_source_write_route():
    text = (SKILLS_ROOT / "_lj_table_routes" / "datatable_view.py").read_text()
    used = set(re.findall(r'"(datatable_[a-z_]+)"', text))
    source_writes = {k for k, v in ROUTES.items() if v.get("writes") and k in NEW_SOURCE + [
        "datatable_content_update", "datatable_metadata_update"]}
    assert used & source_writes == set()
