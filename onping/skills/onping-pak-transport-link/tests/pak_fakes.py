"""A fake OnPing for the onping-pak-transport-link tests.

It models the handler and cloud-app behaviour read from source: list filters
to requested AND owned serials; repsert checks ownership of the
request's serial and of the stored record's serial; delete checks the stored
record's serial; the cloud app's validation answers 400, which OnPing
surfaces as a 500. All values here are synthetic.
"""

from __future__ import annotations

import copy
import json
from typing import Any
from urllib.parse import urlparse

import requests

G_MINE = "11111111-1111-4111-8111-111111111111"
G_OTHER = "22222222-2222-4222-8222-222222222222"
LJ_A, LJ_B, LJ_C, LJ_FOREIGN = 9101, 9102, 9103, 9199  # A, B, C owned; FOREIGN not
CFG_A = "aaaaaaaa-0000-4000-8000-00000000000a"
CFG_FOREIGN = "ffffffff-0000-4000-8000-00000000000f"

LIST = ("POST", "/pak-transport-ticket-permissive/config")
REPSERT = ("POST", "/pak-transport-ticket-permissive/config/repsert")
DELETE = ("POST", "/pak-transport-ticket-permissive/config/delete")
WRITE_ROUTES = {REPSERT, DELETE}


def record(cid: str, serial: int, maps: list[tuple[int, int]], name: str = "Example Facility",
           url: str = "10.0.0.5", port: int = 13180, fid: str = "FAC01") -> dict:
    return {
        "pakTransportConfigId": cid,
        "pakTransportFacilityId": fid,
        "pakTransportFacilityName": name,
        "pakTransportLumberjackId": serial,
        "pakTransportLumberjackUrl": url,
        "pakTransportLumberjackPort": port,
        "pakTransportBayLaneMappings": [{"bayLaneBayId": b, "bayLaneLaneNumber": l} for b, l in maps],
    }


class FakeResponse:
    def __init__(self, status: int, body: Any, url: str, headers: dict | None = None):
        self.status_code = status
        self.text = body if isinstance(body, str) and body.lstrip().startswith("<") else json.dumps(body)
        self.url = url
        self.history: list = []
        self.headers: dict[str, str] = headers or {}

    def json(self):
        return json.loads(self.text)


class FakeOnPing:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.owned_groups = {G_MINE}
        self.profiles: dict[int, dict] = {
            LJ_A: {"lumberjackGroup": G_MINE, "lumberjackUrl": "10.0.0.5"},
            LJ_B: {"lumberjackGroup": G_MINE, "lumberjackUrl": "lj-b.example.net"},
            LJ_C: {"lumberjackGroup": G_MINE, "lumberjackUrl": ""},
            LJ_FOREIGN: {"lumberjackGroup": G_OTHER, "lumberjackUrl": "10.0.0.9"},
        }
        self.store: dict[str, dict] = {
            CFG_A: record(CFG_A, LJ_A, [(38, 1)]),
            CFG_FOREIGN: record(CFG_FOREIGN, LJ_FOREIGN, [(50, 2)], name="Other Facility"),
        }
        self.switcher_fails = False  # the cloud app answers 502, stores nothing
        self.list_override: Any = None  # (status, body) for every list call
        self.write_override: Any = None  # (status, body) or an Exception, for the next write
        self.redirect_all = False
        self.after_write = None  # callable(fake) run after a stored write

    # ── helpers ──
    def writes(self) -> list[dict]:
        return [c for c in self.calls if (c["method"], c["path"]) in WRITE_ROUTES]

    def owned(self) -> set[int]:
        return {s for s, p in self.profiles.items() if p["lumberjackGroup"] in self.owned_groups}

    # ── transport ──
    def request(self, method, url, headers=None, data=None, json=None, **kw):
        body = json if json is not None else (None if data is None else _json_loads(data))
        return self._handle(method.upper(), url, body)

    def _handle(self, method: str, url: str, body: Any) -> FakeResponse:
        path = urlparse(url).path
        self.calls.append({"method": method, "path": path, "body": copy.deepcopy(body)})
        r = lambda status, b: FakeResponse(status, b, url)  # noqa: E731
        if self.redirect_all:
            return FakeResponse(303, "", url, {"Location": "/auth/login"})
        key = (method, path)
        if key == ("GET", "/permissions/groups/ownership"):
            return r(200, [{"key": g, "value": {"name": "g"}} for g in sorted(self.owned_groups)])
        if key == ("GET", "/las/api/v1/lumberjack/profiles"):
            return r(200, [[s, dict(p)] for s, p in sorted(self.profiles.items())])
        if key == LIST:
            if self.list_override is not None:
                return r(*self.list_override)
            wanted = set(body) & self.owned()
            return r(200, [copy.deepcopy(c) for c in self.store.values() if c["pakTransportLumberjackId"] in wanted])
        if key in WRITE_ROUTES and self.write_override is not None:
            o, self.write_override = self.write_override, None
            if isinstance(o, Exception):
                raise o
            return r(*o)
        if key == REPSERT:
            stored = self.store.get(body["pakTransportConfigId"])
            if stored and stored["pakTransportLumberjackId"] not in self.owned():
                return r(403, "Insufficient permissions for this lumberjack")
            if body["pakTransportLumberjackId"] not in self.owned():
                return r(403, "Insufficient permissions for this lumberjack")
            err = self._cloud_validate(body)
            if err:
                return r(500, wrapped(400, err))
            if self.switcher_fails:
                return r(500, wrapped(502, "could not register the lumberjack in the switcher"))
            stored = copy.deepcopy(body)
            stored["pakTransportBayLaneMappings"].sort(key=lambda m: m["bayLaneBayId"])
            self.store[body["pakTransportConfigId"]] = stored
            if self.after_write:
                self.after_write(self)
            return r(200, [])
        if key == DELETE:
            cur = self.store.get(body)
            if cur is None:
                return r(404, "Config not found")
            if cur["pakTransportLumberjackId"] not in self.owned():  # STORED serial
                return r(403, "Insufficient permissions for this lumberjack")
            del self.store[body]
            return r(200, [])
        return r(404, f"no fake route {method} {path}")

    def _cloud_validate(self, body: dict) -> str | None:
        maps = body["pakTransportBayLaneMappings"]
        if not maps:
            return "pakTransportBayLaneMappings must not be empty"
        bays = [m["bayLaneBayId"] for m in maps]
        if len(set(bays)) != len(bays):
            return "pakTransportBayLaneMappings must not repeat a bay ID"
        others = [c for c in self.store.values() if c["pakTransportConfigId"] != body["pakTransportConfigId"]]
        if any(c["pakTransportLumberjackId"] == body["pakTransportLumberjackId"] for c in others):
            return "another configuration already exists for this lumberjack"
        taken = {m["bayLaneBayId"] for c in others for m in c["pakTransportBayLaneMappings"]}
        if taken & set(bays):
            return f"bay ID(s) already mapped by another configuration: {sorted(taken & set(bays))}"
        return None


def wrapped(status: int, message: str) -> dict:
    """OnPing's HTTP 500 body for a cloud-app error, in the shape seen live:
    the Haskell show of servant's FailureResponse, inner quotes escaped."""
    q = '\\"'
    esc = message.replace("\\", "\\\\").replace('"', q)
    return {
        "error": (
            f'InternalError "FailureResponse (Request {{requestPath = (BaseUrl {{baseUrlScheme = Http, '
            f'baseUrlHost = {q}pak-transport-ticket-permissive.service.consul{q}, baseUrlPort = 13096, '
            f'baseUrlPath = {q}{q}}},{q}/config/repsert{q}), requestMethod = {q}POST{q}}}) '
            f'(Response {{responseStatusCode = Status {{statusCode = {status}, statusMessage = {q}x{q}}}, '
            f'responseHeaders = fromList [], responseHttpVersion = HTTP/1.1, responseBody = {q}{esc}{q}}})"'
        )
    }


def _json_loads(data: Any) -> Any:
    return json.loads(data) if isinstance(data, (str, bytes)) else data


def install(monkeypatch) -> FakeOnPing:
    fake = FakeOnPing()
    monkeypatch.setattr(requests, "request", fake.request)
    return fake
