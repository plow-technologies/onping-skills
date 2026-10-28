"""cp-list against the /cpInferno/list tagged union (onping #16220).

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
SCRIPT = HERE.parent / "scripts" / "list_control_parameters.py"
spec = importlib.util.spec_from_file_location("list_control_parameters", SCRIPT)
cpl = importlib.util.module_from_spec(spec)
sys.modules["list_control_parameters"] = cpl
spec.loader.exec_module(cpl)

FIXTURE = json.loads((HERE / "fixtures" / "cpinferno-list-all-tags.json").read_text())
READABLE = FIXTURE[0]
ORPHAN = FIXTURE[1]
ORPHAN_CPID = "1001-00000000-0000-4000-8000-00000000c002"


class FakeResponse:
    def __init__(self, body):
        self.status_code = 200
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


def run(monkeypatch, capsys, bodies: dict[int, list], argv_ids: list[int]):
    def fake_post(url, data, **_kwargs):
        assert url.endswith("/cpInferno/list")
        return FakeResponse(bodies[int(data)])

    monkeypatch.setattr(cpl.requests, "post", fake_post)
    monkeypatch.setattr(sys, "argv", ["cp-list", "TOKEN", *map(str, argv_ids)])
    code = 0
    try:
        cpl.main()
    except SystemExit as exc:  # pragma: no cover - main returns normally on success
        code = exc.code
    out, err = capsys.readouterr()
    return code, out, err


def test_readable_only_prints_no_notice(monkeypatch, capsys):
    code, out, err = run(monkeypatch, capsys, {1001: [READABLE]}, [1001])
    assert code == 0
    assert json.loads(out) == [READABLE]
    assert err == ""


def test_one_readable_and_one_orphan(monkeypatch, capsys):
    body = [READABLE, ORPHAN]
    code, out, err = run(monkeypatch, capsys, {1001: copy.deepcopy(body)}, [1001])
    assert code == 0
    assert json.loads(out) == body  # stdout unchanged
    assert ORPHAN_CPID in err
    assert "500015" in err
    assert "OrphanedControlParameterInferno=1" in err
    assert "ReadableControlParameterInferno=1" in err


def test_every_tag_is_counted_and_named(monkeypatch, capsys):
    code, out, err = run(monkeypatch, capsys, {1001: copy.deepcopy(FIXTURE)}, [1001])
    assert code == 0
    assert json.loads(out) == FIXTURE
    for tag in cpl.KNOWN_TAGS:
        assert f"{tag}=1" in err
    assert "prohibited (no read permission): 1001-00000000-0000-4000-8000-00000000c003" in err
    assert "failed permission lookup: 1001-00000000-0000-4000-8000-00000000c004" in err
    assert '"Example Orphaned Passthrough"' in err


def test_unknown_tag_is_named(monkeypatch, capsys):
    body = [READABLE, {"tag": "SomeFutureControlParameterInferno", "contents": {}}]
    code, out, err = run(monkeypatch, capsys, {1001: copy.deepcopy(body)}, [1001])
    assert code == 0
    assert json.loads(out) == body
    assert "unknown tag: SomeFutureControlParameterInferno" in err


def test_multiple_lumberjacks_report_per_serial(monkeypatch, capsys):
    bodies = {1001: [READABLE], 1002: [ORPHAN]}
    code, out, err = run(monkeypatch, capsys, copy.deepcopy(bodies), [1001, 1002])
    assert code == 0
    assert json.loads(out) == {"1001": [READABLE], "1002": [ORPHAN]}
    assert "Lumberjack 1001" not in err
    assert "Lumberjack 1002" in err
    assert ORPHAN_CPID in err


def test_orphan_without_cpid_prints_unparsed():
    orphan = copy.deepcopy(ORPHAN)
    del orphan["contents"][0]["cpId"]
    lines = cpl.non_readable_notice([orphan], 1001)
    assert lines[1].startswith('  [0] orphaned: <unparsed> "Example Orphaned Passthrough"')
    assert "null" not in lines[1]


@pytest.mark.parametrize(
    "value",
    [
        {"engineHost": 1001, "perEngineId": "u"},
        {"CPID": {"engineHost": 1001, "perEngineId": "u"}},
        {"ACPID": {"engineHost": 1001, "perEngineId": "u"}},
        {"tag": "CPID", "contents": {"engineHost": 1001, "perEngineId": "u"}},
        {"tag": "ACPID", "contents": {"engineHost": 1001, "perEngineId": "u"}},
        "1001-u",
    ],
)
def test_friendly_cpid_accepts_every_cpid_form(value):
    assert cpl.friendly_cpid(value) == "1001-u"


def test_friendly_cpid_absent_and_unrecognised():
    assert cpl.friendly_cpid(None) == "<unparsed>"
    assert cpl.friendly_cpid({"x": 1}) == '{"x": 1}'


GOLDEN_DIR = os.environ.get("ONPING_FRONTEND_TYPES_GOLDEN")


@pytest.mark.skipif(not GOLDEN_DIR, reason="set ONPING_FRONTEND_TYPES_GOLDEN to the upstream golden dir")
def test_upstream_golden_orphans(monkeypatch, capsys):
    golden = json.loads(
        (Path(GOLDEN_DIR) / "ReadableControlParameterInferno" / "OrphanedControlParameterInferno.json").read_text()
    )["samples"]
    code, out, err = run(monkeypatch, capsys, {1001: copy.deepcopy(golden)}, [1001])
    assert code == 0
    assert json.loads(out) == golden
    assert f"OrphanedControlParameterInferno={len(golden)}" in err
    for sample in golden:
        cp_id = sample["contents"][0]["cpId"]
        assert f"{cp_id['engineHost']}-{cp_id['perEngineId']}" in err
