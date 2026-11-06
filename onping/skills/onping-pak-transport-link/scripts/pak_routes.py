# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Skill-local routes, transport and checks for onping-pak-transport-link.

Wire, read from the OnPing and cloud-app source (2026-10-27, after the
bay-to-lane change that deployed 2026-10-28):

  POST /pak-transport-ticket-permissive/config         body [LJSerial, ...]
       200, a bare JSON array of PakTransportTicketPermissiveConfig. The
       handler fetches every config, then keeps those whose
       pakTransportLumberjackId is in the body AND owned by the caller.
       Unowned or unrequested serials are dropped with no marker.
  POST /pak-transport-ticket-permissive/config/repsert body: one whole config
       200, body []. Create-or-overwrite keyed by pakTransportConfigId.
       403 "Insufficient permissions for this lumberjack" (bare JSON string).
       The cloud app answers 400 for the rejections mirrored by preflight()
       and 502 when it cannot register the switcher route (nothing stored).
       OnPing wraps either as HTTP 500 {"error": "InternalError \"FailureResponse
       ... statusCode = 400 ... responseBody = \"<message>\"})\""}; see
       cloud_error(). (Seen live 2026-10-28.)
  POST /pak-transport-ticket-permissive/config/delete  body: "<uuid>"
       200, body []. 404 "Config not found", 403 as above. Hard delete.
  GET  /las/api/v1/lumberjack/profiles                 [[serial, Profile], ...]
  GET  /permissions/groups/ownership                   [{key: groupId, value}, ...]

Ownership: OnPing's rule is "the LJ's lumberjackGroup is one of the caller's
owned groups" (profiles x ownership, the same two reads its handler makes).
The repsert handler applies that rule to the serial in the request and to the
LJ of the record already stored under the UUID; delete applies it to the stored
record. The skill applies the rule first: it loads the stored record through
the list route and refuses unless the caller owns its LJ, so a refusal sends
no write.

The record (7 fields; bay mappings stored sorted by bay id):
  pakTransportConfigId      UUID string, client-minted
  pakTransportFacilityId    string, sent to the LJ with each ticket
  pakTransportFacilityName  string, display
  pakTransportLumberjackId  int, the routing target
  pakTransportLumberjackUrl string, host registered in the switcher
  pakTransportLumberjackPort int, the lj app's serverPort (13180 by default)
  pakTransportBayLaneMappings [{bayLaneBayId: Word64, bayLaneLaneNumber: Word64}]
"""

from __future__ import annotations

import json
import os
import re
import uuid as uuidlib
from typing import Any

import requests

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net").rstrip("/")
TIMEOUT_SECONDS = 60

LIST = "POST /pak-transport-ticket-permissive/config"
REPSERT = "POST /pak-transport-ticket-permissive/config/repsert"
DELETE = "POST /pak-transport-ticket-permissive/config/delete"
PROFILES = "GET /las/api/v1/lumberjack/profiles"
OWNERSHIP = "GET /permissions/groups/ownership"

FIELDS = (
    "pakTransportConfigId",
    "pakTransportFacilityId",
    "pakTransportFacilityName",
    "pakTransportLumberjackId",
    "pakTransportLumberjackUrl",
    "pakTransportLumberjackPort",
    "pakTransportBayLaneMappings",
)
# Fields of the record before the bay-to-lane change. Seeing one means the
# server still runs the old cloud app, and this skill must not write to it.
OLD_SHAPE_FIELDS = (
    "pakTransportExchangeName",
    "pakTransportQueueName",
    "pakTransportStatusExchangeName",
    "pakTransportDropOffRawQueueName",
)
DEFAULT_PORT = 13180
WORD64_MAX = 2**64 - 1
FORBIDDEN_403 = "Insufficient permissions for this lumberjack"
NOT_FOUND_404 = "Config not found"


class RouteFailure(Exception):
    """A read failed: transport, HTTP status, auth redirect or response shape."""


class ShapeError(RouteFailure):
    """The server returned a record that is not the 7-field shape."""


# ─────────────────────────────── transport ───────────────────────────────


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _check_auth(resp: requests.Response, endpoint: str) -> None:
    # An expired token answers 303 -> /auth/login. Redirects are not followed,
    # so a login page can never be read as a result.
    if 300 <= resp.status_code < 400:
        raise RouteFailure(
            f"{endpoint}: HTTP {resp.status_code} redirect (to {resp.headers.get('Location', '?')}); "
            "the access token is probably expired"
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        raise RouteFailure(f"{endpoint}: got an HTML page instead of JSON; the access token may be expired")


def send(token: str, endpoint: str, body: Any = None) -> requests.Response:
    """One request, no retry. Raises RouteFailure on a transport error or an
    auth redirect; returns any other response for the caller to classify."""
    method, path = endpoint.split(" ", 1)
    try:
        resp = requests.request(
            method,
            BASE_URL + path,
            headers=_headers(token),
            data=None if body is None else json.dumps(body),
            allow_redirects=False,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RouteFailure(f"{endpoint}: request error: {exc}") from exc
    _check_auth(resp, endpoint)
    return resp


def _read(token: str, endpoint: str, body: Any = None) -> Any:
    resp = send(token, endpoint, body)
    if resp.status_code != 200:
        raise RouteFailure(f"{endpoint}: HTTP {resp.status_code}: {body_text(resp)}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RouteFailure(f"{endpoint}: response is not JSON") from exc


def body_text(resp: requests.Response, limit: int = 500) -> str:
    """The response body as text. OnPing's 403/404 bodies are bare JSON strings."""
    try:
        parsed = resp.json()
    except ValueError:
        return resp.text[:limit]
    if isinstance(parsed, str):
        return parsed[:limit]
    return json.dumps(parsed)[:limit]


_CLOUD_STATUS = re.compile(r"responseStatusCode = Status \{statusCode = (\d+)")
_CLOUD_BODY = re.compile(r'responseBody = \\"(.*)\\"\}\)"?\s*$', re.S)


def cloud_error(resp: requests.Response) -> tuple[int | None, str | None]:
    """(cloud status, cloud message) from OnPing's wrapped 500, else (None, None).

    OnPing passes a cloud-app error on as HTTP 500 whose JSON "error" string is
    the Haskell show of the servant FailureResponse, inner quotes escaped.
    """
    try:
        parsed = resp.json()
    except ValueError:
        return None, None
    err = parsed.get("error") if isinstance(parsed, dict) else None
    if not isinstance(err, str) or "FailureResponse" not in err:
        return None, None
    status = _CLOUD_STATUS.search(err)
    body = _CLOUD_BODY.search(err)
    msg = body.group(1).replace('\\"', '"').replace("\\\\", "\\") if body else None
    return (int(status.group(1)) if status else None), msg


# ─────────────────────────────── reads ───────────────────────────────


def owned_group_ids(token: str) -> set[str]:
    payload = _read(token, OWNERSHIP)
    if not isinstance(payload, list):
        raise RouteFailure(f"{OWNERSHIP}: expected a list of groups")
    out: set[str] = set()
    for item in payload:
        gid = item.get("key") if isinstance(item, dict) else None
        if not isinstance(gid, str) or not gid:
            raise RouteFailure(f"{OWNERSHIP}: an entry has no group id")
        out.add(gid)
    return out


def profiles(token: str) -> dict[int, dict]:
    """{serial: LAS profile} for every profile the caller can see."""
    payload = _read(token, PROFILES)
    if not isinstance(payload, list):
        raise RouteFailure(f"{PROFILES}: expected a list of [serial, profile] pairs")
    out: dict[int, dict] = {}
    for item in payload:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or isinstance(item[0], bool)
            or not isinstance(item[0], int)
            or not isinstance(item[1], dict)
        ):
            raise RouteFailure(f"{PROFILES}: an entry is not a [serial, profile] pair")
        out[item[0]] = item[1]
    return out


class Ownership:
    """The caller's owned LJ serials, computed the way OnPing's handler does."""

    def __init__(self, token: str):
        groups = owned_group_ids(token)
        self.profiles = profiles(token)
        self.owned: set[int] = {
            serial for serial, prof in self.profiles.items() if prof.get("lumberjackGroup") in groups
        }

    def owns(self, serial: int) -> bool:
        return serial in self.owned

    def default_url(self, serial: int) -> str | None:
        url = (self.profiles.get(serial) or {}).get("lumberjackUrl")
        return url.strip() if isinstance(url, str) and url.strip() else None


def check_record(rec: Any, where: str) -> dict:
    """Refuse anything that is not exactly the 7-field record."""
    if not isinstance(rec, dict):
        raise ShapeError(f"{where}: a config is not a JSON object")
    old = [k for k in OLD_SHAPE_FIELDS if k in rec]
    if old or "pakTransportBayLaneMappings" not in rec:
        raise ShapeError(
            f"{where}: the server returned the OLD link record (fields such as "
            f"{', '.join(old) or 'no pakTransportBayLaneMappings'}). The bay-to-lane cloud app is not "
            "deployed here; this skill supports only the 7-field record and writes nothing."
        )
    missing = [k for k in FIELDS if k not in rec]
    extra = [k for k in rec if k not in FIELDS]
    if missing or extra:
        raise ShapeError(f"{where}: unexpected config fields (missing {missing}, extra {extra})")
    maps = rec["pakTransportBayLaneMappings"]
    if not isinstance(maps, list) or not all(
        isinstance(m, dict) and set(m) == {"bayLaneBayId", "bayLaneLaneNumber"} for m in maps
    ):
        raise ShapeError(f"{where}: pakTransportBayLaneMappings is not a list of bay/lane objects")
    return rec


def list_configs(token: str, serials: list[int]) -> list[dict]:
    """The visible configs for these serials (owned ones only; the route filters)."""
    payload = _read(token, LIST, sorted(set(serials)))
    if not isinstance(payload, list):
        raise RouteFailure(f"{LIST}: expected a JSON array")
    return [check_record(rec, LIST) for rec in payload]


# ─────────────────────────────── checks ───────────────────────────────


def _is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def _valid_ipv4(host: str) -> bool:
    parts = host.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p or len(p) > 3 or not all(_is_digit(c) for c in p):
            return False
        if len(p) > 1 and p[0] == "0":
            return False
        if int(p) > 255:
            return False
    return True


def _label_ok(label: str) -> bool:
    return (
        0 < len(label) <= 63
        and all(c.isascii() and (c.isalnum() or c == "-") for c in label)
        and label[0] != "-"
        and label[-1] != "-"
    )


def address_error(host: Any, port: Any) -> str | None:
    """Mirror of the cloud app's lumberjackAddress check; None when valid."""
    if isinstance(port, bool) or not isinstance(port, int) or port < 1 or port > 65535:
        return f"port must be between 1 and 65535, got {port!r}"
    if not isinstance(host, str) or host == "":
        return "host must not be empty"
    if all(_is_digit(c) or c == "." for c in host):
        return None if _valid_ipv4(host) else f"not a valid IPv4 address: {host!r}"
    if len(host) > 253:
        return "host name is longer than 253 characters"
    if not all(_label_ok(lbl) for lbl in host.split(".")):
        return f"invalid host name: {host!r}"
    last = host.rsplit(".", 1)[-1]
    if all(_is_digit(c) for c in last):
        return f"the last part of a host name must not be all digits: {host!r}"
    return None


def bay_ids(rec: dict) -> list[int]:
    return [m["bayLaneBayId"] for m in rec["pakTransportBayLaneMappings"]]


def _word64(v: Any) -> bool:
    """True for a Word64: a non-bool int from 0 to 2^64-1."""
    return not isinstance(v, bool) and isinstance(v, int) and 0 <= v <= WORD64_MAX


def preflight(rec: dict, others: list[dict], ownership: Ownership) -> list[str]:
    """Every reason the save would be refused, mirroring the server.

    `others` are the visible configs with a different id. Configs on LJs the
    caller does not own are not visible, so the cross-config bay check covers
    the caller's own LJs; the cloud app still checks all of them.
    """
    problems: list[str] = []
    serial = rec["pakTransportLumberjackId"]
    if not ownership.owns(serial):
        problems.append(f"you do not own LJ {serial} (OnPing would answer 403)")
    maps = rec["pakTransportBayLaneMappings"]
    if not maps:
        problems.append("pakTransportBayLaneMappings must not be empty (give at least one --map BAY=LANE)")
    for m in maps:
        for key in ("bayLaneBayId", "bayLaneLaneNumber"):
            v = m[key]
            if not _word64(v):
                problems.append(f"{key} {v!r} is not a whole number from 0 to 2^64-1")
    # A --from file can carry any JSON value here (a list is unhashable), so
    # the bay checks below see only the bay ids that are valid numbers.
    ids = [b for b in bay_ids(rec) if _word64(b)]
    dups = sorted({b for b in ids if ids.count(b) > 1})
    if dups:
        problems.append(f"pakTransportBayLaneMappings must not repeat a bay ID: {dups}")
    err = address_error(rec["pakTransportLumberjackUrl"], rec["pakTransportLumberjackPort"])
    if err:
        problems.append(f"invalid lumberjack address: {err}")
    same_lj = [o["pakTransportConfigId"] for o in others if o["pakTransportLumberjackId"] == serial]
    if same_lj:
        problems.append(f"another configuration already exists for this lumberjack: {same_lj[0]}")
    taken = {b: o["pakTransportConfigId"] for o in others for b in bay_ids(o)}
    claimed = sorted({b for b in ids if b in taken})
    if claimed:
        owners = sorted({taken[b] for b in claimed})
        problems.append(f"bay ID(s) already mapped by another configuration: {claimed} ({', '.join(owners)})")
    for key in ("pakTransportFacilityId", "pakTransportFacilityName"):
        if not isinstance(rec[key], str):
            problems.append(f"{key} must be a string")
    return problems


def canonical(rec: dict) -> dict:
    """The record as the cloud stores it: mappings sorted by bay id."""
    out = {k: rec[k] for k in FIELDS}
    out["pakTransportBayLaneMappings"] = sorted(
        ({"bayLaneBayId": m["bayLaneBayId"], "bayLaneLaneNumber": m["bayLaneLaneNumber"]} for m in rec["pakTransportBayLaneMappings"]),
        key=lambda m: m["bayLaneBayId"],
    )
    return out


def diff(before: dict | None, after: dict | None) -> list[tuple[str, Any, Any]]:
    """[(field, old, new)] for fields that differ, comparing canonical forms."""
    b = canonical(before) if before else {}
    a = canonical(after) if after else {}
    return [(k, b.get(k), a.get(k)) for k in FIELDS if b.get(k) != a.get(k)]


def new_config_id() -> str:
    return str(uuidlib.uuid4())


def is_uuid(text: str) -> bool:
    try:
        return str(uuidlib.UUID(text)) == text.lower()
    except (ValueError, AttributeError, TypeError):
        return False
