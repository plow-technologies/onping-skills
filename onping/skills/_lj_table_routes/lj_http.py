"""Shared HTTP helpers for the OnPing data-table and log-table skills.

Every `onping-datatable-*` and `onping-logtable-*` primitive goes through these
functions, so the base URL, bearer-token auth, and the expired-token hardening
live in one place. The hardening matches `_ctable_routes/ctable_http.py`: an
expired bearer token makes OnPing answer `303 -> /auth/login`, a 200 HTML login
page, or a 401, so all three are detected on every call.

Failures RAISE `LJTableError` instead of exiting, so `--references-pid` scans
can report one failed table and carry on. A single-call script uses `die(err)`.

OnPing wraps every app error as `{"error": "<text>"}` with the app's status.
Three statuses get a clearer message:
  - 500 "Permission Denied" — the source's group is not one you own (writes)
    or own-or-belong-to (reads);
  - 503 — a data-table regeneration holds the write lock; retry shortly;
  - 404 "Routing index could not be found" — the Lumberjack has no routing for
    this table kind.

Endpoints are `ROUTES` keys (see `routes.py`); `{lj}` is a path parameter.
"""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

import requests

from .routes import BASE_URL, ROUTES, TIMEOUT_SECONDS


class LJTableError(Exception):
    """A failed call: network error, expired token, HTML body, or non-2xx status."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def die(err: Exception) -> NoReturn:
    print(str(err), file=sys.stderr)
    sys.exit(1)


def error_text(body: str) -> str:
    """Unwrap `{"error": "<msg>"}` or a bare JSON string; anything else unchanged."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return body
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
        return parsed["error"]
    if isinstance(parsed, str):
        return parsed
    return body


def endpoint_of(route: str) -> str:
    return ROUTES[route]["endpoint"]


def _url(endpoint: str, **path_params: Any) -> str:
    path = endpoint.split(" ", 1)[1]
    for name, value in path_params.items():
        path = path.replace("{" + name + "}", str(value))
    if "{" in path:
        raise ValueError(f"unresolved path placeholder in {path!r}")
    return BASE_URL + path


def _auth_redirected(resp: requests.Response) -> bool:
    return bool(resp.history) and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    )


def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:5].lower() in ("<!doc", "<html")


def explain(status: int, text: str, endpoint: str) -> str:
    """Turn a non-2xx OnPing answer into one actionable line."""
    if status == 500 and "Permission Denied" in text:
        return (
            f"HTTP 500 Permission Denied from {endpoint}. Writes need the source's group "
            "in your OWNED groups; reads need it in your owned-or-member groups."
        )
    if status == 503:
        return (
            f"HTTP 503 from {endpoint}: a data-table regeneration is in progress and holds "
            f"the write lock. Nothing was changed; retry in a minute. ({text[:200]})"
        )
    if status == 404 and "Routing index" in text:
        return (
            f"HTTP 404 from {endpoint}: this Lumberjack has no routing for this table kind "
            "(no tables of this kind live there). Use --all to see which LJs have tables."
        )
    if status == 401:
        return (
            f"HTTP 401 from {endpoint}: the access token is missing or expired. "
            "Re-run onping-login."
        )
    return f"HTTP {status} from {endpoint}: {text[:500]}"


def _send(token: str, route: str, *, body: Any = None, **path_params: Any) -> Any:
    endpoint = endpoint_of(route)
    method = endpoint.split(" ", 1)[0]
    url = _url(endpoint, **path_params)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    kwargs: dict[str, Any] = {}
    if method == "POST":
        headers["Content-Type"] = "application/json"
        kwargs["data"] = json.dumps(body, separators=(",", ":"))
    try:
        resp = requests.request(
            method, url, headers=headers, allow_redirects=True,
            timeout=ROUTES[route].get("timeout", TIMEOUT_SECONDS), **kwargs,
        )
    except requests.RequestException as e:
        raise LJTableError(f"Request error ({endpoint}): {e}") from e
    if _auth_redirected(resp):
        raise LJTableError(
            f"Access token redirected to auth — the token is likely expired "
            f"(final URL: {resp.url}). Re-run onping-login."
        )
    if _looks_like_html(resp.text):
        raise LJTableError(
            f"Expected JSON from {endpoint} but received HTML — the access token is "
            "likely expired. Re-run onping-login."
        )
    if not (200 <= resp.status_code < 300):
        text = error_text(resp.text)
        raise LJTableError(
            explain(resp.status_code, text, endpoint), status=resp.status_code, body=resp.text
        )
    if not resp.text.strip():
        return None
    try:
        payload = resp.json()
    except ValueError as e:
        raise LJTableError(
            f"Expected JSON from {endpoint} but could not parse:\n{resp.text[:500]}"
        ) from e
    if isinstance(payload, dict) and set(payload) == {"error"}:
        raise LJTableError(f"{endpoint} answered an error: {payload['error']}")
    return payload


def get_json(token: str, route: str, **path_params: Any) -> Any:
    """GET a JSON route by `ROUTES` key and return the parsed body."""
    return _send(token, route, **path_params)


def post_json(token: str, route: str, body: Any, **path_params: Any) -> Any:
    """POST a JSON body to a `ROUTES` key and return the parsed body (None if empty)."""
    return _send(token, route, body=body, **path_params)
