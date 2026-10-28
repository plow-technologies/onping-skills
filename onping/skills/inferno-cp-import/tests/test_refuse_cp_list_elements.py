"""inferno-cp-import refuses raw /cpInferno/list elements (onping #16220).

The fixture `fixtures/cpinferno-list-all-tags.json` holds one element per tag,
shaped like onping-frontend-types/golden/ReadableControlParameterInferno/*.json
with synthetic ids, names and PIDs. requests.post fails the test if called.
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
SCRIPT = HERE.parent / "scripts" / "import_inferno_cp.py"
spec = importlib.util.spec_from_file_location("import_inferno_cp", SCRIPT)
ici = importlib.util.module_from_spec(spec)
sys.modules["import_inferno_cp"] = ici
spec.loader.exec_module(ici)

FIXTURE_PATH = HERE / "fixtures" / "cpinferno-list-all-tags.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())

FLAT_CP = {
    "cpId": "1001-00000000-0000-4000-8000-00000000c001",
    "name": "Example Casing PSI Daily Avg",
    "inputs": [500012],
    "outputs": {"average": 500013},
    "script": "F" * 43 + "=",
    "trigger": "0 0 1/1 * *",
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("inferno-cp-import sent a request")

    monkeypatch.setattr(ici.requests, "post", boom)


def run_main(monkeypatch, capsys, path: Path, *flags: str):
    monkeypatch.setattr(sys, "argv", ["import_inferno_cp.py", "TOKEN", "--input", str(path), *flags])
    with pytest.raises(SystemExit) as exc:
        ici.main()
    out, err = capsys.readouterr()
    return exc.value.code, out, err


@pytest.mark.parametrize("index", range(len(FIXTURE)), ids=[el["tag"] for el in FIXTURE])
def test_tagged_entry_is_refused_naming_cp_import_json(monkeypatch, capsys, tmp_path, index):
    path = tmp_path / "entry.json"
    path.write_text(json.dumps([copy.deepcopy(FIXTURE[index])]))
    code, out, err = run_main(monkeypatch, capsys, path, "--yes")
    assert code == 1
    assert out == ""
    assert "raw cp-list element" in err
    assert FIXTURE[index]["tag"] in err
    assert "cp-import-json" in err
    assert "missing required field" not in err
    assert "Nothing was sent." in err


def test_orphan_refusal_names_missing_pids(monkeypatch, capsys, tmp_path):
    path = tmp_path / "orphan.json"
    path.write_text(json.dumps([copy.deepcopy(FIXTURE[1])]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--yes")
    assert code == 1
    assert "orphaned CP" in err
    assert "[500015]" in err


def test_whole_cp_list_output_is_refused(monkeypatch, capsys, tmp_path):
    code, _out, err = run_main(monkeypatch, capsys, FIXTURE_PATH, "--yes")
    assert code == 1
    assert "4 of 4 entries are tagged list elements" in err


def test_tagged_entry_after_a_flat_one_is_refused(monkeypatch, capsys, tmp_path):
    path = tmp_path / "mixed.json"
    path.write_text(json.dumps([FLAT_CP, copy.deepcopy(FIXTURE[0])]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 1
    assert "Entry 1 is a raw cp-list element" in err


def test_every_orphan_is_named_even_when_the_first_entry_is_readable(monkeypatch, capsys, tmp_path):
    second = copy.deepcopy(FIXTURE[1])
    second["contents"][1] = [500099]
    path = tmp_path / "list.json"
    path.write_text(json.dumps([copy.deepcopy(FIXTURE[0]), copy.deepcopy(FIXTURE[1]), FIXTURE[2], second]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--yes")
    assert code == 1
    assert "Entry 0 is a raw cp-list element (tag 'ReadableControlParameterInferno')" in err
    assert "2 of them are orphaned CPs" in err
    assert "entry 1 missing output PID(s) [500015]" in err
    assert "entry 3 missing output PID(s) [500099]" in err


def without(entry: dict, *keys: str) -> dict:
    return {key: value for key, value in entry.items() if key not in keys}


def nested(entry: dict) -> dict:
    """FLAT_CP in the nested `{cpId, cpData}` form that cp-import-json normalize emits."""
    return {"cpId": entry["cpId"], "cpData": without(entry, "cpId")}


@pytest.mark.parametrize("trigger", ["absent", None], ids=["absent", "null"])
def test_create_without_trigger_is_accepted(monkeypatch, capsys, tmp_path, trigger):
    """A create (no cpId) may omit the trigger: the server defaults it to OnInputChangeAny."""
    create = without(FLAT_CP, "cpId", "trigger")
    if trigger is None:
        create["trigger"] = None
    path = tmp_path / "create.json"
    path.write_text(json.dumps([create]))
    code, out, _err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 0
    assert "trigger=<default: OnInputChangeAny>" in out


@pytest.mark.parametrize("shape", ["flat", "nested"])
@pytest.mark.parametrize("trigger", ["absent", None], ids=["absent", "null"])
def test_update_without_trigger_is_accepted(monkeypatch, capsys, tmp_path, shape, trigger):
    """In the friendly format a missing trigger IS OnInputChangeAny (ControlParametersInferno.hs).

    /cpInferno/export/json omits it, so an update with no trigger must round-trip.
    """
    update = without(FLAT_CP, "trigger")
    if trigger is None:
        update["trigger"] = None
    entry = nested(update) if shape == "nested" else update
    path = tmp_path / "update.json"
    path.write_text(json.dumps([entry]))
    code, out, err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 0, err
    assert FLAT_CP["cpId"] in out
    assert "trigger=<default: OnInputChangeAny>" in out


def test_update_with_explicit_default_trigger_is_accepted(monkeypatch, capsys, tmp_path):
    update = dict(FLAT_CP, trigger={"tag": "OnInputChange", "contents": {"tag": "OnInputChangeAny"}})
    path = tmp_path / "update.json"
    path.write_text(json.dumps([update]))
    code, out, _err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 0
    assert "OnInputChangeAny" in out


def test_entry_missing_name_is_accepted(monkeypatch, capsys, tmp_path):
    """The server defaults name to "" (NewOrExistingControlParameterInferno2)."""
    path = tmp_path / "flat.json"
    path.write_text(json.dumps([without(FLAT_CP, "name"), without(nested(FLAT_CP)["cpData"], "name")]))
    code, out, _err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 0
    assert out.count("name=''") == 2


def test_nested_entry_is_accepted(monkeypatch, capsys, tmp_path):
    path = tmp_path / "nested.json"
    path.write_text(json.dumps([nested(FLAT_CP)]))
    code, out, _err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 0
    assert FLAT_CP["cpId"] in out
    assert f"name={FLAT_CP['name']!r}" in out
    assert "trigger='0 0 1/1 * *'" in out


def test_nested_entry_missing_a_field_is_refused(monkeypatch, capsys, tmp_path):
    entry = nested(FLAT_CP)
    del entry["cpData"]["script"]
    path = tmp_path / "nested.json"
    path.write_text(json.dumps([entry]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 1
    assert "missing required field(s): ['script']" in err


def test_cpdata_that_is_not_an_object_is_refused(monkeypatch, capsys, tmp_path):
    path = tmp_path / "nested.json"
    path.write_text(json.dumps([{"cpId": FLAT_CP["cpId"], "cpData": "x"}]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 1
    assert "cpData that is not a JSON object" in err


def test_generic_cpid_object_is_accepted_and_deduplicated(monkeypatch, capsys, tmp_path):
    """The server falls back to the generic CPID object; duplicates are caught across both forms."""
    generic = dict(FLAT_CP, cpId={"engineHost": 1001, "perEngineId": "00000000-0000-4000-8000-00000000c001"})
    path = tmp_path / "generic.json"
    path.write_text(json.dumps([generic]))
    code, out, _err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 0
    assert "ljSerial 1001" in out and FLAT_CP["cpId"] in out
    path.write_text(json.dumps([generic, FLAT_CP]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 1
    assert "duplicate cpId(s)" in err


UUID = "00000000-0000-4000-8000-00000000c001"


@pytest.mark.parametrize(
    "cp_id, text",
    [
        (f"1001-{UUID}", f"1001-{UUID}"),
        (f"1001-{UUID.upper()}", f"1001-{UUID}"),  # Data.UUID parses either case
        ({"engineHost": 1001, "perEngineId": UUID}, f"1001-{UUID}"),
        ({"engineHost": "1001", "perEngineId": UUID}, f"1001-{UUID}"),  # parseJSONSafe
        ({"engineHost": 1001, "perEngineId": UUID, "extra": 1}, f"1001-{UUID}"),  # generic FromJSON ignores it
    ],
)
def test_cp_id_text_accepts_what_the_server_parses(cp_id, text):
    assert ici._cp_id_text(cp_id) == text


@pytest.mark.parametrize(
    "cp_id",
    [
        "1001-abc",  # fewer than six parts
        "1001-a-b-c-d-e",  # the last five parts are not a UUID
        f"x-{UUID}",  # the host is not an integer
        f"-{UUID}",  # empty host
        "1001-00000000-0000-4000-8000-00000000g001",  # not hex
        {"engineHost": 1001},  # no perEngineId
        {"engineHost": True, "perEngineId": UUID},
        {"engineHost": 1001, "perEngineId": "not-a-uuid"},
        1001,
    ],
)
def test_cp_id_text_rejects_what_the_server_rejects(cp_id):
    assert ici._cp_id_text(cp_id) is None


def test_malformed_cpid_is_refused(monkeypatch, capsys, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([dict(FLAT_CP, cpId="1001-a-b-c-d-e")]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 1
    assert "malformed cpId '1001-a-b-c-d-e'" in err


def test_generic_cpid_with_extra_keys_dedupes_against_upper_case_friendly(monkeypatch, capsys, tmp_path):
    generic = dict(FLAT_CP, cpId={"engineHost": 1001, "perEngineId": UUID, "extra": True})
    upper = dict(FLAT_CP, cpId=f"1001-{UUID.upper()}")
    path = tmp_path / "dupes.json"
    path.write_text(json.dumps([generic, upper]))
    code, _out, err = run_main(monkeypatch, capsys, path, "--dry-run")
    assert code == 1
    assert f"duplicate cpId(s) in the file: ['1001-{UUID}']" in err


@pytest.mark.parametrize("value", [f"1001-{UUID}", {"ACPID": {"engineHost": 1001, "perEngineId": UUID}}, 1001])
def test_dhall_cp_id_or_serial_key_is_refused(monkeypatch, capsys, tmp_path, value):
    """The JSON import reads only cpId (ControlParametersInferno.hs): cpIdOrSerial would become a create."""
    entry = dict(without(FLAT_CP, "cpId"), cpIdOrSerial=value)
    path = tmp_path / "dhall-key.json"
    path.write_text(json.dumps([entry]))
    code, out, err = run_main(monkeypatch, capsys, path, "--yes")
    assert code == 1
    assert out == ""
    assert "cpIdOrSerial" in err and "would be imported as a new CP" in err
    assert "Nothing was sent." in err


def test_flat_entry_still_previews(monkeypatch, capsys, tmp_path):
    path = tmp_path / "flat.json"
    path.write_text(json.dumps([FLAT_CP]))
    code, out, _err = run_main(monkeypatch, capsys, path)
    assert code == 0
    assert FLAT_CP["cpId"] in out


GOLDEN_DIR = os.environ.get("ONPING_FRONTEND_TYPES_GOLDEN")


@pytest.mark.skipif(not GOLDEN_DIR, reason="set ONPING_FRONTEND_TYPES_GOLDEN to the upstream golden dir")
def test_upstream_golden_orphan_is_refused(monkeypatch, capsys, tmp_path):
    golden = json.loads(
        (Path(GOLDEN_DIR) / "ReadableControlParameterInferno" / "OrphanedControlParameterInferno.json").read_text()
    )["samples"]
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(golden))
    code, _out, err = run_main(monkeypatch, capsys, path, "--yes")
    assert code == 1
    assert "OrphanedControlParameterInferno" in err
    assert "cp-import-json" in err
    assert json.dumps(golden[0]["contents"][1]) in err
