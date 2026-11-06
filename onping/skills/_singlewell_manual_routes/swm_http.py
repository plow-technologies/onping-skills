"""Transport and reads shared by onping-create-singlewell-manual and
onping-delete-singlewell-manual.

Every read raises RouteFailure on any failure (HTTP, transport, auth redirect,
HTML login page, bad shape), so a caller can never mistake a failed read for an
empty answer. The two write calls (`post_once`) return a WriteResult instead of
raising, because a write whose response was lost has an unknown outcome, which
is not the same as a failure.

`read_location` is the one place that classifies a get/loc answer. Both skills
use it, so create's "present" and delete's "gone" cannot drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import requests

from . import routes as R


class RouteFailure(Exception):
    """A read failed. Nothing was written by this call."""


class AuthFailure(RouteFailure):
    """The token was refused (redirect to login or an HTML page)."""


# ─────────────────────────────── transport ───────────────────────────────


def _auth_redirected(resp: requests.Response) -> bool:
    return bool(resp.history) and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    )


def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:5].lower() in ("<!doc", "<html")


def _split(endpoint: str) -> tuple[str, str]:
    method, path = endpoint.split(" ", 1)
    return method, R.BASE_URL + path


def _send(token: str, endpoint: str, body: Any = None, params: dict | None = None) -> requests.Response:
    """Send one request. Raises requests.RequestException or AuthFailure."""
    method, url = _split(endpoint)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    kwargs: dict[str, Any] = {
        "headers": headers,
        "allow_redirects": True,
        "timeout": R.TIMEOUT_SECONDS,
    }
    if params:
        kwargs["params"] = params
    if method == "POST":
        headers["Content-Type"] = "application/json"
        resp = requests.post(url, json=body, **kwargs)
    else:
        resp = requests.get(url, **kwargs)
    if _auth_redirected(resp):
        raise AuthFailure(
            f"{endpoint}: the token was redirected to the login page; it may be expired. "
            "Get a new one with onping-login."
        )
    if _looks_like_html(resp.text):
        raise AuthFailure(
            f"{endpoint}: expected JSON but received HTML; the token may be expired."
        )
    return resp


def _json(resp: requests.Response, endpoint: str) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        raise RouteFailure(f"{endpoint}: HTTP {resp.status_code}, body is not JSON: {resp.text[:300]}") from exc


def read(token: str, endpoint: str, body: Any = None, params: dict | None = None) -> Any:
    """A read that must answer 2xx JSON."""
    try:
        resp = _send(token, endpoint, body, params)
    except requests.RequestException as exc:
        raise RouteFailure(f"{endpoint}: request error: {exc}") from exc
    if not 200 <= resp.status_code < 300:
        raise RouteFailure(f"{endpoint}: HTTP {resp.status_code}: {resp.text[:300]}")
    return _json(resp, endpoint)


@dataclass
class WriteResult:
    sent: bool  # False only when the request provably did not reach the handler
    status: int | None = None
    body: Any = None
    text: str = ""
    error: str | None = None


def post_once(token: str, endpoint: str, body: Any) -> WriteResult:
    """POST a write exactly once. Never retried.

    A transport error after the call starts is treated as sent (the server may
    have acted). An auth redirect is treated as not sent: the login check runs
    before the handler.
    """
    try:
        resp = _send(token, endpoint, body)
    except AuthFailure as exc:
        return WriteResult(sent=False, error=str(exc))
    except requests.ConnectTimeout as exc:
        return WriteResult(sent=False, error=f"connect timeout: {exc}")
    except requests.RequestException as exc:
        return WriteResult(sent=True, error=f"request error: {exc}")
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None
    return WriteResult(sent=True, status=resp.status_code, body=parsed, text=resp.text[:1000])


# ───────────────────────────────── reads ─────────────────────────────────


def owned_groups(token: str) -> dict[str, str | None]:
    """{group id: name} for the caller's owned groups."""
    payload = read(token, R.OWNERSHIP)
    if not isinstance(payload, list):
        raise RouteFailure(f"{R.OWNERSHIP} did not return a list")
    out: dict[str, str | None] = {}
    for item in payload:
        gid = item.get("key") if isinstance(item, dict) else None
        value = item.get("value") if isinstance(item, dict) else None
        if not isinstance(gid, str) or not gid or not isinstance(value, dict):
            raise RouteFailure(f"{R.OWNERSHIP} returned an entry without a group id")
        name = value.get("name")
        out[gid] = name if isinstance(name, str) else None
    return out


def lumberjack_url(token: str, serial: int) -> str | None:
    """The Lumberjack's lumberjackUrl from its LAS profile, or None.

    The profile carries the Lumberjack's password, so nothing but the URL is
    returned or printed.
    """
    payload = read(token, R.PROFILES)
    if not isinstance(payload, list):
        raise RouteFailure(f"{R.PROFILES} did not return a list")
    for item in payload:
        if isinstance(item, list) and len(item) == 2 and item[0] == serial:
            prof = item[1] if isinstance(item[1], dict) else {}
            url = prof.get("lumberjackUrl")
            return url if isinstance(url, str) and url.strip() else None
    return None


def company_sites(token: str, company: int) -> dict[int, str | None]:
    """{site id: name} for the company's live (not deleted) sites."""
    payload = read(token, R.SITES, params={"getCompanyLookupList": str(company)})
    if not isinstance(payload, list):
        raise RouteFailure(f"{R.SITES} did not return a list")
    out: dict[int, str | None] = {}
    for item in payload:
        value = item.get("value") if isinstance(item, dict) else None
        if not isinstance(value, dict):
            raise RouteFailure(f"{R.SITES} returned an entry without a value")
        if value.get("cid") != company or value.get("delete") not in (0, False, None):
            continue
        ref = value.get("refId")
        if isinstance(ref, int):
            out[ref] = value.get("name")
    return out


def manual_at_site(token: str, site: int) -> dict[int, str | None]:
    """{refId: name} for the manual locations the server lists at a site."""
    payload = read(token, R.LIST_AT_SITES, [site])
    if not isinstance(payload, list):
        raise RouteFailure(f"{R.LIST_AT_SITES} did not return a list")
    out: dict[int, str | None] = {}
    for loc in payload:
        if not isinstance(loc, dict) or not isinstance(loc.get("refId"), int):
            raise RouteFailure(f"{R.LIST_AT_SITES} returned an entry without a refId")
        out[loc["refId"]] = loc.get("name")
    return out


@dataclass
class LocState:
    """One get/loc answer, classified.

    kind:
      present  200 with a config whose manualLocationRefId is the id asked for
      missing  400 "failed to find single well manual location by id"
      partial  400 naming a missing extras record or group join (the manual
               record exists)
      unknown  anything else (the id may or may not exist)
    """

    kind: str
    config: dict | None = None
    detail: str = ""
    extra: dict = field(default_factory=dict)


def read_location(token: str, ref: int) -> LocState:
    try:
        resp = _send(token, R.GET_LOC, ref)
    except AuthFailure as exc:
        return LocState("unknown", detail=str(exc))
    except requests.RequestException as exc:
        return LocState("unknown", detail=f"request error: {exc}")
    try:
        body = resp.json()
    except ValueError:
        return LocState("unknown", detail=f"HTTP {resp.status_code}, not JSON: {resp.text[:200]}")
    if resp.status_code == 200:
        if isinstance(body, dict) and body.get("manualLocationRefId") == ref:
            return LocState("present", config=body)
        return LocState("unknown", detail=f"HTTP 200 but the body is not location {ref}")
    if resp.status_code == 400 and isinstance(body, dict):
        msg = body.get("error")
        if msg == R.MSG_NO_MANUAL:
            return LocState("missing", detail=msg)
        if msg in (R.MSG_NO_EXTRAS, R.MSG_NO_GROUP):
            return LocState("partial", detail=msg)
        return LocState("unknown", detail=f"HTTP 400: {msg!r}")
    return LocState("unknown", detail=f"HTTP {resp.status_code}: {resp.text[:200]}")


# ──────────────────────────── add classification ────────────────────────────

_REF_RE = re.compile(r"LocationIdRef\s*\{?\s*(?:unLocationIdRef\s*=\s*)?(\d+)")


def classify_add_failure(text: str) -> tuple[str | None, int | None, tuple[str, ...]]:
    """(failed stage, LocationIdRef, records that exist) from a 500 error text.

    Returns (None, None, ()) when the text names no known stage.
    """
    ref_match = _REF_RE.search(text)
    ref = int(ref_match.group(1)) if ref_match else None
    for marker, stage, exist in R.ADD_FAILURES:
        if marker in text:
            return stage, ref, exist
    return None, ref, ()
