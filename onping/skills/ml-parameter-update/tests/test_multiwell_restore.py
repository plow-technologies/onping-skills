"""Contract tests for SingleOrMany source reads and full-envelope restore PUTs."""

from __future__ import annotations

import copy

import pytest

from _inferno_ml_routes import inferno_ml_models as ml

PARAM_ID = "00000000-0000-4000-8000-00000000c005"
OLD_HASH = "old-hash="
NEW_HASH = "new-hash="


def bare(width: int = 3, script: str = NEW_HASH) -> dict:
    return {
        "id": PARAM_ID, "name": "multiwell", "description": "unchanged",
        "company": 100, "active": True,
        "schedule": {"enabled": True, "stype": {"tag": "OnCron", "contents": "0,30 * * * *"}},
        "param": {
            "id": PARAM_ID, "gid": "ogroup", "script": script,
            "inputs": {"sensor": list(range(101, 101 + width))},
            "outputs": {"setpoint": list(range(201, 201 + width))},
            "resolution": 60, "terminated": None,
        },
    }


def export(width: int = 2) -> dict:
    current = bare(width, OLD_HASH)
    p = current["param"]
    return {
        "id": PARAM_ID, "name": current["name"],
        "description": current["description"], "company": current["company"],
        "schedule": current["schedule"], "itype": {"device": "gpu", "cap": "medium"},
        "gid": p["gid"], "script": p["script"], "inputs": p["inputs"],
        "outputs": p["outputs"], "resolution": p["resolution"],
    }


def with_sources(width: int = 3) -> dict:
    current = bare(width)
    for section, stype in (("inputs", "InputSource"), ("outputs", "OutputSource")):
        current["param"][section] = {
            name: [
                {"id": f"{section}-{pid}", "pid": pid, "param": PARAM_ID,
                 "itype": {"tag": "TDouble"}, "company": 100, "site": 2,
                 "location": 3, "stype": stype}
                for pid in pids
            ] for name, pids in current["param"][section].items()
        }
    return current


def test_with_sources_accepts_arrays_and_preserves_order():
    ws = with_sources()
    assert ml._validate_param_envelope(ws, with_sources=True) == []
    assert ml._param_body_from_with_sources(ws)["inputs"] == {"sensor": [101, 102, 103]}
    assert [(s["pid"], s["stype"]) for s in ml.build_sources_vector(ws)] == [
        (101, "InputSource"), (102, "InputSource"), (103, "InputSource"),
        (201, "OutputSource"), (202, "OutputSource"), (203, "OutputSource"),
    ]
    ws["param"]["inputs"]["sensor"] = []
    with pytest.raises(ml.OnPingRequestError, match="nonempty array"):
        ml._validate_param_envelope(ws, with_sources=True)


def test_restore_dry_run_preserves_envelope_and_restores_whole_arrays(monkeypatch):
    current = bare()
    monkeypatch.setattr(ml, "get_inference_param", lambda *_: copy.deepcopy(current))
    calls = []
    monkeypatch.setattr(ml, "_request", lambda *a, **kw: calls.append((a, kw)))
    target = export()
    target["inputs"]["new_channel"] = [301, 302]
    result = ml.restore_inference_param_from_export(
        "token", param_id=PARAM_ID, exported=target,
        expected_script_hash=NEW_HASH, expected_current_width=3,
    )
    assert result["result"] == "dry-run" and not calls
    assert result["current_width"] == 3 and result["desired_width"] == 2
    body = result["put_body"]
    assert set(body) == set(current) and "sources" not in body
    assert body["active"] is True and body["schedule"] == current["schedule"]
    assert body["param"]["inputs"] == target["inputs"]
    assert body["param"]["outputs"] == target["outputs"]
    assert body["param"]["script"] == OLD_HASH
    assert current["param"]["inputs"]["sensor"] == [101, 102, 103]
    assert result["changes"]["inputs"]["changed"]["sensor"]["after"] == [101, 102]


def test_restore_apply_only_sends_full_envelope(monkeypatch):
    current = bare()
    monkeypatch.setattr(ml, "get_inference_param", lambda *_: copy.deepcopy(current))
    requests = []
    monkeypatch.setattr(ml, "_request", lambda *a, **kw: requests.append((a, kw)))
    result = ml.restore_inference_param_from_export(
        "token", param_id=PARAM_ID, exported=export(),
        expected_script_hash=NEW_HASH, expected_current_width=3, dry_run=False,
    )
    assert result["result"] == "applied"
    assert len(requests) == 1
    (method, route, token), kw = requests[0]
    assert (method, route, token) == ("PUT", "/inferno/ml/inference/update", "token")
    assert kw["json_body"]["id"] == PARAM_ID
    assert kw["json_body"]["param"]["inputs"]["sensor"] == [101, 102]
    assert "sources" not in kw["json_body"]


@pytest.mark.parametrize("change", [
    lambda t: t.update(id="other"),
    lambda t: t.update(company=43),
    lambda t: t["inputs"].update(sensor=[101, 0]),
    lambda t: t["outputs"].update(setpoint=[201, 202, 203]),
])
def test_restore_fails_closed_on_bad_export(monkeypatch, change):
    monkeypatch.setattr(ml, "get_inference_param", lambda *_: bare())
    calls = []
    monkeypatch.setattr(ml, "_request", lambda *a, **kw: calls.append((a, kw)))
    target = export()
    change(target)
    with pytest.raises(ml.OnPingRequestError):
        ml.restore_inference_param_from_export(
            "token", param_id=PARAM_ID, exported=target,
            expected_script_hash=NEW_HASH, expected_current_width=3, dry_run=False,
        )
    assert not calls


def test_restore_rejects_stale_pin_or_width(monkeypatch):
    monkeypatch.setattr(ml, "get_inference_param", lambda *_: bare())
    for script, width in ((OLD_HASH, 3), (NEW_HASH, 4)):
        with pytest.raises(ml.OnPingRequestError):
            ml.restore_inference_param_from_export(
                "token", param_id=PARAM_ID, exported=export(),
                expected_script_hash=script, expected_current_width=width,
            )


def test_legacy_scalar_update_is_full_envelope_but_array_update_refuses(monkeypatch):
    monkeypatch.setattr(ml, "get_inference_param_with_sources", lambda *_: with_sources())
    with pytest.raises(ml.OnPingRequestError, match="multi-well"):
        ml.update_inference_param("token", param_id=PARAM_ID, script_hash=OLD_HASH)
    single = with_sources(1)
    single["param"]["inputs"]["sensor"] = single["param"]["inputs"]["sensor"][0]
    single["param"]["outputs"]["setpoint"] = single["param"]["outputs"]["setpoint"][0]
    monkeypatch.setattr(ml, "get_inference_param_with_sources", lambda *_: single)
    result = ml.update_inference_param("token", param_id=PARAM_ID, script_hash=OLD_HASH, dry_run=True)
    assert result["put_body"]["id"] == PARAM_ID
    assert result["put_body"]["param"]["inputs"]["sensor"] == 101
    assert "sources" not in result["put_body"]
