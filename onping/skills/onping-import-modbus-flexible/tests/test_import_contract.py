"""Contract tests for onping-import-modbus-flexible.

HTTP is faked; every PID, location id and name is synthetic. Run with:

    uv run --with pytest --with requests --with openpyxl \
        pytest onping/skills/onping-import-modbus-flexible/tests
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_params.py"
spec = importlib.util.spec_from_file_location("import_modbus_flexible", SCRIPT)
imp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = imp  # dataclasses look the module up by name
spec.loader.exec_module(imp)

LOC = 20006
TOKEN = "synthetic-token"
HEADERS = ["PID", "Index", "Description", "Read/Write", "Data Type", "On Change", "Local Only"]


def idx(register: int, key_order: str = "contents-first") -> str:
    inner = {"contents": register, "tag": "SCADAPackHoldingRegisterInt16"}
    outer = {"contents": inner, "tag": "SCADAPackIndex"}
    if key_order == "tag-first":
        outer = {"tag": "SCADAPackIndex", "contents": {"tag": inner["tag"], "contents": float(register)}}
    return json.dumps(outer)


def row(pid, register, desc="Synthetic Tag", rw="ReadOnly", dtype="Int16", on_change="", local=False):
    return [pid, idx(register) if isinstance(register, int) else register, desc, rw, dtype, on_change, local]


def xlsx(rows, sheet="Sheet1", headers=HEADERS, padding=0) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["Parameters"])
    ws.append(headers)
    for r in rows:
        ws.append(r)
    for _ in range(padding):  # the export's styled template leaves "" cells below the data
        ws.append([""] * 7)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CURRENT = [row(500001, 17, "Tag A"), row(500002, 18, "Tag B"), row(500003, 19, "Tag C")]


class FakeResponse:
    def __init__(self, status=200, content=b"", url="https://onping.example/x", history=()):
        self.status_code = status
        self.content = content
        self.url = url
        self.history = list(history)

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)


class Server:
    """Fake OnPing: a queue of export bodies and a recorded import POST."""

    def __init__(self, exports, post_status=204, post_body=b""):
        self.exports = list(exports)
        self.gets = []
        self.posts = []
        self.post_status = post_status
        self.post_body = post_body

    def get(self, url, **kw):
        self.gets.append(url)
        return FakeResponse(200, self.exports.pop(0))

    def post(self, url, **kw):
        self.posts.append((url, kw))
        return FakeResponse(self.post_status, self.post_body)


@pytest.fixture
def run(monkeypatch, tmp_path):
    def _run(sheet_rows, exports, *flags, post_status=204, post_body=b"", sheet_bytes=None):
        server = Server(exports, post_status, post_body)
        monkeypatch.setattr(imp.requests, "get", server.get)
        monkeypatch.setattr(imp.requests, "post", server.post)
        path = tmp_path / "edited.xlsx"
        path.write_bytes(sheet_bytes if sheet_bytes is not None else xlsx(sheet_rows))
        monkeypatch.setenv("ONPING_ACCESS_TOKEN", TOKEN)
        argv = [str(LOC), str(path), "--backup", str(tmp_path / "b.xlsx"), *flags]
        code = imp.main(argv)
        return code, server

    return _run


# ------------------------------------------------------------ sheet parsing


def test_export_shape_parses_with_padding_rows():
    rows, errors = imp.parse_sheet(xlsx(CURRENT, padding=50))
    assert errors == []
    assert [r.pid for r in rows] == [500001, 500002, 500003]
    assert rows[0].on_change is None and rows[0].local_only is False


def test_index_key_ignores_key_order_and_integral_floats():
    a = imp.canonical_index(json.loads(idx(17)))
    b = imp.canonical_index(json.loads(idx(17, "tag-first")))
    assert a == b


def test_wrong_sheet_name_is_refused():
    _rows, errors = imp.parse_sheet(xlsx(CURRENT, sheet="Tags"))
    assert "Sheet1" in errors[0]


def test_moved_column_is_refused():
    headers = ["PID", "Description", "Index", "Read/Write", "Data Type", "On Change", "Local Only"]
    _rows, errors = imp.parse_sheet(xlsx(CURRENT, headers=headers))
    assert "row 2" in errors[0]


def test_interior_blank_row_is_refused():
    _rows, errors = imp.parse_sheet(xlsx([CURRENT[0], [None] * 7, CURRENT[1]]))
    assert any("row 4" in e and "blank row" in e for e in errors)


@pytest.mark.parametrize(
    "bad, needle",
    [
        (row("500001", 17), "PID must be a number"),
        (row(500001.5, 17), "whole number"),
        (row(500001, "not json"), "not valid JSON"),
        (row(500001, json.dumps({"tag": "NoSuchIndex", "contents": 1})), "not a modbus-flexible"),
        (row(500001, 17, rw="Writable"), "Read/Write"),
        (row(500001, 17, dtype="Int12"), "Data Type"),
        (row(500001, 17, on_change="5"), "On Change"),
        (row(500001, 17, local="maybe"), "Local Only"),
        (row(500001, 17, desc=True), "Description"),
    ],
)
def test_cell_rules(bad, needle):
    _rows, errors = imp.parse_sheet(xlsx([bad]))
    assert errors and needle in errors[0] and errors[0].startswith("row 3")


def test_cell_rules_accept_server_leniency():
    rows, errors = imp.parse_sheet(
        xlsx([row(500001, 17, desc=42, rw="readwrite", dtype="int16", on_change=0.5, local="TRUE")])
    )
    assert errors == []
    r = rows[0]
    assert (r.description, r.read_write, r.data_type, r.on_change, r.local_only) == (
        "42", "ReadWrite", "Int16", 0.5, True)


# ------------------------------------------------------------ planning


def plan_for(sheet_rows, allow=False):
    sheet, e1 = imp.parse_sheet(xlsx(sheet_rows))
    current, e2 = imp.parse_sheet(xlsx(CURRENT))
    assert e1 == [] and e2 == []
    return imp.make_plan(sheet, current, allow)


def test_unchanged_sheet_is_all_updates():
    plan = plan_for(CURRENT)
    assert len(plan.updates) == 3 and not plan.creates and not plan.replacements
    assert plan.blockers == []


def test_blank_pid_new_index_is_create():
    plan = plan_for(CURRENT + [row(None, 30, "New Tag")])
    assert [r.sheet_row for r in plan.creates] == [6] and plan.blockers == []


def test_changed_index_is_pid_change_and_needs_flag():
    edited = [CURRENT[0], CURRENT[1], row(500003, 40, "Tag C")]
    plan = plan_for(edited)
    assert [r.pid for r, _ in plan.replacements] == [500003]
    assert [c.pid for c in plan.leaving] == [500003]
    assert any("--allow-pid-change" in b for b in plan.blockers)
    assert plan_for(edited, allow=True).blockers == []


def test_duplicate_index_is_refused():
    plan = plan_for(CURRENT + [row(None, 17, "Copy of A")])
    assert any("duplicate Index" in b and "row 6" in b for b in plan.blockers)


def test_blank_pid_on_current_index_is_refused():
    plan = plan_for([CURRENT[0], CURRENT[1], row(None, 19)])
    assert any("blank PID" in b and "500003" in b for b in plan.blockers)


def test_duplicate_pid_is_refused():
    plan = plan_for(CURRENT + [row(500001, 30)])
    assert any("duplicate PID 500001" in b for b in plan.blockers)


def test_coverage_missing_and_unknown():
    assert any("missing from the sheet: [500003]" in b for b in plan_for(CURRENT[:2]).blockers)
    assert any("not on the location: [599999]" in b for b in plan_for(CURRENT + [row(599999, 30)]).blockers)


def test_idec_microsmart_rows_are_refused():
    micro = json.dumps({"tag": "IdecMicroSmartIndex", "contents": {"tag": "X", "contents": 1}})
    plan = plan_for(CURRENT + [row(None, micro)])
    assert any("IdecMicroSmartIndex" in b for b in plan.blockers)


# ------------------------------------------------------------ main / HTTP


def test_preview_sends_no_post(run):
    code, server = run(CURRENT, [xlsx(CURRENT)])
    assert code == 0 and server.posts == []


def test_dry_run_wins_over_yes(run):
    code, server = run(CURRENT, [xlsx(CURRENT)], "--yes", "--dry-run")
    assert code == 0 and server.posts == []


def test_blocked_yes_exits_1_without_post(run):
    code, server = run(CURRENT[:2], [xlsx(CURRENT)], "--yes")
    assert code == 1 and server.posts == []


def test_yes_posts_f1_f2_and_reads_back(run, tmp_path):
    edited = [row(500001, 17, "Tag A renamed"), CURRENT[1], CURRENT[2]]
    code, server = run(edited, [xlsx(CURRENT), xlsx(edited)], "--yes")
    assert code == 0
    (url, kw), = server.posts
    assert url.endswith("/modbus/flexible/import/params")
    assert set(kw["files"]) == {"f1"} and kw["data"] == {"f2": str(LOC)}
    assert "File" not in kw["files"] and "Location" not in kw["data"]
    assert kw["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert (tmp_path / "b.xlsx").read_bytes()[:2] == b"PK"


def test_create_reports_assigned_pid(run, capsys):
    edited = CURRENT + [row(None, 30, "New Tag")]
    after = CURRENT + [row(500010, 30, "New Tag")]
    code, _ = run(edited, [xlsx(CURRENT), xlsx(after)], "--yes")
    assert code == 0
    assert "row 6: PID 500010" in capsys.readouterr().out


def test_server_400_text_is_passed_through(run, capsys):
    msg = json.dumps("Failed to import: overlapping registers")
    code, _ = run(CURRENT, [xlsx(CURRENT)], "--yes", post_status=400, post_body=msg.encode())
    assert code == 1
    assert "Failed to import: overlapping registers" in capsys.readouterr().err


def test_server_403_is_reported_and_nothing_is_claimed_written(run, capsys):
    msg = json.dumps({"error": "Insufficient permissions for this location or group"})
    code, server = run(CURRENT, [xlsx(CURRENT)], "--yes", post_status=403, post_body=msg.encode())
    assert code == 1
    err = capsys.readouterr().err
    assert "HTTP 403" in err and "nothing was confirmed written" in err
    assert len(server.posts) == 1


def test_skill_text_says_the_server_enforces_location_ownership():
    skill = (Path(imp.__file__).parent.parent / "SKILL.md").read_text()
    assert "unless\nthe caller owns one of the location's groups" in skill
    assert "does not check\nownership itself" in skill


def test_read_back_mismatch_exits_1(run, capsys):
    edited = [row(500001, 17, "Tag A renamed"), CURRENT[1], CURRENT[2]]
    code, _ = run(edited, [xlsx(CURRENT), xlsx(CURRENT)], "--yes")
    assert code == 1
    err = capsys.readouterr().err
    assert "Read-back mismatch" in err and "Tag A renamed" in err


def test_read_back_flags_unexpected_and_missing_tags(run, capsys):
    after = [CURRENT[0], CURRENT[1], row(500009, 50)]
    code, _ = run(CURRENT, [xlsx(CURRENT), xlsx(after)], "--yes")
    err = capsys.readouterr().err
    assert code == 1 and "Index not found" in err and "unexpected tag" in err


def test_html_export_means_expired_token(run, capsys):
    code, server = run(CURRENT, [b"<!DOCTYPE html><html>login</html>"])
    assert code == 1 and server.posts == []
    assert "expired" in capsys.readouterr().err


def test_token_is_never_printed(run, capsys):
    run(CURRENT, [xlsx(CURRENT), xlsx(CURRENT)], "--yes")
    out = capsys.readouterr()
    assert TOKEN not in out.out and TOKEN not in out.err
