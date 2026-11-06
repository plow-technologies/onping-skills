"""In-memory fake of the LAS routes, shared by every lj-config-* test suite.

`install(monkeypatch)` patches `requests.request` and returns the FakeLAS. The
shapes follow live reads from 2026-10-28; every serial, name, path, group and
value here is made up.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable
from urllib.parse import urlparse

import requests

SERIAL = 9999           # the synthetic Lumberjack the caller owns
OTHER = 9998            # a Lumberjack the caller does not own (member only)
GROUP = "o000000000000000000000001"
SECRET = "zz-synthetic-secret"


def wrapped_500(status: int, message: str) -> str:
    """OnPing's 500 body around a las-server error, escaped as captured live."""
    inner = (
        'InternalError "TransientError (FailureResponse (Request {requestPath = '
        '(BaseUrl {baseUrlScheme = Http, baseUrlHost = \\"las-server.example\\", '
        'baseUrlPort = 80, baseUrlPath = \\"\\"},\\"/api/v1/lumberjack/configs\\"), '
        'requestMethod = \\"GET\\"}) (Response {responseStatusCode = Status '
        f'{{statusCode = {status}, statusMessage = \\"Not Found\\"}}, responseHeaders = '
        'fromList [], responseHttpVersion = HTTP/1.1, responseBody = \\"'
        + message.replace("\n", "\\\\n")
        + '\\\\n\\\\nTrace-ID:00000000-0000-4000-8000-000000000000\\"}))"'
    )
    return json.dumps({"error": inner})


def tflow() -> dict:
    return {
        "pkgConfName": "single-well-tflow",
        "pkgConfMonitorName": "swtflow",
        "pkgConfPath": "/srv/example/configs/single-well-tflow-editable-config.yaml",
        "pkgConfSchema": [
            {"configKey": "wait-time", "configType": {"tag": "CInteger"}, "configValue": 15},
            {"configKey": "multi-serial-wait-time", "configType": {"tag": "CInteger"},
             "configValue": 1},
        ],
    }


def broker() -> dict:
    return {
        "pkgConfName": "client-mosquitto-broker",
        "pkgConfMonitorName": "",
        "pkgConfPath": "/srv/example/configs/client-mosquitto-broker-editable-config.yaml",
        "pkgConfSchema": [
            {"configKey": "username", "configType": {"tag": "CText"}, "configValue": "zz-user"},
            {"configKey": "password", "configType": {"tag": "CPassword"}, "configValue": SECRET},
            {"configKey": "port", "configType": {"tag": "CPort"}, "configValue": 1883},
            {"configKey": "uri", "configType": {"tag": "CURL"}, "configValue": "mqtt://127.0.0.1"},
        ],
    }


def kitchen_sink() -> dict:
    return {
        "pkgConfName": "zz-kitchen-sink",
        "pkgConfMonitorName": "zzsink",
        "pkgConfPath": "/srv/example/configs/zz-kitchen-sink-editable-config.yaml",
        "pkgConfSchema": [
            {"configKey": "ratio", "configType": {"tag": "CFloat"}, "configValue": 0.5},
            {"configKey": "enabled", "configType": {"tag": "CBool"}, "configValue": True},
            {"configKey": "label", "configType": {"tag": "CText"}, "configValue": "a"},
            {"configKey": "maybe-port", "configType": {"tag": "CMaybe", "contents": {"tag": "CPort"}},
             "configValue": None},
            {"configKey": "hosts", "configType": {"tag": "CList", "contents": {"tag": "CText"}},
             "configValue": ["h1"]},
            {"configKey": "tokens",
             "configType": {"tag": "CList", "contents": {"tag": "CPassword"}},
             "configValue": [SECRET, SECRET + "2"]},
            {"configKey": "future", "configType": {"tag": "CDuration"}, "configValue": 3},
        ],
    }


def profile(name: str) -> dict:
    return {
        "lumberjackArch": "x86_64-linux",
        "lumberjackCapabilities": [],
        "lumberjackDownloadOptions": {},
        "lumberjackGroup": GROUP,
        "lumberjackInternetSource": [],
        "lumberjackName": name,
        "lumberjackPassword": "$2b$10$zzSyntheticBcryptHashzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        "lumberjackTimezone": "UTC",
        "lumberjackUrl": "http://zz-synthetic.example",
    }


class FakeResponse:
    def __init__(self, status: int, text: str, ctype: str = "application/json",
                 url: str = "", history: list | None = None):
        self.status_code = status
        self.text = text
        self.headers = {"content-type": ctype}
        self.url = url
        self.history = history or []

    def json(self) -> Any:
        return json.loads(self.text)


class FakeLAS:
    def __init__(self) -> None:
        self.profiles: list = [[SERIAL, profile("Synthetic Sim LJ")],
                               [9997, profile("Another Synthetic LJ")]]
        self.configs: dict[int, list[dict]] = {
            SERIAL: [tflow(), broker(), kitchen_sink()],
            OTHER: [tflow()],
        }
        self.synced: dict[int, bool] = {SERIAL: True, OTHER: True}
        # After a POST, is-storage-synced turns true after this many polls (None = never).
        self.ack_after_polls: int | None = 0
        self.bridge: Any = None
        self.fail: dict[str, tuple[int, str]] = {}   # "METHOD path" -> (status, body)
        self.expired = False
        self.on_post: Callable[[int, dict], None] | None = None
        self.on_get_configs: Callable[[int, int], None] | None = None  # (serial, n-th GET)
        self.calls: list[tuple[str, str, dict, Any]] = []
        self._polls_since_post: int | None = None
        self._config_gets = 0

    # ---------------------------------------------------------------- helpers
    def posts(self) -> list[tuple[str, str, dict, Any]]:
        return [c for c in self.calls if c[0] == "POST"]

    def pkg(self, serial: int, name: str) -> dict:
        for c in self.configs[serial]:
            if c["pkgConfName"] == name:
                return c
        raise KeyError(name)

    # ---------------------------------------------------------------- routing
    def request(self, method: str, url: str, params=None, headers=None, data=None,
                allow_redirects=True, timeout=None, **_: Any) -> FakeResponse:
        path = urlparse(url).path
        params = dict(params or {})
        body = json.loads(data) if data else None
        self.calls.append((method, path, params, body))
        assert headers and headers.get("Authorization", "").startswith("Bearer ")
        if self.expired:
            return FakeResponse(200, "<!DOCTYPE html><html>login</html>", "text/html",
                                url="https://x/auth/login", history=[object()])
        key = f"{method} {path}"
        if key in self.fail:
            st, text = self.fail[key]
            return FakeResponse(st, text)
        if path == "/las/api/v1/lumberjack/profiles":
            return FakeResponse(200, json.dumps(self.profiles))
        try:
            serial = int(params.get("serial"))
        except (TypeError, ValueError):
            return FakeResponse(400, json.dumps("Invalid or missing 'serial' query param"))
        if serial not in self.configs:
            return FakeResponse(403, json.dumps("User is not authorized to access Lumberjack"))
        owned = any(s == serial for s, _ in self.profiles)
        if path == "/las/api/v1/is-storage-synced":
            if self._polls_since_post is not None:
                self._polls_since_post += 1
                if self.ack_after_polls is not None and \
                        self._polls_since_post > self.ack_after_polls:
                    self.synced[serial] = True
            return FakeResponse(200, json.dumps(self.synced[serial]))
        if path == "/las/api/v1/is-mqtt-bridge-up":
            return FakeResponse(200, json.dumps(self.bridge))
        if path == "/las/api/v1/lumberjack/configs" and method == "GET":
            self._config_gets += 1
            if self.on_get_configs:
                self.on_get_configs(serial, self._config_gets)
            return FakeResponse(200, json.dumps(self.configs[serial]))
        if path == "/las/api/v1/lumberjack/configs" and method == "POST":
            if not owned:
                return FakeResponse(403, json.dumps("User is not authorized to access Lumberjack"))
            name = body["pkgConfName"]
            try:
                stored = self.pkg(serial, name)
            except KeyError:
                return FakeResponse(500, wrapped_500(
                    404, f"No configs for package {name} found for serial {serial}"))
            stored["pkgConfSchema"] = copy.deepcopy(body["pkgConfSchema"])
            if self.on_post:
                self.on_post(serial, stored)
            self.synced[serial] = False
            self._polls_since_post = 0
            return FakeResponse(200, "")
        if path == "/las/api/v1/lumberjack/configs/export":
            if not owned:
                return FakeResponse(403, json.dumps("User is not authorized to access Lumberjack"))
            name = params.get("package")
            if not name:
                return FakeResponse(400, json.dumps("Missing 'package' query param"))
            try:
                pkg = self.pkg(serial, name)
            except KeyError:
                return FakeResponse(500, wrapped_500(
                    404, f"No configs for package {name} found for serial {serial}"))
            lines = [f"{e['configKey']}: {json.dumps(e['configValue'])}"
                     for e in sorted(pkg["pkgConfSchema"], key=lambda e: e["configKey"])]
            return FakeResponse(200, "\n".join(lines) + "\n", "text/plain; charset=utf-8")
        return FakeResponse(404, json.dumps({"error": f"fake: no route {key}"}))


def install(monkeypatch) -> FakeLAS:
    fake = FakeLAS()
    monkeypatch.setattr(requests, "request", fake.request)
    return fake
