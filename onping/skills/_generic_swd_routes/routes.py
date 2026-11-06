"""Generic-SWD kiosk routes and their transport.

Wire, read from the OnPing source (2026-10-28). Handlers are in
onping/Handler/GenericSWD/Service.hs unless noted:

  POST /generic-swd/kiosk/configs       postGenericSWDKioskConfigsR
       body: [GroupId]; answer: [Kiosk] from Mongo, every kiosk kind
  POST /generic-swd/kiosk/config        postGenericSWDKioskConfigR
       body: {"unKioskUUID": uuid}; answer: FrontendKioskServerConfig, the
       edge token stripped, each lane's PIDs enriched with the PID's
       description and the read PID's raw value, masked value and status
  GET  /generic-swd/kiosk/lanes/UUID    getGenericSWDKioskLanesR
       answer: [{"lane": n, "status": "Available"|...}] or, for a disabled
       lane, {"lane": n, "status": "Disabled", "message": text}. One PID poll
       per lane on the edge; any lane failing fails the whole list (500).
  GET  /generic-swd/kiosk/tickets/N/UUID getGenericSWDKioskTicketsR
       answer: [{"ticketId", "ticketLane", "ticketStatus": {tag, contents}}]
  POST /generic-swd/config/lane/update  postGenericSWDConfigLaneUpdateR
       body: [KioskUUID, FrontendKioskServerConfig]; answer [] on success.
       Replaces the stored name, lanes (sorted by number) and status map and
       keeps the edge token and attribute fields.

Permission and PID routes:

  GET  /permissions/groups/ownership    owned groups, [{key: gid, value: {name}}]
  GET  /permissions/groups/membership   member groups, same shape
  GET  /location/lister/group/GID       [{value: {refId}}], the group's locations
  POST /json/listers/v3/parameters      through _pid_routes.pid_http.lookup_pids

Errors are {"error": text}. These are the only generic-SWD routes this
package knows. The kiosk ticket route and the config add, update and delete
routes are deliberately absent.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the skills root
from _pid_routes.pid_http import lookup_pids  # noqa: E402

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 60
LANES_TIMEOUT_SECONDS = 120  # one edge poll per lane, sequential
SCAN_WORKERS = 8  # concurrent group-location GETs

ROUTES: dict[str, str] = {
    "kiosks": "POST /generic-swd/kiosk/configs",
    "config": "POST /generic-swd/kiosk/config",
    "lanes": "GET /generic-swd/kiosk/lanes/{uuid}",
    "tickets": "GET /generic-swd/kiosk/tickets/{limit}/{uuid}",
    "lane_update": "POST /generic-swd/config/lane/update",
    "owned": "GET /permissions/groups/ownership",
    "member": "GET /permissions/groups/membership",
    "group_locations": "GET /location/lister/group/{gid}",
}

# The one write route. Tests assert nothing else under /generic-swd/ is written.
WRITE_ROUTE = ROUTES["lane_update"]


class RouteFailure(Exception):
    """A request failed (HTTP status, transport, auth redirect, or shape)."""

    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class WriteLost(Exception):
    """The write request was sent, or may have been, and no response came back."""


def _split(endpoint: str) -> tuple[str, str]:
    method, path = endpoint.split(" ", 1)
    return method, path


def _headers(token: str, body: bool) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body:
        h["Content-Type"] = "application/json"
    return h


def _check_auth(resp: requests.Response, endpoint: str) -> None:
    if resp.history and "/auth" in str(resp.url):
        raise RouteFailure(f"{endpoint} redirected to auth; the token may be expired")
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        raise RouteFailure(f"{endpoint} returned HTML; the token may be expired")


def error_text(text: str) -> str:
    """The server's {"error": ...} message, else the body, shortened."""
    try:
        doc = json.loads(text)
        if isinstance(doc, dict) and isinstance(doc.get("error"), str):
            return doc["error"][:600]
    except ValueError:
        pass
    return text[:600]


def call(token: str, endpoint: str, *, body: Any = None, timeout: int = TIMEOUT_SECONDS,
         session: Any = None, **fmt: Any) -> Any:
    """Send one read request and return its decoded JSON. RouteFailure on anything else."""
    method, path = _split(endpoint)
    path = path.format(**fmt)
    shown = f"{method} {path}"
    sender = session if session is not None else requests
    try:
        if method == "GET":
            resp = sender.get(BASE_URL + path, headers=_headers(token, False),
                              allow_redirects=True, timeout=timeout)
        else:
            resp = sender.post(BASE_URL + path, headers=_headers(token, True), json=body,
                               allow_redirects=True, timeout=timeout)
    except requests.RequestException as exc:
        raise RouteFailure(f"{type(exc).__name__} on {shown}") from exc
    _check_auth(resp, shown)
    if not (200 <= resp.status_code < 300):
        raise RouteFailure(f"HTTP {resp.status_code} from {shown}: {error_text(resp.text)}",
                           resp.status_code, resp.text)
    try:
        return resp.json()
    except ValueError as exc:
        raise RouteFailure(f"{shown} did not return JSON") from exc


# ─────────────────────────────── permission reads ───────────────────────────────


def _groups(token: str, key: str) -> dict[str, str | None]:
    payload = call(token, ROUTES[key])
    if not isinstance(payload, list):
        raise RouteFailure(f"{ROUTES[key]} did not return a list of groups")
    out: dict[str, str | None] = {}
    for item in payload:
        gid = item.get("key") if isinstance(item, dict) else None
        value = item.get("value") if isinstance(item, dict) else None
        if not isinstance(gid, str) or not gid or not isinstance(value, dict):
            raise RouteFailure(f"{ROUTES[key]} returned an entry without a group id")
        name = value.get("name")
        out[gid] = name if isinstance(name, str) else None
    return out


def owned_groups(token: str) -> dict[str, str | None]:
    return _groups(token, "owned")


def member_groups(token: str) -> dict[str, str | None]:
    return _groups(token, "member")


def group_locations(token: str, gid: str, session: Any = None) -> list[int]:
    payload = call(token, ROUTES["group_locations"], gid=gid, session=session)
    if not isinstance(payload, list):
        raise RouteFailure(f"GET /location/lister/group/{gid} did not return a list")
    refs = []
    for loc in payload:
        value = loc.get("value") if isinstance(loc, dict) else None
        ref = value.get("refId") if isinstance(value, dict) else None
        if not isinstance(ref, int) or isinstance(ref, bool):
            raise RouteFailure(f"GET /location/lister/group/{gid} returned a location without an integer refId")
        refs.append(ref)
    return refs


def location_groups(token: str, group_ids: list[str], refs: set[int]) -> dict[int, list[str]]:
    """{location refId: [group ids joined to it]}, scanning only the given groups."""
    found: dict[int, list[str]] = {ref: [] for ref in refs}
    if not refs:
        return found
    with requests.Session() as session:
        with ThreadPoolExecutor(SCAN_WORKERS) as pool:
            results = list(pool.map(lambda g: (g, group_locations(token, g, session)), group_ids))
    for gid, got in results:
        for ref in got:
            if ref in found and gid not in found[ref]:
                found[ref].append(gid)
    return found


def lister(token: str, pids: list[int]) -> dict[int, dict]:
    """`_pid_routes.lookup_pids`, with its exit-1 failure as RouteFailure."""
    try:
        return lookup_pids(token, sorted({int(p) for p in pids}))
    except SystemExit as exc:
        raise RouteFailure("the parameter lister failed") from exc


# ─────────────────────────────── generic-SWD reads ───────────────────────────────


def kiosks(token: str, group_ids: list[str]) -> list[dict]:
    payload = call(token, ROUTES["kiosks"], body=list(group_ids))
    if not isinstance(payload, list) or not all(isinstance(k, dict) for k in payload):
        raise RouteFailure(f"{ROUTES['kiosks']} did not return a list of kiosks")
    return payload


def kiosk_config(token: str, uuid: str) -> dict:
    payload = call(token, ROUTES["config"], body={"unKioskUUID": uuid})
    if not isinstance(payload, dict) or "frontendConfigLanes" not in payload:
        raise RouteFailure(f"{ROUTES['config']} did not return a kiosk configuration")
    return payload


def kiosk_lanes(token: str, uuid: str) -> list[dict]:
    payload = call(token, ROUTES["lanes"], uuid=uuid, timeout=LANES_TIMEOUT_SECONDS)
    if not isinstance(payload, list):
        raise RouteFailure("the lane-state route did not return a list")
    return payload


def kiosk_tickets(token: str, uuid: str, limit: int) -> list[dict]:
    payload = call(token, ROUTES["tickets"], uuid=uuid, limit=int(limit))
    if not isinstance(payload, list):
        raise RouteFailure("the ticket route did not return a list")
    return payload


# ─────────────────────────────── the write ───────────────────────────────


def lane_update(token: str, uuid: str, config: dict) -> tuple[int, str]:
    """Send the one write, once. Returns (status, body). WriteLost if no response."""
    method, path = _split(WRITE_ROUTE)
    try:
        resp = requests.post(BASE_URL + path, headers=_headers(token, True),
                             json=[{"unKioskUUID": uuid}, config],
                             allow_redirects=True, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise WriteLost(f"{type(exc).__name__} on {method} {path}") from exc
    if resp.history and "/auth" in str(resp.url):
        return 401, "redirected to auth; the token may be expired"
    return resp.status_code, resp.text
