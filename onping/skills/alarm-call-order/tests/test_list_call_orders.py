"""Contract tests for alarm-call-order against the /alarmmix/lister wire format.

Shapes follow onping-frontend-types AlarmConfigMix / AlarmMixError and
onping-types CallOrderConfig / CallOrderEntryConfig (onping #16132). The
fixtures under fixtures/ are the upstream goldens with the random unicode
strings replaced by ASCII; lister_legacy.json is the pre-#16132 shape.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "list_call_orders.py"
spec = importlib.util.spec_from_file_location("list_call_orders", SCRIPT)
lco = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lco)

FLAGS = {
    "notificationFlagCall": True,
    "notificationFlagEmail": False,
    "notificationFlagText": True,
    "notificationFlagTextBroadcast": False,
}


def fixture(name: str):
    return json.loads((HERE / "fixtures" / name).read_text())


def alarm(entries, co_id="o00000000000000000000c001", mix_id="o00000000000000000000a001", **cfg_overrides) -> dict:
    cfg = {
        "orderId": co_id,
        "orderName": "Night",
        "orderEntries": entries,
        "orderOID": None,
        "orderGID": "o00000000000000000000g001",
        "orderPerm": [],
    }
    cfg.update(cfg_overrides)
    return {
        "alarmMixId": {"tag": "AlarmMixIdRegular", "contents": mix_id},
        "alarmName": "High pressure",
        "alarmActive": True,
        "callOrderId": co_id,
        "callOrderConfig": cfg,
    }


def entry(name, repeat, user_id="o00000000000000000000u001", flags=None) -> dict:
    return {
        "entryConfigUserId": user_id,
        "entryConfigUserName": name,
        "entryConfigRepeatCount": repeat,
        "entryConfigNotificationFlags": flags,
    }


ANN_BO = [entry("Ann", 2), entry("Bo", 1, user_id="o00000000000000000000u002", flags=FLAGS)]


class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text)


class FakePost:
    def __init__(self, status: int, body):
        self.response = FakeResponse(status, body)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


SITE = "o00000000000000000000000c"


def run(capsys, status, body):
    post = FakePost(status, body)
    code = lco.main(["TOKEN", "--site", SITE], post=post)
    out, err = capsys.readouterr()
    return code, out, err, post


# --- summarize: orderEntries ---------------------------------------------------


def test_two_entries_in_order_with_derived_keys():
    result = lco.summarize([{"Right": alarm(ANN_BO)}])
    co = result["callOrders"]["o00000000000000000000c001"]
    assert co["orderName"] == "Night"
    assert co["entries"] == [
        {"userId": "o00000000000000000000u001", "userName": "Ann", "repeatCount": 2, "notificationFlags": None},
        {"userId": "o00000000000000000000u002", "userName": "Bo", "repeatCount": 1, "notificationFlags": FLAGS},
    ]
    assert co["userNames"] == ["Ann", "Bo"]
    assert co["repeatCounts"] == [2, 1]
    assert result["totalAlarms"] == 1
    assert result["errors"] == []


def test_two_entries_end_to_end_exit_0(capsys):
    code, out, err, post = run(capsys, 200, [{"Right": alarm(ANN_BO)}])
    assert code == 0
    co = json.loads(out)["callOrders"]["o00000000000000000000c001"]
    assert co["userNames"] == ["Ann", "Bo"]
    assert co["repeatCounts"] == [2, 1]
    assert len(post.calls) == 1
    assert post.calls[0][1]["json"]["getSiteLookups"] == [SITE]


def test_empty_call_order_is_not_an_error(capsys):
    code, out, err, _ = run(capsys, 200, [{"Right": alarm([])}])
    assert code == 0
    co = json.loads(out)["callOrders"]["o00000000000000000000c001"]
    assert co["entries"] == []
    assert co["userNames"] == []
    assert co["repeatCounts"] == []
    assert "has no entries" in err


def test_alarms_grouped_by_call_order():
    a1 = alarm(ANN_BO, mix_id="o00000000000000000000a001")
    a2 = alarm(ANN_BO, mix_id="o00000000000000000000a002")
    a3 = alarm([entry("Cy", 3)], co_id="o00000000000000000000c002", mix_id="o00000000000000000000a003")
    result = lco.summarize([{"Right": a1}, {"Right": a2}, {"Right": a3}])
    assert result["totalAlarms"] == 3
    assert len(result["callOrders"]["o00000000000000000000c001"]["alarms"]) == 2
    assert result["callOrders"]["o00000000000000000000c002"]["userNames"] == ["Cy"]


def test_golden_fixture_entries_match_upstream_order():
    data = fixture("lister_golden.json")
    result = lco.summarize(data)
    assert result["totalAlarms"] == len(data)
    for item in data:
        a = item["Right"]
        co = result["callOrders"][a["callOrderId"]]
        raw = a["callOrderConfig"]["orderEntries"]
        assert co["userNames"] == [e["entryConfigUserName"] for e in raw]
        assert co["repeatCounts"] == [e["entryConfigRepeatCount"] for e in raw]
        assert [e["notificationFlags"] for e in co["entries"]] == [e["entryConfigNotificationFlags"] for e in raw]
        assert co["userNames"], "golden call orders are non-empty"


# --- refuse unknown shapes (exit 3, nothing on stdout) -------------------------


def test_legacy_fixture_exits_3_and_names_16132(capsys):
    data = fixture("lister_legacy.json")
    code, out, err, _ = run(capsys, 200, data)
    assert code == 3
    assert out == ""
    a = data[0]["Right"]
    assert a["alarmMixId"]["contents"] in err
    assert a["callOrderId"] in err
    assert "#16132" in err
    assert '"userNames"' in err and '"repeatCounts"' in err


def test_missing_call_order_config_exits_3(capsys):
    a = alarm(ANN_BO)
    del a["callOrderConfig"]
    code, out, err, _ = run(capsys, 200, [{"Right": a}])
    assert code == 3
    assert out == ""
    assert "o00000000000000000000a001" in err
    assert "callOrderConfig is missing" in err


@pytest.mark.parametrize(
    "body, needle",
    [
        ({"alarms": []}, "not a list"),
        ([{"Middle": {}}], "neither"),
        ([["Right", {}]], "neither"),
        ([{"Right": {**alarm(ANN_BO), "callOrderConfig": []}}], "not an object"),
        ([{"Right": alarm(ANN_BO, orderEntries=None)}], "not a list"),
        ([{"Right": alarm(ANN_BO, orderEntries={})}], "not a list"),
        ([{"Right": alarm([{"entryConfigUserName": "Ann"}])}], "entryConfigRepeatCount"),
        ([{"Right": alarm([entry("Ann", "2")])}], "entryConfigRepeatCount"),
        ([{"Right": alarm([entry("Ann", True)])}], "entryConfigRepeatCount"),
        ([{"Right": alarm([{"entryConfigRepeatCount": 1}])}], "entryConfigUserName"),
        ([{"Right": alarm(["Ann"])}], "not an object"),
        ([{"Right": alarm([{k: v for k, v in entry("Ann", 2).items() if k != "entryConfigUserId"}])}], "entryConfigUserId"),
        ([{"Right": alarm([entry("Ann", 2, user_id=42)])}], "entryConfigUserId"),
        ([{"Right": alarm([entry("Ann", 2, flags={**FLAGS, "notificationFlagCall": "yes"})])}], "entryConfigNotificationFlags"),
        ([{"Right": alarm([entry("Ann", 2, flags={"notificationFlagCall": True})])}], "entryConfigNotificationFlags"),
        ([{"Right": alarm([entry("Ann", 2, flags=[True, False, True, False])])}], "entryConfigNotificationFlags"),
        ([{"Right": alarm(ANN_BO, orderName=None)}], "orderName is missing or not a string"),
        ([{"Right": alarm(ANN_BO, orderName=7)}], "orderName is missing or not a string"),
    ],
)
def test_unknown_shapes_exit_3(capsys, body, needle):
    code, out, err, _ = run(capsys, 200, body)
    assert code == 3
    assert out == ""
    assert needle in err


def test_missing_order_entries_without_user_names_does_not_blame_16132():
    a = alarm(ANN_BO)
    del a["callOrderConfig"]["orderEntries"]
    with pytest.raises(lco.ShapeError) as exc:
        lco.summarize([{"Right": a}])
    assert "#16132" not in str(exc.value)
    assert "orderEntries is missing" in str(exc.value)


def test_missing_order_name_exits_3():
    a = alarm(ANN_BO)
    del a["callOrderConfig"]["orderName"]
    with pytest.raises(lco.ShapeError, match="orderName is missing"):
        lco.summarize([{"Right": a}])


def test_error_names_tagged_alarm_mix_id_not_the_whole_object():
    a = alarm(ANN_BO, mix_id="o00000000000000000000a009")
    del a["callOrderConfig"]
    with pytest.raises(lco.ShapeError) as exc:
        lco.summarize([{"Right": a}])
    assert "alarm AlarmMixIdRegular:o00000000000000000000a009," in str(exc.value)
    assert '"contents"' not in str(exc.value)


def test_alarm_id_keeps_the_tag():
    assert lco._alarm_id({"tag": "AlarmMixIdRegular", "contents": "o1"}) == "AlarmMixIdRegular:o1"
    assert lco._alarm_id({"tag": "AlarmMixIdVP", "contents": "o1"}) == "AlarmMixIdVP:o1"
    assert lco._alarm_id({"contents": "o1"}) == "o1"


def test_alarm_id_falls_back_when_contents_missing():
    assert lco._alarm_id({"tag": "Odd"}) == '{"tag": "Odd"}'
    assert lco._alarm_id("o1") == "o1"
    assert lco._alarm_id(None) == "null"


def test_regular_and_vp_alarms_with_the_same_oid_are_told_apart(capsys):
    regular = alarm(ANN_BO, mix_id="o00000000000000000000a001")
    vp = alarm([entry("Cy", 3)], mix_id="o00000000000000000000a001")
    vp["alarmMixId"]["tag"] = "AlarmMixIdVP"
    code, out, err, _ = run(capsys, 200, [{"Right": regular}, {"Right": vp}])
    assert code == 4
    (conflict,) = json.loads(out)["errors"]
    assert conflict["contents"]["keptAlarmMixId"] == "AlarmMixIdRegular:o00000000000000000000a001"
    assert conflict["contents"]["alarmMixId"] == "AlarmMixIdVP:o00000000000000000000a001"
    assert "alarm AlarmMixIdVP:o00000000000000000000a001" in err


def _alarm_level_failures():
    no_cfg = alarm(ANN_BO, mix_id="o00000000000000000000a007")
    del no_cfg["callOrderConfig"]
    return [
        no_cfg,
        alarm(ANN_BO, mix_id="o00000000000000000000a007", orderEntries=None),
        alarm(ANN_BO, mix_id="o00000000000000000000a007", orderName=None),
        alarm([entry("Ann", "2")], mix_id="o00000000000000000000a007"),
        alarm([entry("Ann", 2, flags={"notificationFlagCall": True})], mix_id="o00000000000000000000a007"),
        alarm(["Ann"], mix_id="o00000000000000000000a007"),
    ]


@pytest.mark.parametrize("bad", _alarm_level_failures())
def test_exit_3_messages_name_alarm_call_order_and_keys(capsys, bad):
    code, out, err, _ = run(capsys, 200, [{"Right": alarm(ANN_BO)}, {"Right": bad}])
    assert code == 3
    assert out == ""
    assert "element 1 (alarm AlarmMixIdRegular:o00000000000000000000a007, call order o00000000000000000000c001)" in err
    assert "keys found: " in err


def test_missing_call_order_id_names_alarm_and_keys(capsys):
    a = alarm(ANN_BO, mix_id="o00000000000000000000a007")
    del a["callOrderId"]
    code, out, err, _ = run(capsys, 200, [{"Right": a}])
    assert code == 3
    assert "alarm AlarmMixIdRegular:o00000000000000000000a007" in err
    assert "callOrderId is null" in err
    assert 'keys found: ["alarmActive"' in err


@pytest.mark.parametrize(
    "entries, index, needle",
    [
        ([entry("Ann", 2), entry("Bo", "1")], 1, "entryConfigRepeatCount"),
        ([entry("Ann", 2), entry("Bo", 1), {"entryConfigUserName": "Cy"}], 2, "entryConfigUserId"),
        ([entry("Ann", 2), "Bo"], 1, "not an object"),
        ([entry("Ann", 2), entry("Bo", 1, flags={"notificationFlagCall": True})], 1, "entryConfigNotificationFlags"),
        ([entry("Ann", 2, flags=[True])], 0, "entryConfigNotificationFlags"),
    ],
)
def test_entry_errors_name_the_entry_index(entries, index, needle):
    with pytest.raises(lco.ShapeError) as exc:
        lco.summarize([{"Right": alarm(entries)}])
    msg = str(exc.value)
    assert f"orderEntries[{index}]:" in msg
    assert needle in msg


# --- conflicting copies of one call order (exit 4, listing still printed) -------


def test_conflicting_copies_of_one_call_order_exit_4_with_full_listing(capsys):
    data = fixture("lister_conflict.json")
    a, b = data[0]["Right"], data[1]["Right"]
    assert a["callOrderId"] == b["callOrderId"]
    other = alarm([entry("Cy", 3)], co_id="o00000000000000000000c002", mix_id="o00000000000000000000a003")
    code, out, err, _ = run(capsys, 200, data + [{"Right": other}])
    assert code == 4
    result = json.loads(out)
    assert set(result["callOrders"]) == {a["callOrderId"], "o00000000000000000000c002"}
    assert result["totalAlarms"] == 3
    co = result["callOrders"][a["callOrderId"]]
    assert len(co["entries"]) == 6, "the first alarm's copy is kept"
    assert [x.get("configConflict", False) for x in co["alarms"]] == [False, True]
    (conflict,) = result["errors"]
    assert conflict == {
        "tag": "CallOrderConflict",
        "contents": {
            "callOrderId": a["callOrderId"],
            "keptAlarmMixId": f"{a['alarmMixId']['tag']}:{a['alarmMixId']['contents']}",
            "alarmMixId": f"{b['alarmMixId']['tag']}:{b['alarmMixId']['contents']}",
            "differences": [{"field": "entries.length", "kept": 6, "other": 5}],
        },
    }
    assert a["callOrderId"] in err
    assert a["alarmMixId"]["contents"] in err and b["alarmMixId"]["contents"] in err
    assert "entries.length 6 vs 5" in err
    assert "1 call order conflict(s)" in err


def test_conflict_names_the_entry_field_and_order_name_that_differ(capsys):
    kept = alarm(ANN_BO, mix_id="o00000000000000000000a001")
    changed = [entry("Ann", 2), entry("Bo", 3, user_id="o00000000000000000000u002", flags=FLAGS)]
    other = alarm(changed, mix_id="o00000000000000000000a002", orderName="Day")
    code, out, err, _ = run(capsys, 200, [{"Right": kept}, {"Right": other}])
    assert code == 4
    (conflict,) = json.loads(out)["errors"]
    assert conflict["contents"]["differences"] == [
        {"field": "orderName", "kept": "Night", "other": "Day"},
        {"field": "entries[1].repeatCount", "kept": 1, "other": 3},
    ]
    assert 'orderName "Night" vs "Day"' in err
    assert "entries[1].repeatCount 1 vs 3" in err
    assert "entries.length" not in err


def test_conflict_names_differing_flags_and_user():
    kept = alarm(ANN_BO, mix_id="o00000000000000000000a001")
    other = alarm(
        [entry("Ann", 2, flags=FLAGS), entry("Cy", 1, user_id="o00000000000000000000u003", flags=FLAGS)],
        mix_id="o00000000000000000000a002",
    )
    result = lco.summarize([{"Right": kept}, {"Right": other}])
    fields = [d["field"] for d in result["errors"][0]["contents"]["differences"]]
    assert fields == ["entries[0].notificationFlags", "entries[1].userId", "entries[1].userName"]


def test_identical_copies_of_one_call_order_are_merged(capsys):
    data = fixture("lister_conflict.json")
    data[1]["Right"]["callOrderConfig"] = copy.deepcopy(data[0]["Right"]["callOrderConfig"])
    code, out, err, _ = run(capsys, 200, data)
    assert code == 0
    result = json.loads(out)
    (co,) = result["callOrders"].values()
    assert len(co["alarms"]) == 2
    assert not any("configConflict" in x for x in co["alarms"])
    assert len(co["entries"]) == 6
    assert result["errors"] == []


def test_later_alarm_with_bad_shape_is_still_refused():
    good = alarm(ANN_BO, mix_id="o00000000000000000000a001")
    bad = copy.deepcopy(good)
    bad["alarmMixId"]["contents"] = "o00000000000000000000a002"
    bad["callOrderConfig"]["orderEntries"] = [{"entryConfigUserName": "Ann"}]
    with pytest.raises(lco.ShapeError) as exc:
        lco.summarize([{"Right": good}, {"Right": bad}])
    assert "o00000000000000000000a002" in str(exc.value)


# --- Left elements --------------------------------------------------------------


def test_left_element_goes_to_errors(capsys):
    data = fixture("lister_with_left.json")
    code, out, err, _ = run(capsys, 200, data)
    assert code == 0
    result = json.loads(out)
    assert result["totalAlarms"] == 1
    assert result["errors"] == [data[1]["Left"]]
    assert result["errors"][0]["tag"] == "AlarmCallOrderNotFound"
    assert len(result["callOrders"]) == 1
    assert "1 alarm error(s)" in err


@pytest.mark.parametrize(
    "left",
    [
        "AlarmCallOrderNotFound",
        None,
        ["o1", "o2"],
        {"tag": "AlarmNotFound"},
        {"contents": "o1"},
        {"tag": 7, "contents": "o1"},
        {"tag": "AlarmNotFound", "contents": "o1", "extra": 1},
    ],
)
def test_left_that_is_not_tag_contents_exits_3(capsys, left):
    code, out, err, _ = run(capsys, 200, [{"Right": alarm(ANN_BO)}, {"Left": left}])
    assert code == 3
    assert out == ""
    assert "element 1: the Left value is not an AlarmMixError {tag, contents}" in err
    assert "keys found: " in err


# --- server errors and auth ------------------------------------------------------


def test_error_body_exits_1(capsys):
    code, out, err, post = run(capsys, 200, {"error": "lookup failed"})
    assert code == 1
    assert out == ""
    assert "lookup failed" in err
    assert len(post.calls) == 1


@pytest.mark.parametrize("status", [401, 403, 302, 303])
def test_auth_failure_exits_1_after_one_request(capsys, status):
    code, out, err, post = run(capsys, status, "")
    assert code == 1
    assert out == ""
    assert "token expired or invalid; run onping-login" in err
    assert len(post.calls) == 1


@pytest.mark.parametrize("body", ['"ErrorLogCompleted"', '"ErrorLogFailed"'])
def test_403_permission_body_names_permission_not_login(capsys, body):
    # Live 2026-10-15: a site the account cannot see answers 403 "ErrorLogCompleted"
    # with a valid token (checkAlarmLookupPermission). onping-login would not help.
    code, out, err, post = run(capsys, 403, body)
    assert code == 1
    assert out == ""
    assert err.startswith("HTTP 403: the account lacks permission")
    assert "run onping-login" not in err
    assert len(post.calls) == 1


def test_non_json_200_exits_3_with_login_hint(capsys):
    code, out, err, post = run(capsys, 200, "<!DOCTYPE html><html><body>Login</body></html>")
    assert code == 3
    assert out == ""
    assert "not JSON" in err
    assert "login page" in err and "run onping-login" in err
    assert len(post.calls) == 1


def test_auth_failure_via_monkeypatched_requests_post(monkeypatch, capsys):
    post = FakePost(401, "")
    monkeypatch.setattr(lco.requests, "post", post)
    code = lco.main(["TOKEN"])
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert "run onping-login" in err
    assert len(post.calls) == 1
    assert post.calls[0][1]["allow_redirects"] is False


def test_other_http_error_exits_1(capsys):
    code, out, err, post = run(capsys, 500, {"error": "boom"})
    assert code == 1
    assert "HTTP 500: boom" in err
    assert len(post.calls) == 1


@pytest.mark.parametrize("body", ["x" * 2000, {"error": "y" * 2000}])
def test_long_non_200_body_is_truncated(capsys, body):
    code, out, err, _ = run(capsys, 502, body)
    assert code == 1
    assert out == ""
    assert "[1500 more characters not shown]" in err
    assert len(err) < 700


def test_long_non_json_200_body_is_truncated(capsys):
    code, out, err, _ = run(capsys, 200, "<html>" + "z" * 2000)
    assert code == 3
    assert "Body: <html>" in err
    assert "[1506 more characters not shown]" in err
    assert len(err) < 1000


def test_short_body_is_not_truncated():
    assert lco._truncate("abc") == "abc"
    assert lco._truncate("a" * 500) == "a" * 500


def test_base_url_from_environment(monkeypatch):
    monkeypatch.setenv("ONPING_BASE_URL", "https://staging.example.test/")
    spec2 = importlib.util.spec_from_file_location("list_call_orders_env", SCRIPT)
    mod = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod)
    assert mod.URL == "https://staging.example.test/alarmmix/lister"
    post = FakePost(200, [])
    assert mod.main(["TOKEN"], post=post) == 0
    assert post.calls[0][0] == "https://staging.example.test/alarmmix/lister"


def test_base_url_default(monkeypatch):
    monkeypatch.delenv("ONPING_BASE_URL", raising=False)
    spec2 = importlib.util.spec_from_file_location("list_call_orders_default", SCRIPT)
    mod = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod)
    assert mod.URL == "https://onping.plowtech.net/alarmmix/lister"
