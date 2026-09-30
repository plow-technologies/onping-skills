"""Shared HTTP helpers for the OnPing custom-table skills.

Every `onping-ctable-*` skill goes through these functions so the base URL,
bearer-token auth, and the auth-redirect / HTML-fallthrough hardening live in one
place. The hardening is carried over from `_hmi_routes/hmi_http.py`: an expired
bearer token makes OnPing answer `303 -> /auth/login` and a 200 HTML login page.
Observed live on 2026-08-26 — the expiry presented as a `303`, never a `401`, so
status-code checks alone do not catch it.

Two response verbs, because the custom-table routes need exactly two:

  - get_json   — GET returning parsed JSON (get_json, exists, table_data)
  - post_json  — POST a JSON body, returns the raw Response so the caller can
                 inspect the body for the 200-with-refusal-string case

`_fail(msg)` prints to stderr and exits non-zero.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import requests

from .routes import BASE_URL, TIMEOUT_SECONDS


def _auth_redirected(resp: requests.Response) -> bool:
    return bool(resp.history) and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    )


def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:5].lower() in ("<!doc", "<html")


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _url(endpoint: str, **path_params: str) -> str:
    """Turn a routes-table "METHOD /path/{name}" into an absolute URL."""
    path = endpoint.split(" ", 1)[1] if " " in endpoint else endpoint
    for name, value in path_params.items():
        path = path.replace("{" + name + "}", str(value))
    if "{" in path:
        raise ValueError(f"unresolved path placeholder in {path!r}")
    return path if path.startswith("http") else BASE_URL + path


def _guard(resp: requests.Response) -> None:
    """Fail fast on every shape an expired token takes.

    A login page can never be a legitimate result for any of these routes, so both
    read and write verbs go through this before anything else.

    An expired token has been observed presenting three different ways against
    these routes, which is why all three are checked rather than just the redirect:

      - `303 -> /auth/login` (a redirect the session follows)
      - `200` carrying an HTML login page
      - `401 {"error":"NotAuthenticated"}`

    The 401 was found while testing this skill. Reporting it as a generic HTTP
    failure sent the reader looking at the id and the route instead of at the
    token, so it is named explicitly.
    """
    if _auth_redirected(resp):
        _fail(
            "Access token redirected to auth — the token is most likely expired "
            f"(final URL: {resp.url}). Re-run onping-login."
        )
    if _looks_like_html(resp.text):
        _fail(
            "Response body is an HTML page, not JSON — the token is most likely "
            f"expired (HTTP {resp.status_code}). Re-run onping-login."
        )
    if resp.status_code == 401 or "NotAuthenticated" in resp.text[:200]:
        _fail(
            f"Not authenticated (HTTP {resp.status_code}): {resp.text[:200]}\n"
            "  The access token is expired or invalid. Re-run onping-login."
        )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def get_json(token: str, endpoint: str, *, params: dict | None = None, **path_params) -> Any:
    """GET a route and return parsed JSON. Fails fast on any non-200."""
    url = _url(endpoint, **path_params)
    try:
        resp = requests.get(
            url, headers=_headers(token), params=params or {}, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        _fail(f"GET {url} failed: {exc}")
    _guard(resp)
    if resp.status_code != 200:
        _fail(f"GET {url} returned HTTP {resp.status_code}: {resp.text[:400]}")
    try:
        return resp.json()
    except json.JSONDecodeError:
        _fail(f"GET {url} returned a non-JSON body: {resp.text[:400]}")


def get_bytes(token: str, endpoint: str, *, params: dict | None = None, **path_params) -> bytes:
    """GET a route and return the raw body (the XLSX export)."""
    url = _url(endpoint, **path_params)
    try:
        resp = requests.get(
            url, headers={"Authorization": f"Bearer {token}"},
            params=params or {}, timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        _fail(f"GET {url} failed: {exc}")
    _guard(resp)
    if resp.status_code != 200:
        _fail(f"GET {url} returned HTTP {resp.status_code}: {resp.text[:400]}")
    return resp.content


def post_json(token: str, endpoint: str, body: Any, **path_params) -> requests.Response:
    """POST a JSON body and return the raw Response.

    Deliberately does NOT interpret the result. `postCustomTableJsonR` answers a
    permission refusal with the bare JSON string `"insufficient permissions"` at
    HTTP 200, so the caller must inspect the body itself. See
    `check_write_response`.
    """
    url = _url(endpoint, **path_params)
    payload = json.dumps(body, separators=(",", ":")).encode()
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            data=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        _fail(f"POST {url} failed: {exc}")
    _guard(resp)
    return resp


def check_write_response(resp: requests.Response) -> dict:
    """Validate a `POST /content/ctable/json` response, or exit non-zero.

    THE 200-IS-NOT-SUCCESS GUARD. The handler returns the bare JSON string
    `"insufficient permissions"` with a 200 status (`Table.hs`), so a client
    that trusts the status code reports a restore that never happened. Only an
    echoed object carrying both `ctable` and `cid` counts as success.
    """
    if resp.status_code != 200:
        _fail(f"write returned HTTP {resp.status_code}: {resp.text[:400]}")
    try:
        body = resp.json()
    except json.JSONDecodeError:
        _fail(f"write returned a non-JSON body: {resp.text[:400]}")
    if isinstance(body, str):
        _fail(
            f"write REFUSED by the server: {body!r} (HTTP 200 — the handler "
            "reports refusals with a success status). No write occurred."
        )
    if not isinstance(body, dict) or "ctable" not in body or "cid" not in body:
        _fail(
            "write returned an unrecognized body; expected the echoed "
            f"{{ctable, cid}} envelope, got: {str(body)[:400]}"
        )
    return body
