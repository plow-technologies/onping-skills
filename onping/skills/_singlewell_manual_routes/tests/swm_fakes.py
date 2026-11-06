"""An in-memory OnPing for the singlewell-manual create and delete tests.

`FakeOnPing.install(monkeypatch)` replaces `requests.post` and `requests.get`.
It models the parts of the server the skills depend on, as read from
onping/Handler/SingleWellManual/Service.hs and deleteManualLocationById:

- add writes six records in order (MySQL row, switcher index, manual record,
  Mongo location, extras record, group join) and stops at an injected failure,
  answering 500 with the step and the LocationIdRef, leaving the earlier ones;
- get/loc needs exactly one manual record, one extras record and one group,
  and answers the server's three 400 messages otherwise;
- the site listing is Mongo locations at the site that have an extras record;
- delete models a server before the 2026.11.5.1 fix: it always answers 200,
  removes the manual record, then the Mongo location if found, and leaves
  everything else.

Synthetic ids, names and urls only.
"""

from __future__ import annotations

import copy
import json
from typing import Any
from urllib.parse import urlparse

import requests

LJ = 900001
LJ_URL = "http://lj.example.invalid"
COMPANY = 70001
SITE = 80001
OTHER_SITE = 80002
G_OWNED = "o0000000000000000000000a1"
G_OTHER = "o0000000000000000000000b2"
EXISTING = 30001  # a manual location with parameters
EXISTING_NAME = "zz-existing-manual"


class FakeResponse:
    def __init__(self, status: int, body: Any, url: str, history: list | None = None):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.url = url
        self.history = history or []
        self.headers: dict[str, str] = {}

    def json(self):
        return json.loads(self.text)


class FakeOnPing:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.profiles = {LJ: LJ_URL, 900002: ""}
        self.owned = {G_OWNED: "owned group"}
        self.sites = {COMPANY: {SITE: "site one", OTHER_SITE: "site two"}}
        self.next_ref = 40001
        self.mysql: set[int] = set()
        self.switcher: set[int] = set()
        self.manual: dict[int, dict] = {}
        self.mongo: dict[int, dict] = {}
        self.extras: dict[int, dict] = {}
        self.group_join: dict[int, str] = {}
        # failure injection
        self.add_fail: str | None = None  # "switcher", "1", "2", "3", "4"
        self.add_lose_response = False
        self.add_status_override: tuple[int, Any] | None = None
        self.delete_mode = "normal"  # normal | manual_fails | noop | keep_mongo
        self.delete_lose_response = False
        self.lj_unreachable = False
        self.expired = False
        self.fail_reads: set[str] = set()
        self._seed_existing()

    # ───────────────────────────── seeding ─────────────────────────────

    def _seed_existing(self) -> None:
        ref = EXISTING
        self.mysql.add(ref)
        self.switcher.add(ref)
        self.manual[ref] = {
            "name": EXISTING_NAME,
            "notes": "",
            "tags": [{"tagPid": 990001, "tagLocationId": ref, "tagDesc": "p1"}],
        }
        self.mongo[ref] = {"name": EXISTING_NAME, "site": SITE, "company": COMPANY, "url": LJ_URL}
        self.extras[ref] = {"url": LJ_URL, "port": 13001, "gps": None}
        self.group_join[ref] = G_OWNED

    def seed(self, ref: int, name: str, group: str = G_OWNED, tags: list | None = None) -> int:
        self.mysql.add(ref)
        self.switcher.add(ref)
        self.manual[ref] = {"name": name, "notes": "", "tags": tags or []}
        self.mongo[ref] = {"name": name, "site": SITE, "company": COMPANY, "url": LJ_URL}
        self.extras[ref] = {"url": LJ_URL, "port": 13001, "gps": None}
        self.group_join[ref] = group
        return ref

    # ───────────────────────────── plumbing ─────────────────────────────

    def install(self, monkeypatch) -> "FakeOnPing":
        monkeypatch.setattr(requests, "post", self._post)
        monkeypatch.setattr(requests, "get", self._get)
        return self

    def writes(self) -> list[dict]:
        return [c for c in self.calls if c["path"] in ("/singlewellmanual/location/add", "/singlewellmanual/delete")]

    def _resp(self, status: int, body: Any, url: str) -> FakeResponse:
        if self.expired:
            return FakeResponse(200, "<!DOCTYPE html><html>login</html>", url + "/auth/login", history=[object()])
        return FakeResponse(status, body, url)

    def _get(self, url, headers=None, params=None, **kw):
        path = urlparse(url).path
        self.calls.append({"method": "GET", "path": path, "params": params})
        if path in self.fail_reads:
            return self._resp(500, {"error": "boom"}, url)
        if path == "/las/api/v1/lumberjack/profiles":
            return self._resp(200, [[s, {"lumberjackUrl": u, "lumberjackPassword": "x"}] for s, u in self.profiles.items()], url)
        if path == "/permissions/groups/ownership":
            return self._resp(200, [{"key": g, "value": {"name": n, "gId": g, "oId": "o1", "description": ""}} for g, n in self.owned.items()], url)
        if path == "/json/listers/siteLister":
            company = int(params["getCompanyLookupList"])
            sites = self.sites.get(company, {})
            return self._resp(200, [{"key": f"k{s}", "value": {"cid": company, "delete": 0, "name": n, "pull": 0, "refId": s}} for s, n in sites.items()], url)
        return self._resp(404, {"error": "no route"}, url)

    def _post(self, url, json=None, headers=None, **kw):
        path = urlparse(url).path
        self.calls.append({"method": "POST", "path": path, "body": copy.deepcopy(json)})
        if path in self.fail_reads:
            return self._resp(500, {"error": "boom"}, url)
        if path == "/singlewellmanual/location/add":
            return self._add(json, url)
        if path == "/singlewellmanual/get/loc":
            status, body = self.get_loc(json)
            return self._resp(status, body, url)
        if path == "/singlewellmanual/locations":
            return self._resp(200, self.listing(json), url)
        if path == "/singlewellmanual/delete":
            return self._delete(json, url)
        return self._resp(404, {"error": "no route"}, url)

    # ───────────────────────────── routes ─────────────────────────────

    REQUIRED = ("manualLocationName", "manualLocationUrl", "manualLocationPort", "manualLocationGroupId",
                "locationCompanyId", "locationSiteId", "locationNotes", "locationData")

    def _add(self, body: Any, url: str) -> FakeResponse:
        if self.add_status_override is not None:
            return self._resp(*self.add_status_override, url)
        if not isinstance(body, dict) or any(k not in body for k in self.REQUIRED):
            return self._resp(400, {"error": "postAddSingleWellManualLocationR: Failed to parse JSON request body."}, url)
        if body.get("manualLocationId") is not None:
            return self._resp(500, {"error": "... Use update endpoint instead."}, url)
        ref = self.next_ref
        self.next_ref += 1
        self.mysql.add(ref)

        def fail(msg: str) -> FakeResponse:
            return self._resp(500, {"error": msg}, url)

        if self.add_fail == "switcher":
            return fail(f"postAddSingleWellManualLocationR: Failed to insert switcher index for LocationIdRef {ref} with URL 'u' and port 1. Error: x")
        self.switcher.add(ref)
        if self.add_fail == "1":
            return fail(f"postAddSingleWellManualLocationR: Failed at Step 1 - addNewManualLocation for LocationIdRef {ref}. Error: x")
        self.manual[ref] = {"name": body["manualLocationName"], "notes": body["locationNotes"], "tags": list(body["locationData"])}
        if self.add_fail == "2":
            return fail(f"postAddSingleWellManualLocationR: Failed at Step 2 - insertLocation for LocationIdRef {ref}. Error: x")
        self.mongo[ref] = {"name": body["manualLocationName"], "site": body["locationSiteId"],
                           "company": body["locationCompanyId"], "url": body["manualLocationUrl"]}
        if self.add_fail == "3":
            return fail(f"postAddSingleWellManualLocationR: Failed at Step 3 - insertSingleWellExtras for LocationIdRef {ref} with URL 'u'. Error: x")
        self.extras[ref] = {"url": body["manualLocationUrl"], "port": body["manualLocationPort"], "gps": body.get("coordinates")}
        if self.add_fail == "4":
            return fail(f"postAddSingleWellManualLocationR: Failed at Step 4 - insertLocationGroupJoinHaxl for LocationIdRef {ref} and GroupId x. Error: x")
        self.group_join[ref] = body["manualLocationGroupId"]
        if self.add_lose_response:
            raise requests.ReadTimeout("read timed out")
        return self._resp(200, {"int": ref}, url)

    def get_loc(self, ref: Any) -> tuple[int, Any]:
        if not isinstance(ref, int):
            return 400, {"error": "JSON not properly formatted. "}
        manuals = [] if self.lj_unreachable or ref not in self.manual else [self.manual[ref]]
        swes = [self.extras[ref]] if ref in self.extras else []
        groups = [self.group_join[ref]] if ref in self.mongo and ref in self.group_join else []
        if len(manuals) != 1:
            return 400, {"error": "failed to find single well manual location by id"}
        if len(swes) != 1:
            return 400, {"error": "failed to find single well extras in mongo"}
        if len(groups) != 1:
            return 400, {"error": "failed to find group id by location in mongo"}
        m, s, loc = manuals[0], swes[0], self.mongo[ref]
        return 200, {
            "manualLocationName": m["name"],
            "manualLocationId": None,
            "manualLocationUrl": s["url"],
            "manualLocationPort": s["port"],
            "manualLocationGroupId": groups[0],
            "manualLocationRefId": ref,
            "locationCompanyId": loc["company"],
            "locationSiteId": loc["site"],
            "locationNotes": m["notes"],
            "locationData": m["tags"],
            "coordinates": s["gps"],
        }

    def listing(self, sites: Any) -> list[dict]:
        return [
            {"company": loc["company"], "delete": 0, "name": loc["name"], "refId": ref,
             "site": loc["site"], "slaveId": 1, "url": loc["url"]}
            for ref, loc in sorted(self.mongo.items())
            if loc["site"] in sites and ref in self.extras
        ]

    def _delete(self, body: Any, url: str) -> FakeResponse:
        if not (isinstance(body, list) and len(body) == 1):
            return self._resp(200, {"error": "JSON not properly formatted. Expecting an array, found object instead."}, url)
        ref = body[0]
        if self.delete_mode == "noop":
            result = {"response": "Success"}
        else:
            manual_ok = self.delete_mode != "manual_fails" and ref in self.manual
            if manual_ok:
                del self.manual[ref]
            if ref not in self.mongo:
                result = {"response": "specified singlewell manual could not be extracted from SWE"}
            else:
                if self.delete_mode != "keep_mongo":
                    del self.mongo[ref]
                result = {"response": "Success"} if manual_ok else {"response": "manual server error"}
        if self.delete_lose_response:
            raise requests.ReadTimeout("read timed out")
        return self._resp(200, result, url)
