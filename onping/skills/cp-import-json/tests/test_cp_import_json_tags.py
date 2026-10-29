"""cp-import-json against the /cpInferno/list tagged union (onping #16220).

The fixture `fixtures/cpinferno-list-all-tags.json` holds one element per tag,
shaped like onping-frontend-types/golden/ReadableControlParameterInferno/*.json
with synthetic ids, names and PIDs. No network: requests.post is faked.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "cp_import_json.py"
spec = importlib.util.spec_from_file_location("cp_import_json", SCRIPT)
cij = importlib.util.module_from_spec(spec)
sys.modules["cp_import_json"] = cij
spec.loader.exec_module(cij)

FIXTURE_PATH = HERE / "fixtures" / "cpinferno-list-all-tags.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())
READABLE, ORPHAN, PROHIBITED, FAILED = FIXTURE
READABLE_CPID = "1001-00000000-0000-4000-8000-00000000c001"
ORPHAN_CPID = "1001-00000000-0000-4000-8000-00000000c002"
PROHIBITED_CPID = "1001-00000000-0000-4000-8000-00000000c003"
FAILED_CPID = "1001-00000000-0000-4000-8000-00000000c004"


class FakeResponse:
    def __init__(self, body):
        self.status_code = 200
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


def run_main(monkeypatch, capsys, argv, bodies: dict[int, list] | None = None):
    if bodies is not None:
        monkeypatch.setattr(
            cij.requests, "post", lambda url, data, **_kw: FakeResponse(bodies[int(data)])
        )
    monkeypatch.setattr(sys, "argv", ["cp_import_json.py", *argv])
    with pytest.raises(SystemExit) as exc:
        cij.main()
    out, err = capsys.readouterr()
    return exc.value.code, out, err


def cp_ids_in(doc) -> list[str]:
    """cpIds of every CP in a document, nested (`{cpId, cpData}`) or flat."""
    return [(container or cp).get("cpId") for _path, cp, container in cij.collect_cp_entries(doc)]


# --- normalize / fetch-normalize ------------------------------------------------


def test_fetch_normalize_omits_orphan_by_default(monkeypatch, capsys):
    code, out, err = run_main(
        monkeypatch, capsys, ["fetch-normalize", "TOKEN", "1001"], {1001: copy.deepcopy(FIXTURE)}
    )
    assert code == 0
    doc = json.loads(out)
    # Readable unwrapped to its {cpId, cpData}; orphan omitted; prohibited/failed dropped.
    assert len(doc) == 1
    assert set(doc[0]) == {"cpId", "cpData"}
    assert doc[0]["cpId"] == READABLE_CPID
    assert "omitted 1 orphaned CP(s)" in err
    assert ORPHAN_CPID in err
    assert '"Example Orphaned Passthrough"' in err
    assert "[500015]" in err


def test_fetch_normalize_include_orphans_keeps_it(monkeypatch, capsys):
    code, out, err = run_main(
        monkeypatch,
        capsys,
        ["fetch-normalize", "TOKEN", "1001", "--include-orphans"],
        {1001: copy.deepcopy(FIXTURE)},
    )
    assert code == 0
    doc = json.loads(out)
    assert cp_ids_in(doc) == [READABLE_CPID, ORPHAN_CPID]
    assert all(set(cp) == {"cpId", "cpData"} for cp in doc)
    assert doc[1]["cpData"]["outputs"] == 500015
    assert "kept 1 orphaned CP(s)" in err
    assert ORPHAN_CPID in err


def test_fetch_normalize_multiple_lumberjacks(monkeypatch, capsys):
    bodies = {1001: [copy.deepcopy(READABLE)], 1002: [copy.deepcopy(ORPHAN)]}
    code, out, err = run_main(monkeypatch, capsys, ["fetch-normalize", "TOKEN", "1001", "1002"], bodies)
    assert code == 0
    doc = json.loads(out)
    assert doc["1002"] == []
    assert cp_ids_in(doc) == [READABLE_CPID]
    assert '$.1002[0] ' + ORPHAN_CPID in err


def test_normalize_file_omits_orphan(monkeypatch, capsys):
    code, out, err = run_main(monkeypatch, capsys, ["normalize", "--input", str(FIXTURE_PATH)])
    assert code == 0
    assert cp_ids_in(json.loads(out)) == [READABLE_CPID]
    assert ORPHAN_CPID in err


def test_normalize_unwraps_readable_into_the_server_import_shape(capsys):
    """Friendly cpId plus nested cpData: NewOrExistingControlParameterInferno2 reads `cpData`."""
    [entry] = cij.normalize_list_document_status([copy.deepcopy(READABLE)])[0]
    expected = {
        "cpId": READABLE_CPID,
        "cpData": cij.normalize_cp_data(READABLE["contents"]["cpData"]),
    }
    assert entry == expected
    assert entry["cpData"]["outputs"] == {"average": 500013}
    assert entry["cpData"]["trigger"] == "0 0 1/1 * *"
    # NoRetries is the server default retry strategy (Types.hs), so it is omitted.
    assert "calculateRetryStrategy" not in entry["cpData"]
    assert "writeRetryStrategy" not in entry["cpData"]
    assert capsys.readouterr().err == ""


def test_record_output_keyed_scalar_output_is_normalised_once(capsys):
    """One transform pass: a record output with a key named ScalarOutput stays a record."""
    readable = copy.deepcopy(READABLE)
    readable["contents"]["cpData"]["outputs"] = {"tag": "RecordOutput", "contents": {"ScalarOutput": 500013}}
    [entry] = cij.normalize_list_document_status([readable])[0]
    assert entry["cpData"]["outputs"] == {"ScalarOutput": 500013}


GENERIC_DEFAULT_TRIGGER = {"tag": "OnInputChange", "contents": {"tag": "OnInputChangeAny"}}


@pytest.mark.parametrize("cp_id_key", ["cpId", "cpIdOrSerial", None])
def test_default_trigger_is_omitted_on_create_and_update(capsys, cp_id_key):
    """The server's friendly ToJSON omits OnInputChangeAny (ControlParametersInferno.hs).

    The import reads it back, for a create and an update alike.
    """
    readable = copy.deepcopy(READABLE)
    readable["contents"]["cpData"]["trigger"] = copy.deepcopy(GENERIC_DEFAULT_TRIGGER)
    [entry] = cij.normalize_list_document_status([readable])[0]
    assert "trigger" not in entry["cpData"]
    flat = dict(readable["contents"]["cpData"])
    if cp_id_key is not None:
        flat[cp_id_key] = READABLE_CPID
    assert "trigger" not in cij.transform_document(flat, mode="normalize")
    assert "trigger" not in cij.transform_document({"cpData": flat}, mode="normalize")["cpData"]


def test_noretries_is_the_default_retry_strategy():
    """control-parameters-types ControlParameters/Types.hs: defaultRetryStrategy = NoRetries."""
    assert cij.is_default_retry_strategy({"tag": "NoRetries"})
    assert cij.is_default_retry_strategy("default")
    assert not cij.is_default_retry_strategy(
        {"tag": "ConstantDelayRetryStrategy", "contents": {"maxRetries": 3, "interval": 10}}
    )
    expanded = cij.expand_cp_data({"inputs": [1], "outputs": 2, "script": "S"})
    assert expanded["calculateRetryStrategy"] == {"tag": "NoRetries"}
    assert expanded["writeRetryStrategy"] == {"tag": "NoRetries"}


def test_normalize_then_expand_gives_generic_fields_back(capsys):
    normalized = cij.normalize_list_document_status(copy.deepcopy(FIXTURE))[0]
    [entry] = cij.transform_document(normalized, mode="expand")
    assert entry["cpId"] == READABLE["contents"]["cpId"]
    assert entry["cpData"]["outputs"] == {"RecordOutput": {"average": 500013}}
    assert entry["cpData"]["resolution"] == 1024
    assert entry["cpData"]["calculateRetryStrategy"] == {"tag": "NoRetries"}


def test_friendly_cpid_splits_like_the_server():
    """The UUID is the last five '-' parts (parseJSONFriendlyCPIDString), not the last one."""
    assert cij.parse_friendly_cpid(READABLE_CPID) == (1001, "00000000-0000-4000-8000-00000000c001")
    assert cij.parse_friendly_cpid("1001-ABCDEF00-0000-4000-8000-00000000C001") == (
        1001,
        "ABCDEF00-0000-4000-8000-00000000C001",
    )
    assert cij.parse_friendly_cpid("1001-abc") is None


@pytest.mark.parametrize(
    "text",
    [
        "x-00000000-0000-4000-8000-00000000c001",  # host is not an integer
        "1001-a-b-c-d-e",  # six parts, but the last five are not a UUID
        "1001-00000000-0000-4000-8000-00000000g001",  # not hex
        "1001-0000000-00000-4000-8000-00000000c001",  # wrong group lengths
        "-00000000-0000-4000-8000-00000000c001",  # empty host
    ],
)
def test_friendly_cpid_rejects_what_the_server_rejects(text):
    assert cij.parse_friendly_cpid(text) is None


def test_strict_validate_accepts_normalised_cp_list_output(capsys):
    normalized = cij.normalize_list_document_status(copy.deepcopy(FIXTURE))[0]
    report = cij.validate_document(normalized, strict=True)
    assert report["ok"] is True, report["errors"]


def test_normalize_is_idempotent_on_its_own_output(capsys):
    once = cij.normalize_list_document_status(copy.deepcopy(FIXTURE))[0]
    assert cij.normalize_list_document_status(copy.deepcopy(once))[0] == once


def test_normalize_drops_not_readable_with_a_notice_per_element(capsys):
    doc = cij.normalize_list_document_status([copy.deepcopy(PROHIBITED), copy.deepcopy(FAILED)])[0]
    assert doc == []
    err = capsys.readouterr().err
    assert "omitted 2 not-readable element(s)" in err
    assert f"$[0] prohibited (no read permission): {PROHIBITED_CPID}" in err
    assert f"$[1] failed permission lookup: {FAILED_CPID}" in err


def test_normalize_flags_and_drops_unknown_tags(capsys):
    unknown = {"tag": "SomeFutureControlParameterInferno", "contents": {"x": 1}}
    doc = cij.normalize_list_document_status([copy.deepcopy(READABLE), unknown])[0]
    assert cp_ids_in(doc) == [READABLE_CPID]
    err = capsys.readouterr().err
    assert "omitted 1 element(s) with an unknown tag" in err
    assert "$[1] unknown tag: SomeFutureControlParameterInferno" in err


def test_unknown_tag_inside_a_cp_is_not_a_list_element():
    """Tagged outputs/triggers inside a CP object are CP fields, not list elements."""
    flat = {"inputs": [1], "outputs": {"tag": "ScalarOutput", "contents": 2}, "script": "S"}
    assert cij.scan_list_document([flat])[1] == []


def test_dropped_orphan_live_outputs_are_reported(capsys):
    """An orphan that still claims a live output PID: listed, and a collision is warned."""
    orphan = copy.deepcopy(ORPHAN)
    orphan["contents"][0]["cpData"]["outputs"] = {
        "tag": "RecordOutput",
        "contents": {"gone": 500015, "live": 500013},
    }
    cij.normalize_list_document_status([copy.deepcopy(READABLE), orphan])[0]
    err = capsys.readouterr().err
    assert "still claims live output PIDs [500013]" in err
    assert f"output PID 500013 at $[0].cpData is also claimed by omitted orphan {ORPHAN_CPID} ($[1])" in err


def test_normalize_and_validate_see_the_same_orphans(capsys):
    """One walker: normalize and validate find the same orphan paths."""
    doc = {"1001": copy.deepcopy(FIXTURE), "1002": [copy.deepcopy(ORPHAN)]}
    _import_doc, elements = cij.scan_list_document(copy.deepcopy(doc))
    scanned = [el.path for el in elements if el.tag == cij.ORPHANED_TAG]
    report = cij.validate_document(doc)
    flagged = [w["path"] for w in report["warnings"] if w["code"] == "orphaned_cp"]
    assert scanned == flagged == ["$.1001[1]", "$.1002[0]"]
    cij.normalize_list_document_status(copy.deepcopy(doc))[0]
    err = capsys.readouterr().err
    assert all(path in err for path in scanned)


def test_orphan_without_cpid_is_malformed_and_prints_unparsed(monkeypatch, capsys, tmp_path):
    """Without a cpId the entry would be a create, so it is dropped and normalize exits 1."""
    orphan = copy.deepcopy(ORPHAN)
    del orphan["contents"][0]["cpId"]
    path = tmp_path / "list.json"
    path.write_text(json.dumps([copy.deepcopy(READABLE), orphan]))
    code, out, err = run_main(monkeypatch, capsys, ["normalize", "--include-orphans", "--input", str(path)])
    assert code == 1
    assert cp_ids_in(json.loads(out)) == [READABLE_CPID]
    assert "dropped 1 malformed element(s)" in err
    assert "$[1] OrphanedControlParameterInferno <unparsed>: no cpId" in err


@pytest.mark.parametrize(
    "contents",
    [{"cpId": READABLE["contents"]["cpId"]}, {"cpId": READABLE["contents"]["cpId"], "cpData": "x"}, 7],
    ids=["no-cpData", "cpData-not-object", "not-an-object"],
)
def test_readable_without_usable_cpdata_is_dropped_and_exits_1(monkeypatch, capsys, tmp_path, contents):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([copy.deepcopy(READABLE), {"tag": cij.READABLE_TAG, "contents": contents}]))
    code, out, err = run_main(monkeypatch, capsys, ["normalize", "--input", str(path)])
    assert code == 1
    doc = json.loads(out)
    assert cp_ids_in(doc) == [READABLE_CPID]
    assert all("tag" not in entry for entry in doc)
    assert "dropped 1 malformed element(s)" in err
    assert "$[1] ReadableControlParameterInferno" in err


def test_fetch_normalize_exits_1_on_a_malformed_element(monkeypatch, capsys):
    body = [copy.deepcopy(READABLE), {"tag": cij.READABLE_TAG, "contents": {"cpId": None}}]
    code, out, err = run_main(monkeypatch, capsys, ["fetch-normalize", "TOKEN", "1001"], {1001: body})
    assert code == 1
    assert cp_ids_in(json.loads(out)) == [READABLE_CPID]
    assert "malformed" in err


def test_normalize_without_tags_is_unchanged_and_quiet(capsys):
    flat = [{"cpId": READABLE_CPID, **cij.normalize_cp_data(READABLE["contents"]["cpData"])}]
    assert cij.normalize_list_document_status(copy.deepcopy(flat))[0] == cij.transform_document(flat, mode="normalize")
    assert capsys.readouterr().err == ""


def test_expand_does_not_share_default_retry_dicts():
    """Each expanded CP gets its own copy of the NoRetries default."""
    first = cij.expand_cp_data({"inputs": [1], "outputs": 2, "script": "S"})
    second = cij.expand_cp_data({"inputs": [1], "outputs": 3, "script": "S"})
    assert first["calculateRetryStrategy"] is not second["calculateRetryStrategy"]
    assert first["writeRetryStrategy"] is not cij.DEFAULTS["writeRetryStrategy"]
    first["calculateRetryStrategy"]["tag"] = "Mutated"
    assert second["calculateRetryStrategy"] == {"tag": "NoRetries"}
    assert cij.DEFAULTS["calculateRetryStrategy"] == {"tag": "NoRetries"}


def test_dropped_element_under_the_root_object_is_removed(monkeypatch, capsys, tmp_path):
    """A dropped element that is an object value goes with its key, never left as null."""
    doc = {"a": copy.deepcopy(PROHIBITED), "b": [copy.deepcopy(READABLE)], "c": copy.deepcopy(ORPHAN)}
    path = tmp_path / "list.json"
    path.write_text(json.dumps(doc))
    code, out, err = run_main(monkeypatch, capsys, ["normalize", "--input", str(path)])
    assert code == 0
    result = json.loads(out)
    assert set(result) == {"b"}
    assert cp_ids_in(result) == [READABLE_CPID]
    assert f"$.a prohibited (no read permission): {PROHIBITED_CPID}" in err
    assert "$.c " + ORPHAN_CPID in err


def test_readable_under_the_root_object_is_kept(capsys):
    doc, ok = cij.normalize_list_document_status({"a": copy.deepcopy(READABLE)})
    assert ok
    assert doc == {"a": cij.normalize_list_document_status([copy.deepcopy(READABLE)])[0][0]}


@pytest.mark.parametrize("root", [PROHIBITED, FAILED, ORPHAN, {"tag": cij.READABLE_TAG, "contents": 7}])
def test_dropped_root_outputs_an_empty_array_and_exits_1(monkeypatch, capsys, tmp_path, root):
    path = tmp_path / "list.json"
    path.write_text(json.dumps(root))
    code, out, err = run_main(monkeypatch, capsys, ["normalize", "--input", str(path)])
    assert code == 1
    assert json.loads(out) == []
    assert "the document root is itself a list element that was not kept" in err


def test_kept_root_element_exits_0(capsys):
    doc, ok = cij.normalize_list_document_status(copy.deepcopy(READABLE))
    assert ok
    assert doc["cpId"] == READABLE_CPID
    doc, ok = cij.normalize_list_document_status(copy.deepcopy(ORPHAN), include_orphans=True)
    assert ok
    assert doc["cpId"] == ORPHAN_CPID


def test_malformed_orphan_is_counted_once_and_the_same_by_validate_and_normalize(capsys):
    orphan = copy.deepcopy(ORPHAN)
    del orphan["contents"][0]["cpId"]
    doc = [copy.deepcopy(READABLE), orphan, copy.deepcopy(ORPHAN)]
    report = cij.validate_document(copy.deepcopy(doc))
    codes = [f["code"] for f in report["errors"] + report["warnings"]]
    assert codes.count("malformed_element") == 1
    assert codes.count("orphaned_cp") == 1
    assert report["stats"]["malformedElements"] == 1
    assert report["stats"]["orphanedControlParameters"] == 1
    _result, ok = cij.normalize_list_document_status(copy.deepcopy(doc))
    assert not ok
    err = capsys.readouterr().err
    assert "omitted 1 orphaned CP(s)" in err
    assert "dropped 1 malformed element(s)" in err


def test_expand_is_not_filtered():
    assert len(cij.transform_document(copy.deepcopy(FIXTURE), mode="expand")) == 4


# --- validate -------------------------------------------------------------------


def test_validate_scan_builds_no_import_document():
    import_doc, elements = cij.scan_list_document(copy.deepcopy(FIXTURE), build=False)
    assert import_doc is None
    assert [el.tag for el in elements] == [el["tag"] for el in FIXTURE]
    assert elements[1].orphan is not None


def test_validate_flags_a_malformed_element(monkeypatch, tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([READABLE, {"tag": cij.READABLE_TAG, "contents": {"cpId": None}}]))
    code, out, _err = run_main(monkeypatch, capsys, ["validate", "--strict", "--input", str(path)])
    report = json.loads(out)
    assert code == 1
    found = [e for e in report["errors"] if e["code"] == "malformed_element"]
    assert [e["path"] for e in found] == ["$[1]"]
    assert report["stats"]["malformedElements"] == 1


def test_validate_unknown_tag(monkeypatch, tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([READABLE, {"tag": "SomeFutureTag", "contents": 1}]))
    code, out, _err = run_main(monkeypatch, capsys, ["validate", "--strict", "--input", str(path)])
    report = json.loads(out)
    assert code == 1
    found = [e for e in report["errors"] if e["code"] == "unknown_tag"]
    assert len(found) == 1
    assert found[0]["path"] == "$[1]"
    assert "SomeFutureTag" in found[0]["message"]
    assert report["stats"]["unknownTags"] == 1


def test_validate_reports_orphan_as_warning(monkeypatch, capsys):
    code, out, _err = run_main(monkeypatch, capsys, ["validate", "--input", str(FIXTURE_PATH)])
    report = json.loads(out)
    assert code == 0
    assert report["ok"] is True
    orphan = [w for w in report["warnings"] if w["code"] == "orphaned_cp"]
    assert len(orphan) == 1
    assert orphan[0]["path"] == "$[1]"
    assert "[500015]" in orphan[0]["message"]
    assert ORPHAN_CPID in orphan[0]["message"]
    assert report["stats"]["orphanedControlParameters"] == 1


def test_strict_validate_meets_an_orphan(monkeypatch, tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([READABLE, ORPHAN]))
    code, out, _err = run_main(monkeypatch, capsys, ["validate", "--strict", "--input", str(path)])
    report = json.loads(out)
    assert code == 1
    assert report["ok"] is False
    orphan = [e for e in report["errors"] if e["code"] == "orphaned_cp"]
    assert len(orphan) == 1
    assert orphan[0]["path"] == "$[1]"
    assert "[500015]" in orphan[0]["message"]


def test_validate_prohibited_element(monkeypatch, tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([READABLE, PROHIBITED]))
    code, out, _err = run_main(monkeypatch, capsys, ["validate", "--input", str(path)])
    report = json.loads(out)
    assert code == 0
    found = [w for w in report["warnings"] if w["code"] == "not_readable"]
    assert len(found) == 1
    assert found[0]["path"] == "$[1]"
    assert PROHIBITED_CPID in found[0]["message"]
    assert "ProhibitedReadControlParameterInferno" in found[0]["message"]


def test_validate_failed_permission_element(monkeypatch, tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([FAILED]))
    code, out, _err = run_main(monkeypatch, capsys, ["validate", "--strict", "--input", str(path)])
    report = json.loads(out)
    assert code == 1
    found = [e for e in report["errors"] if e["code"] == "not_readable"]
    assert len(found) == 1
    assert FAILED_CPID in found[0]["message"]
    assert report["stats"]["notReadable"] == 1


def test_validate_readable_only_has_no_tag_findings():
    report = cij.validate_document([copy.deepcopy(READABLE)])
    assert report["ok"] is True
    assert report["warnings"] == []
    assert report["stats"]["orphanedControlParameters"] == 0
    assert report["stats"]["notReadable"] == 0


def test_collect_cp_entries_still_walks_into_orphans():
    """Baseline from the wire contract: the orphan's cp is found at contents[0]."""
    paths = [path for path, _cp, _container in cij.collect_cp_entries(FIXTURE)]
    assert paths == ["$[0].contents.cpData", "$[1].contents[0].cpData"]


GOLDEN_DIR = os.environ.get("ONPING_FRONTEND_TYPES_GOLDEN")


@pytest.mark.skipif(not GOLDEN_DIR, reason="set ONPING_FRONTEND_TYPES_GOLDEN to the upstream golden dir")
def test_upstream_golden_orphans_are_dropped_and_flagged(capsys):
    golden = json.loads(
        (Path(GOLDEN_DIR) / "ReadableControlParameterInferno" / "OrphanedControlParameterInferno.json").read_text()
    )["samples"]
    assert cij.normalize_list_document_status(copy.deepcopy(golden))[0] == []
    kept = cij.normalize_list_document_status(copy.deepcopy(golden), include_orphans=True)[0]
    assert len(kept) == len(golden) and all(set(cp) == {"cpId", "cpData"} for cp in kept)
    err = capsys.readouterr().err
    assert f"omitted {len(golden)} orphaned CP(s)" in err
    report = cij.validate_document(golden, strict=True)
    codes = [e["code"] for e in report["errors"]]
    assert codes.count("orphaned_cp") == len(golden)
    for index, sample in enumerate(golden):
        finding = [e for e in report["errors"] if e["code"] == "orphaned_cp"][index]
        assert finding["path"] == f"$[{index}]"
        assert json.dumps(sample["contents"][1]) in finding["message"]
