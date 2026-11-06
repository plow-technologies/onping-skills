"""Offline tests for onping-create-singlewell-manual (no network).

    uv run --with pytest --with requests pytest onping/skills/onping-create-singlewell-manual/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(SKILLS / "_singlewell_manual_routes" / "tests"))
import swm_fakes as F  # noqa: E402
from _driver_add_schemas.schemas import SCHEMAS  # noqa: E402
from _singlewell_manual_routes import routes as R  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "create_location", SKILLS / "onping-create-singlewell-manual" / "scripts" / "create_location.py"
)
create = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create)

NAME = "zz-skill-test-unit"


def args(*extra: str, name: str = NAME, lj: int = F.LJ, group: str = F.G_OWNED, site: int = F.SITE) -> list[str]:
    return ["--lj", str(lj), "--company", str(F.COMPANY), "--site", str(site),
            "--group", group, "--name", name, *extra]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("ONPING_ACCESS_TOKEN", "tok")
    return F.FakeOnPing().install(monkeypatch)


def adds(fake) -> list[dict]:
    return [c for c in fake.calls if c["path"] == "/singlewellmanual/location/add"]


# ─────────────────────────────── preview ───────────────────────────────


def test_preview_sends_nothing(fake, capsys):
    assert create.main(args()) == 0
    assert fake.writes() == []
    out = capsys.readouterr().out
    assert "Preview only" in out and NAME in out and F.LJ_URL in out
    assert "onping-delete-singlewell-manual" in out


def test_dry_run_wins_over_yes(fake):
    assert create.main(args("--yes", "--dry-run")) == 0
    assert fake.writes() == []


def test_preview_json_report(fake, capsys):
    assert create.main(args("--json")) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["mode"] == "preview" and rep["exit"] == 0
    assert rep["checks"]["group_owned"] and rep["checks"]["name_free_at_site"]
    assert "lumberjackPassword" not in json.dumps(rep)


# ─────────────────────────────── refusals ───────────────────────────────


@pytest.mark.parametrize(
    "kw,needle",
    [
        ({"lj": 123}, "no LAS profile"),
        ({"lj": 900002}, "no LAS profile"),
        ({"group": F.G_OTHER}, "not one of your"),
        ({"site": 89999}, "not a live site"),
        ({"name": F.EXISTING_NAME}, "already exists"),
    ],
)
def test_refusals_exit_3_and_send_nothing(fake, capsys, kw, needle):
    assert create.main(args("--yes", **kw)) == 3
    assert fake.writes() == []
    assert needle in capsys.readouterr().out


def test_empty_name_is_usage_error(fake):
    with pytest.raises(SystemExit) as exc:
        create.main(args(name="   "))
    assert exc.value.code == 2


@pytest.mark.parametrize("port", ["0", "65536"])
def test_port_out_of_range_is_usage_error(fake, port):
    with pytest.raises(SystemExit) as exc:
        create.main(args("--yes", "--port", port))
    assert exc.value.code == 2
    assert fake.calls == []


def test_preflight_read_failure_exits_1(fake):
    fake.fail_reads.add("/permissions/groups/ownership")
    assert create.main(args("--yes")) == 1
    assert fake.writes() == []


def test_expired_token_exits_1(fake):
    fake.expired = True
    assert create.main(args("--yes")) == 1
    assert fake.writes() == []


# ─────────────────────────────── writes ───────────────────────────────


def test_verified_create(fake, capsys):
    assert create.main(args("--yes", "--notes", "made by a test")) == 0
    sent = adds(fake)
    assert len(sent) == 1
    body = sent[0]["body"]
    assert body["manualLocationUrl"] == F.LJ_URL
    assert body["manualLocationPort"] == 13001
    assert body["locationData"] == [] and body["manualLocationId"] is None
    ref = 40001
    assert ref in fake.manual and fake.group_join[ref] == F.G_OWNED
    out = capsys.readouterr().out
    assert "created location 40001" in out and "Verified" in out
    assert "delete_location.py" in out and "40001 --yes" in out


def test_body_keys_match_the_corrected_schema(fake):
    assert create.main(args("--yes")) == 0
    body = adds(fake)[0]["body"]
    schema = SCHEMAS["singlewell-manual"]
    assert set(body) == set(schema["request_schema"]) == set(R.CREATE_KEYS)
    assert set(schema["response_schema"]) == {"int"}
    assert set(R.CREATE_KEYS) == {
        "manualLocationName", "manualLocationId", "manualLocationUrl", "manualLocationPort",
        "manualLocationGroupId", "manualLocationRefId", "locationCompanyId", "locationSiteId",
        "locationNotes", "locationData", "coordinates",
    }
    assert "onping-create-singlewell-manual" in schema["notes"]


def test_400_means_nothing_written(fake, capsys):
    fake.add_status_override = (400, {"error": "postAddSingleWellManualLocationR: Failed to parse JSON request body. x"})
    assert create.main(args("--yes")) == 1
    assert "nothing was written" in capsys.readouterr().out


@pytest.mark.parametrize(
    "step,exist",
    [
        ("switcher", 1),
        ("1", 2),
        ("2", 3),
        ("3", 4),
        ("4", 5),
    ],
)
def test_partial_create_reports_its_residue(fake, capsys, step, exist):
    fake.add_fail = step
    assert create.main(args("--yes", "--json")) == 4
    rep = json.loads(capsys.readouterr().out)
    assert rep["location_id"] == 40001
    assert rep["residue"] == list(R.ADD_ORDER[:exist])
    # the fake's real leftovers agree with the report
    held = {
        R.ADD_ORDER[0]: 40001 in fake.mysql,
        R.ADD_ORDER[1]: 40001 in fake.switcher,
        R.ADD_ORDER[2]: 40001 in fake.manual,
        R.ADD_ORDER[3]: 40001 in fake.mongo,
        R.ADD_ORDER[4]: 40001 in fake.extras,
        R.ADD_ORDER[5]: 40001 in fake.group_join,
    }
    assert [k for k, v in held.items() if v] == rep["residue"]
    assert len(adds(fake)) == 1


def test_lost_response_is_unknown_and_looks_by_name(fake, capsys):
    fake.add_lose_response = True
    assert create.main(args("--yes", "--json")) == 4
    rep = json.loads(capsys.readouterr().out)
    assert rep["found_by_name"] == [40001]
    assert len(adds(fake)) == 1  # never retried


def test_unrecognised_500_is_unknown(fake):
    fake.add_status_override = (500, "Internal Server Error")
    assert create.main(args("--yes")) == 4


def test_read_back_mismatch_exits_4(fake, capsys, monkeypatch):
    original = fake._add

    def tampered(body, url):
        resp = original(body, url)
        fake.manual[40001]["notes"] = "changed by someone else"
        return resp

    monkeypatch.setattr(fake, "_add", tampered)
    assert create.main(args("--yes")) == 4
    out = capsys.readouterr().out
    assert "mismatch locationNotes" in out


def test_read_back_not_listed_exits_4(fake, capsys, monkeypatch):
    monkeypatch.setattr(fake, "listing", lambda sites: [])
    assert create.main(args("--yes")) == 4
    assert "not in the manual listing" in capsys.readouterr().out
