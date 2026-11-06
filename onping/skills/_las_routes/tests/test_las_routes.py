"""Offline tests for the _las_routes helper. Run:
    uv run --with pytest --with requests --with pyyaml pytest onping/skills/_las_routes/tests
"""

from __future__ import annotations

import json
import math
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
sys.path.insert(0, str(Path(__file__).resolve().parent))
import las_fakes as fx  # noqa: E402
from _las_routes import config_types as ct  # noqa: E402
from _las_routes import configs as cf  # noqa: E402
from _las_routes import las_http  # noqa: E402

T = {t: {"tag": t} for t in ct.SCALARS}


def maybe(t):
    return {"tag": "CMaybe", "contents": t}


def lst(t):
    return {"tag": "CList", "contents": t}


# ------------------------------------------------------------------ types
@pytest.mark.parametrize("t,v,ok", [
    (T["CInteger"], 5, True), (T["CInteger"], -5, True), (T["CInteger"], True, False),
    (T["CInteger"], 5.0, False), (T["CInteger"], "5", False),
    (T["CPort"], 0, True), (T["CPort"], 65535, True), (T["CPort"], 65536, False),
    (T["CPort"], -1, False), (T["CPort"], False, False),
    (T["CFloat"], 1, True), (T["CFloat"], 0.25, True), (T["CFloat"], math.nan, False),
    (T["CFloat"], math.inf, False), (T["CFloat"], True, False), (T["CFloat"], "1", False),
    (T["CBool"], True, True), (T["CBool"], 0, False), (T["CBool"], "true", False),
    (T["CText"], "x", True), (T["CText"], "", True), (T["CText"], 1, False),
    (T["CText"], None, False),
    (T["CPassword"], "s", True), (T["CPassword"], 1, False),
    (T["CURL"], "mqtt://h:1883", True), (T["CURL"], "10.0.0.1", True),
    (T["CURL"], "a b", False), (T["CURL"], 5, False),
    (maybe(T["CPort"]), None, True), (maybe(T["CPort"]), 80, True),
    (maybe(T["CPort"]), 70000, False),
    (lst(T["CText"]), [], True), (lst(T["CText"]), ["a", "b"], True),
    (lst(T["CText"]), "a", False),
    (lst(maybe(T["CInteger"])), [1, None], True),
    ({"tag": "CDuration"}, 3, False), ({"tag": "CList", "contents": {"tag": "X"}}, [], False),
    ("CInteger", 3, False),
])
def test_validate(t, v, ok):
    assert (ct.validate(t, v, "k") == []) is ok


def test_validate_names_the_bad_list_element():
    errs = ct.validate(lst(T["CInteger"]), [1, "x"], "k")
    assert len(errs) == 1 and errs[0].startswith("k[1]:")


def test_port_error_names_the_range():
    assert "0-65535" in ct.validate(T["CPort"], 70000, "p")[0]


def test_password_error_never_shows_the_value():
    errs = ct.validate(T["CPassword"], 12345, "pw")
    assert errs and "12345" not in errs[0]


def test_text_error_hints_to_quote():
    assert "quote" in ct.validate(T["CText"], True, "k")[0]


@pytest.mark.parametrize("t,text,want", [
    (T["CInteger"], "30", 30), (T["CInteger"], "-2", -2), (T["CPort"], "1883", 1883),
    (T["CFloat"], "2", 2), (T["CFloat"], "2.5", 2.5), (T["CFloat"], "1e-3", 0.001),
    (T["CBool"], "TRUE", True), (T["CBool"], "false", False),
    (T["CText"], " spaced ", " spaced "), (T["CURL"], "mqtt://x", "mqtt://x"),
    (maybe(T["CText"]), "null", None), (maybe(T["CInteger"]), "7", 7),
    (lst(T["CText"]), '["a"]', ["a"]),
])
def test_from_cli(t, text, want):
    got = ct.from_cli(t, text)
    assert ct.same_value(got, want)


@pytest.mark.parametrize("t,text", [
    (T["CInteger"], "3.5"), (T["CInteger"], "x"), (T["CFloat"], "nan"), (T["CFloat"], "inf"),
    (T["CFloat"], "1e999"), (T["CBool"], "yes"), (lst(T["CText"]), "a,b"),
    (lst(T["CText"]), '{"a":1}'), ({"tag": "CDuration"}, "3"),
])
def test_from_cli_refuses(t, text):
    with pytest.raises(ValueError):
        ct.from_cli(t, text)


def test_type_names():
    assert ct.type_name(T["CInteger"]) == "CInteger"
    assert ct.type_name(maybe(T["CText"])) == "CMaybe CText"
    assert ct.type_name(lst(maybe(T["CPort"]))) == "CList (CMaybe CPort)"
    assert ct.type_name({"tag": "CDuration"}).startswith("unknown")


def test_mask_nested_passwords():
    assert ct.render(lst(T["CPassword"]), ["a", "bb"]) == '["********", "********"]'
    assert ct.render(maybe(T["CPassword"]), None) == "null"
    assert ct.render(maybe(T["CPassword"]), "a") == '"********"'
    assert ct.render(T["CPassword"], "a", show_secrets=True) == '"a"'
    assert ct.render(T["CText"], "a") == '"a"'


def test_same_value_keeps_bools_apart():
    assert ct.same_value(1, 1.0)
    assert not ct.same_value(1, True)
    assert not ct.same_value([0], [False])
    assert ct.same_value({"a": [1]}, {"a": [1.0]})
    assert not ct.same_value(None, 0)


# ------------------------------------------------------------------ patch
def test_patch_keeps_order_types_and_other_keys():
    pkg = fx.kitchen_sink()
    new, changes, errs = cf.build_patch(pkg, {"label": "b", "ratio": 2})
    assert errs == []
    assert [c.key for c in changes] == ["ratio", "label"]  # schema order
    assert [e["configKey"] for e in new["pkgConfSchema"]] == \
        [e["configKey"] for e in pkg["pkgConfSchema"]]
    assert [e["configType"] for e in new["pkgConfSchema"]] == \
        [e["configType"] for e in pkg["pkgConfSchema"]]
    assert cf.entry(new, "label")["configValue"] == "b"
    assert cf.entry(pkg, "label")["configValue"] == "a"  # the input is not mutated
    assert cf.entry(new, "future")["configValue"] == 3


def test_patch_reports_every_error():
    _, _, errs = cf.build_patch(fx.kitchen_sink(),
                                {"nope": 1, "ratio": "x", "future": 4, "enabled": 1})
    text = "\n".join(errs)
    assert "nope: no such key" in text
    assert "ratio:" in text and "enabled:" in text
    assert "future:" in text and "cannot be set" in text


def test_patch_refuses_duplicate_stored_keys():
    pkg = fx.tflow()
    pkg["pkgConfSchema"].append(dict(pkg["pkgConfSchema"][0]))
    _, _, errs = cf.build_patch(pkg, {"wait-time": 3})
    assert any("twice" in e for e in errs)


def test_change_line_masks_and_flags_changed_passwords():
    pkg = fx.broker()
    _, changes, _ = cf.build_patch(pkg, {"password": "other"})
    line = cf.change_line(changes[0])
    assert "\"********\" -> \"********\" (changed)" in line
    assert fx.SECRET not in line and "other" not in line
    assert "other" in cf.change_line(changes[0], show_secrets=True)


def test_schema_mismatches():
    sent = fx.tflow()
    got = fx.tflow()
    assert cf.schema_mismatches(sent, got) == []
    got["pkgConfSchema"][0]["configValue"] = 99
    assert cf.schema_mismatches(sent, got)[0].startswith("wait-time: read back 99")
    got = fx.tflow()
    got["pkgConfSchema"].reverse()
    assert cf.schema_mismatches(sent, got) == ["key order differs from what was sent"]
    got = fx.tflow()
    got["pkgConfSchema"].pop()
    assert "missing" in cf.schema_mismatches(sent, got)[0]


def test_restore_updates_checks_identity_and_keys():
    pkg = fx.tflow()
    doc = json.loads(json.dumps(cf.backup_doc(fx.SERIAL, pkg, [pkg])))
    ups, errs = cf.restore_updates(doc, fx.SERIAL, pkg)
    assert errs == [] and ups == {"wait-time": 15, "multi-serial-wait-time": 1}
    _, errs = cf.restore_updates(doc, fx.OTHER, pkg)
    assert "serial" in errs[0]
    other = fx.tflow()
    other["pkgConfSchema"].pop()
    _, errs = cf.restore_updates(doc, fx.SERIAL, other)
    assert "keys or types" in errs[0]
    _, errs = cf.restore_updates({"x": 1}, fx.SERIAL, pkg)
    assert "not an lj-config backup" in errs[0]


def test_write_private_mode_and_no_overwrite(tmp_path):
    p = tmp_path / "f.json"
    cf.write_private(str(p), "a")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    with pytest.raises(FileExistsError):
        cf.write_private(str(p), "b")
    assert p.read_text() == "a"
    cf.write_private(str(p), "c", force=True)
    assert p.read_text() == "c"


def test_safe_profile_drops_the_password_hash():
    pairs = cf.profile_pairs(fx.FakeLAS().profiles)
    s, prof = pairs[0]
    shown = cf.safe_profile(s, prof)
    assert "lumberjackPassword" not in shown and shown["serial"] == fx.SERIAL


# ------------------------------------------------------------------- http
def test_unwrap_500_captured_shape():
    text = las_http.error_text(fx.wrapped_500(404, "No configs for package zz found for serial 9999"))
    st, msg, trace = las_http.unwrap_500(text)
    assert st == 404
    assert msg == "No configs for package zz found for serial 9999"
    assert trace == "00000000-0000-4000-8000-000000000000"


def test_unwrap_500_unknown_shape():
    assert las_http.unwrap_500("Something else") is None


def test_http_errors(monkeypatch):
    fake = fx.install(monkeypatch)
    with pytest.raises(las_http.LASError) as e:
        las_http.get_text("TOKEN", "configs_export", serial=fx.SERIAL, package="zz-missing")
    assert e.value.status == 500 and e.value.inner_status == 404
    assert "las-server answered 404: No configs for package zz-missing" in str(e.value)
    assert "Trace-ID" in str(e.value)

    with pytest.raises(las_http.LASError) as e:
        las_http.get_json("TOKEN", "configs", serial=12345)
    assert e.value.status == 403 and "needs Member or Owner" in str(e.value)

    with pytest.raises(las_http.LASError) as e:
        las_http.get_text("TOKEN", "configs_export", serial=fx.SERIAL)
    assert e.value.status == 400 and "Missing 'package'" in str(e.value)

    fake.fail["GET /las/api/v1/lumberjack/configs"] = (500, json.dumps({"error": "boom"}))
    with pytest.raises(las_http.LASError) as e:
        las_http.get_json("TOKEN", "configs", serial=fx.SERIAL)
    assert "HTTP 500" in str(e.value) and "boom" in str(e.value)

    fake.expired = True
    with pytest.raises(las_http.LASError) as e:
        las_http.get_json("TOKEN", "configs", serial=fx.SERIAL)
    assert "onping-login" in str(e.value) and "TOKEN" not in str(e.value)


def test_http_401(monkeypatch):
    fake = fx.install(monkeypatch)
    fake.fail["GET /las/api/v1/is-storage-synced"] = (401, "")
    with pytest.raises(las_http.LASError) as e:
        las_http.get_json("TOKEN", "storage_synced", serial=fx.SERIAL)
    assert "expired" in str(e.value)
