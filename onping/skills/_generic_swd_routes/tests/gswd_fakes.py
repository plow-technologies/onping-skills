"""An in-memory OnPing for the generic-SWD skill tests.

`install(monkeypatch)` replaces `requests.post`, `requests.get` and
`requests.Session`, so `_generic_swd_routes.routes` and `_pid_routes.pid_http`
both reach the fake. It models:

- the permission graph (owned and member groups) and the group-location lister;
- kiosk/configs, which returns the kiosks of whatever groups are sent;
- kiosk/config, which returns the stored configuration enriched with each read
  PID's raw value, masked value (None when the script "fails") and status;
- the lane-state GET, which fails as a whole when any lane's masked value has
  no status-map entry or its script fails;
- the ticket GET, the parameter lister, and the lane update.

Synthetic UUIDs, group ids and PIDs only.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable
from urllib.parse import urlparse

import requests

G_OWN = "o0000000000000000000ga01"
G_MEM = "o0000000000000000000gb01"
G_FOREIGN = "o0000000000000000000gf01"
K_OWN = "11111111-1111-4111-8111-111111111111"
K_MEM = "22222222-2222-4222-8222-222222222222"
K_FOREIGN = "33333333-3333-4333-8333-333333333333"
UNKNOWN = "44444444-4444-4444-8444-444444444444"
READ_1, WRITE_1 = 600101, 600102
READ_2, WRITE_2 = 600201, 600202
LOC_OWN, LOC_MEM, LOC_SPLIT = 30001, 30002, 30003
RO_PID = 600301  # visible, read-only
MEM_PID = 600401  # at a location in the member group
SPLIT_PID = 600501  # at a location joined to two groups

STATUS_MAP = [[0.0, "Available"], [1.0, "WaitingToStart"], [2.0, "Pumping"], [3.0, {"disabled": "Interlock open"}]]


def lane(number: int, read: int, write: int, script: str = "", wait: float = 1.0) -> dict:
    p = lambda pid: {"laneParamPID": pid, "laneParamName": None, "laneParamRawValue": None,  # noqa: E731
                     "laneParamMaskedValue": None, "laneParamStatus": None}
    return {"frontendLaneNumber": number, "frontendLaneReadPID": p(read), "frontendLaneReadMaskScript": script,
            "frontendLaneWritePID": p(write), "frontendLaneWriteWaitingToStartVal": wait}


def base_config() -> dict:
    return {"frontendConfigName": "Example kiosk", "frontendConfigLanes": [lane(1, READ_1, WRITE_1)],
            "frontendConfigStatusMap": copy.deepcopy(STATUS_MAP)}


class FakeResponse:
    def __init__(self, status: int, body: Any, url: str):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.url = url
        self.history: list = []
        self.headers: dict[str, str] = {}

    def json(self):
        return json.loads(self.text)


class FakeOnPing:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.owned = {G_OWN: "exampleOwners"}
        self.member = {G_MEM: "exampleMembers"}
        self.kiosks = [
            {"kioskUUID": {"unKioskUUID": K_OWN}, "kioskIP": "10.0.0.1", "kioskPort": 13033,
             "kioskName": "Owned kiosk", "kioskGroupId": G_OWN},
            {"kioskUUID": {"unKioskUUID": K_MEM}, "kioskIP": "10.0.0.2", "kioskPort": 13033,
             "kioskName": "Member kiosk", "kioskGroupId": G_MEM},
            {"kioskUUID": {"unKioskUUID": K_FOREIGN}, "kioskIP": "10.0.0.3", "kioskPort": 13033,
             "kioskName": "Foreign kiosk", "kioskGroupId": G_FOREIGN},
        ]
        self.configs: dict[str, dict] = {K_OWN: base_config(), K_MEM: base_config(), K_FOREIGN: base_config()}
        # PID -> (location, writeability, current raw value)
        self.pids: dict[int, tuple[int, str, float]] = {
            READ_1: (LOC_OWN, "TagWriteable", 0.0), WRITE_1: (LOC_OWN, "TagWriteable", 0.0),
            READ_2: (LOC_OWN, "TagWriteable", 2.0), WRITE_2: (LOC_OWN, "TagWriteable", 0.0),
            RO_PID: (LOC_OWN, "TagReadOnly", 0.0), MEM_PID: (LOC_MEM, "TagWriteable", 0.0),
            SPLIT_PID: (LOC_SPLIT, "TagWriteable", 0.0),
        }
        self.location_groups = {LOC_OWN: [G_OWN], LOC_MEM: [G_MEM], LOC_SPLIT: [G_OWN, G_MEM]}
        self.tickets = [{"ticketId": "000000001", "ticketLane": 1,
                         "ticketStatus": {"tag": "TicketCompleted", "contents": {}}}]
        self.ownership_status = 200
        self.lister_status = 200
        self.lanes_fail = False
        self.update_overrides: list[Any] = []  # (status, body) or an exception, one per update
        self.on_config_read: list[Callable[["FakeOnPing"], None]] = []  # one hook per config read
        self.after_update: Callable[["FakeOnPing", dict], None] | None = None
        self.config_reads = 0

    # ── test helpers ──
    def paths(self) -> list[str]:
        return [f"{c['method']} {c['path']}" for c in self.calls]

    def writes(self) -> list[dict]:
        return [c for c in self.calls if c["method"] == "POST" and c["path"] == "/generic-swd/config/lane/update"]

    def generic_swd_paths(self) -> list[str]:
        return [p for p in self.paths() if "/generic-swd/" in p]

    # ── transport ──
    def post(self, url, headers=None, json=None, **kw):
        return self._handle("POST", url, json)

    def get(self, url, headers=None, params=None, **kw):
        return self._handle("GET", url, None)

    def session(self):
        return FakeSession(self)

    @staticmethod
    def _masked(raw: float, script: str) -> float | None:
        if script == "":
            return raw
        if "FAIL" in script:
            return None
        return raw

    def _enriched(self, uuid: str) -> dict:
        cfg = copy.deepcopy(self.configs[uuid])
        smap = {float(v): s for v, s in cfg["frontendConfigStatusMap"]}
        for ln in cfg["frontendConfigLanes"]:
            rd = ln["frontendLaneReadPID"]
            info = self.pids.get(rd["laneParamPID"])
            rd["laneParamName"] = f"P{rd['laneParamPID']}"
            ln["frontendLaneWritePID"]["laneParamName"] = f"P{ln['frontendLaneWritePID']['laneParamPID']}"
            if info:
                rd["laneParamRawValue"] = info[2]
                rd["laneParamMaskedValue"] = self._masked(info[2], ln["frontendLaneReadMaskScript"])
                if rd["laneParamMaskedValue"] is not None:
                    rd["laneParamStatus"] = smap.get(float(rd["laneParamMaskedValue"]))
        return cfg

    def _handle(self, method: str, url: str, body: Any) -> FakeResponse:
        path = urlparse(url).path
        self.calls.append({"method": method, "path": path, "body": copy.deepcopy(body)})
        r = lambda status, b: FakeResponse(status, b, url)  # noqa: E731
        groups = lambda d: [{"key": g, "value": {"name": n}} for g, n in d.items()]  # noqa: E731
        if method == "GET" and path == "/permissions/groups/ownership":
            if self.ownership_status != 200:
                return r(self.ownership_status, {"error": "PermissionGraphError"})
            return r(200, groups(self.owned))
        if method == "GET" and path == "/permissions/groups/membership":
            return r(200, groups(self.member))
        if method == "GET" and path.startswith("/location/lister/group/"):
            gid = path.rsplit("/", 1)[1]
            return r(200, [{"key": f"loc{ref}", "value": {"refId": ref}}
                           for ref, gids in self.location_groups.items() if gid in gids])
        if method == "POST" and path == "/json/listers/v3/parameters":
            if self.lister_status != 200:
                return r(self.lister_status, {"error": "lister down"})
            out = []
            for key in body["preq_query"]["contents"]:
                pid = key["keyValue"]
                if pid in self.pids:
                    loc, wr, val = self.pids[pid]
                    out.append({"tagInfo": {"parameterId": pid, "locationId": loc, "description": f"P{pid}",
                                            "writeability": wr, "result": {"value": val, "tag": "OnPingDouble"}},
                                "tagLocations": [{"name": "Fake location"}]})
            return r(200, out)
        if method == "POST" and path == "/generic-swd/kiosk/configs":
            return r(200, [copy.deepcopy(k) for k in self.kiosks if k["kioskGroupId"] in body])
        if method == "POST" and path == "/generic-swd/kiosk/config":
            uuid = body["unKioskUUID"]
            if self.on_config_read:
                self.on_config_read.pop(0)(self)
            self.config_reads += 1
            if uuid not in self.configs:
                return r(500, {"error": "InternalError \"FailureResponse ...\""})
            return r(200, self._enriched(uuid))
        if method == "GET" and path.startswith("/generic-swd/kiosk/lanes/"):
            uuid = path.rsplit("/", 1)[1]
            if self.lanes_fail:
                return r(500, {"error": "Error in $: failed to lookup masked value"})
            cfg = self._enriched(uuid)
            out = []
            for ln in cfg["frontendConfigLanes"]:
                st = ln["frontendLaneReadPID"]["laneParamStatus"]
                if st is None:
                    return r(500, {"error": f"lane {ln['frontendLaneNumber']}: failed to apply mask or lookup"})
                if isinstance(st, dict):
                    out.append({"lane": ln["frontendLaneNumber"], "status": "Disabled", "message": st["disabled"]})
                else:
                    out.append({"lane": ln["frontendLaneNumber"], "status": st})
            return r(200, out)
        if method == "GET" and path.startswith("/generic-swd/kiosk/tickets/"):
            return r(200, copy.deepcopy(self.tickets))
        if method == "POST" and path == "/generic-swd/config/lane/update":
            if self.update_overrides:
                item = self.update_overrides.pop(0)
                if isinstance(item, BaseException):
                    raise item
                if item[0] != "store":
                    return r(item[0], item[1])
            uuid, cfg = body[0]["unKioskUUID"], copy.deepcopy(body[1])
            cfg["frontendConfigLanes"].sort(key=lambda ln: ln["frontendLaneNumber"])
            cfg["frontendConfigStatusMap"] = sorted({float(v): s for v, s in cfg["frontendConfigStatusMap"]}.items())
            cfg["frontendConfigStatusMap"] = [[v, s] for v, s in cfg["frontendConfigStatusMap"]]
            self.configs[uuid] = cfg
            if self.after_update:
                self.after_update(self, cfg)
            return r(200, [])
        return r(404, {"error": f"fake has no route {method} {path}"})


class FakeSession:
    def __init__(self, fake: FakeOnPing) -> None:
        self.fake = fake

    def get(self, url, **kw):
        return self.fake.get(url, **kw)

    def post(self, url, **kw):
        return self.fake.post(url, **kw)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass


def install(monkeypatch) -> FakeOnPing:
    fake = FakeOnPing()
    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    monkeypatch.setattr(requests, "Session", fake.session)
    return fake
