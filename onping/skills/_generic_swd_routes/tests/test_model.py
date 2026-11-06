"""Offline tests for _generic_swd_routes.model (validation, edits, diff, backups).

    uv run --with pytest --with requests pytest onping/skills/_generic_swd_routes/tests
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gswd_fakes as fx  # noqa: E402
from _generic_swd_routes import model  # noqa: E402


def good() -> dict:
    return model.from_wire(fx.base_config())


def errors_of(m: dict) -> list[str]:
    return model.validate(m)[0]


def test_base_config_is_valid():
    assert model.validate(good()) == ([], [])


def test_round_trip_is_canonical():
    m = good()
    assert model.from_wire(model.to_wire(m)) == model.from_wire(model.to_wire(model.from_wire(model.to_wire(m))))
    assert model.canonical(m) == model.canonical(model.from_wire(model.to_wire(m)))


def test_to_wire_sends_every_lane_param_field_and_sorts():
    m = model.lane_add(good(), 0, fx.READ_2, fx.WRITE_2, 2)
    wire = model.to_wire(m)
    assert [ln["frontendLaneNumber"] for ln in wire["frontendConfigLanes"]] == [0, 1]
    assert set(wire["frontendConfigLanes"][0]["frontendLaneReadPID"]) == {
        "laneParamPID", "laneParamName", "laneParamRawValue", "laneParamMaskedValue", "laneParamStatus"}
    assert wire["frontendConfigLanes"][0]["frontendLaneWriteWaitingToStartVal"] == 2.0


def test_enrichment_is_not_compared():
    cfg = fx.base_config()
    cfg["frontendConfigLanes"][0]["frontendLaneReadPID"]["laneParamRawValue"] = 5.0
    assert model.canonical(model.from_wire(cfg)) == model.canonical(good())


@pytest.mark.parametrize("name", ["", "   ", "x" * 201, "bad\x01name"])
def test_bad_names(name):
    assert any(e.startswith("name:") for e in errors_of(model.name_set(good(), name)))


def test_no_lanes_refused():
    m = good()
    m["lanes"] = []
    assert any("at least one lane" in e for e in errors_of(m))


@pytest.mark.parametrize("number", [-1, 2**64, 1.5, True, "1"])
def test_bad_lane_numbers(number):
    m = good()
    m["lanes"][0]["number"] = number
    assert any("lane number" in e for e in errors_of(m))


def test_duplicate_lane_numbers():
    m = good()
    m["lanes"].append(dict(m["lanes"][0]))
    assert any("used twice" in e for e in errors_of(m))


@pytest.mark.parametrize("pid", [0, -5, 1.0, None, True])
def test_bad_pids(pid):
    m = good()
    m["lanes"][0]["write_pid"] = pid
    assert any("write PID must be a positive integer" in e for e in errors_of(m))


def test_same_read_and_write_pid_is_a_warning():
    m = model.lane_set(good(), 1, write_pid=fx.READ_1)
    errs, warns = model.validate(m)
    assert errs == [] and any("same PID" in w for w in warns)


@pytest.mark.parametrize("wait", [float("nan"), float("inf"), None, "1", True])
def test_bad_wait_values(wait):
    m = good()
    m["lanes"][0]["wait"] = wait
    assert any("waiting-to-start" in e for e in errors_of(m))


@pytest.mark.parametrize("script,needle", [
    ("output := (input1 * 2;", "unbalanced parentheses"),
    ("output := input1 / 10.0);", "unbalanced parentheses"),
    ('output := "abc;', "unterminated string"),
    ("x := input1;", "never assigns output"),
    ("output := input1;\x07", "control character"),
    ("output := input1;" + " " * model.MAX_SCRIPT, "limit is"),
])
def test_bad_scripts(script, needle):
    m = model.lane_set(good(), 1, script=script)
    assert any(needle in e for e in errors_of(m)), errors_of(m)


@pytest.mark.parametrize("script", ["", "output := input1 / 10.0;", 'x := "(";\noutput := ((x));\n',
                                    "y := input1;\n\toutput:= y;"])
def test_good_scripts(script):
    assert errors_of(model.lane_set(good(), 1, script=script)) == []


def test_status_map_duplicates_refused():
    m = good()
    m["status_map"].append([1, "Pumping"])
    assert any("appears twice" in e for e in errors_of(m))


@pytest.mark.parametrize("status", ["Disabled", "available", {"disabled": ""}, {"disabled": 3},
                                    {"disabled": "x", "extra": 1}, None, {"disabled": "x" * 201}])
def test_bad_statuses(status):
    m = model.status_set(good(), 9, status)
    assert errors_of(m), status


@pytest.mark.parametrize("value", [float("nan"), "1", None])
def test_bad_status_values(value):
    m = good()
    m["status_map"].append([value, "Available"])
    assert any("finite number" in e for e in errors_of(m))


@pytest.mark.parametrize("missing", ["Available", "WaitingToStart", "Pumping"])
def test_status_map_needs_the_three_offload_statuses(missing):
    m = good()
    m["status_map"] = [p for p in m["status_map"] if p[1] != missing]
    assert any(f"maps to {missing}" in e for e in errors_of(m))


def test_edits_and_diff():
    m = good()
    m2 = model.status_set(model.lane_add(model.name_set(m, "Renamed"), 2, fx.READ_2, fx.WRITE_2, 1.0),
                          4, {"disabled": "Bay closed"})
    d = model.diff(m, m2)
    assert 'name: "Example kiosk" -> "Renamed"' in d
    assert any(line.startswith("+ lane 2:") for line in d)
    assert "+ status 4: Disabled('Bay closed')" in d
    assert model.touched(m, m2) == {2: {"new": True, "read": True, "write": True, "script": True}}
    m3 = model.lane_set(m2, 1, read_pid=fx.READ_2)
    assert model.touched(m2, m3)[1]["read"] is True and model.touched(m2, m3)[1]["write"] is False
    assert model.diff(m3, model.lane_delete(m3, 2))[0].startswith("- lane 2:")
    assert model.diff(m2, model.status_delete(m2, 4)) == ["- status 4: Disabled('Bay closed')"]
    assert model.diff(m2, model.status_set(m2, 0, "Pumping")) == ["status 0: Available -> Pumping"]


@pytest.mark.parametrize("edit", [
    lambda m: model.lane_set(m, 7, read_pid=1),
    lambda m: model.lane_add(m, 1, 1, 2, 1.0),
    lambda m: model.lane_delete(m, 7),
    lambda m: model.status_delete(m, 99),
])
def test_impossible_edits(edit):
    with pytest.raises(model.ModelError):
        edit(good())


def test_backup_round_trip_and_uuid_check():
    m = good()
    doc = model.backup_doc({"uuid": fx.K_OWN, "group_id": fx.G_OWN}, m, "2026-10-28T00:00:00Z")
    text = json.dumps(doc)
    assert model.canonical(model.read_config_file(text, fx.K_OWN)) == model.canonical(m)
    with pytest.raises(model.ModelError, match="is for kiosk"):
        model.read_config_file(text, fx.K_MEM)
    assert model.canonical(model.read_config_file(json.dumps(fx.base_config()), fx.K_OWN)) == model.canonical(m)
    with pytest.raises(model.ModelError):
        model.read_config_file("{not json", fx.K_OWN)
    with pytest.raises(model.ModelError):
        model.read_config_file(json.dumps({"format": "other/1"}), fx.K_OWN)


def test_from_wire_rejects_bad_shapes():
    for bad in ([], {"frontendConfigName": "x"}, {"frontendConfigName": "x", "frontendConfigLanes": [1],
                                                    "frontendConfigStatusMap": []}):
        with pytest.raises(model.ModelError):
            model.from_wire(bad)


def test_uuid_shape():
    assert model.valid_uuid(fx.K_OWN)
    assert not model.valid_uuid("not-a-uuid") and not model.valid_uuid("")
