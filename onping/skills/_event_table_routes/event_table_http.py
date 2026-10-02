"""Shared HTTP helpers for the OnPing event-table skills.

Every `onping-event-table-*` skill goes through these functions, so the base URL,
bearer-token auth, and the auth-redirect / HTML-fallthrough hardening live in
one place. The hardening matches `_line_graph_routes/line_graph_http.py`: an
expired bearer token makes OnPing answer `303 -> /auth/login` and a 200 HTML
login page, so both are detected on every call and treated as failures.

Unlike the line-graph helper, failures RAISE `EventTableError` instead of
exiting. `onping-event-table-list --references-pid` reads many tables and must
report one failed read as UNCHECKED without stopping. A single-call script uses
`die(err)` to print the error and exit 1.

Endpoints are routes-table strings of the form "METHOD /path" (see `routes.py`).
"""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

import requests

from .routes import BASE_URL, TIMEOUT_SECONDS


class EventTableError(Exception):
    """A failed call: network error, expired token, HTML body, or non-2xx status."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def die(err: EventTableError) -> NoReturn:
    print(str(err), file=sys.stderr)
    sys.exit(1)


def error_text(body: str) -> str:
    """Unwrap an OnPing error body.

    The event-table routes answer either `{"error": "<msg>"}` or a bare JSON
    string, depending on the route. Anything else comes back unchanged.
    """
    try:
        parsed = json.loads(body)
    except ValueError:
        return body
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
        return parsed["error"]
    if isinstance(parsed, str):
        return parsed
    return body


def _url(endpoint: str, **path_params: str) -> str:
    path = endpoint.split(" ", 1)[1] if " " in endpoint else endpoint
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


def _send(
    token: str,
    endpoint: str,
    *,
    accept: str,
    json_body: Any = None,
    params: dict[str, str] | None = None,
    path_params: dict[str, str] | None = None,
) -> requests.Response:
    method = endpoint.split(" ", 1)[0]
    url = _url(endpoint, **(path_params or {}))
    headers = {"Authorization": f"Bearer {token}", "Accept": accept}
    try:
        resp = requests.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise EventTableError(f"Request error ({endpoint}): {e}") from e
    if _auth_redirected(resp):
        raise EventTableError(
            f"Access token redirected to auth — the token is likely expired "
            f"(final URL: {resp.url}). Get a new one with onping-login."
        )
    if _looks_like_html(resp.text):
        raise EventTableError(
            f"Expected {accept} from {endpoint} but received HTML — the access token "
            f"is likely expired, or the route returned an error page."
        )
    if not (200 <= resp.status_code < 300):
        raise EventTableError(
            f"HTTP {resp.status_code} from {endpoint}: {error_text(resp.text)[:500]}",
            status=resp.status_code,
            body=resp.text,
        )
    return resp


def post_json(token: str, endpoint: str, body: Any) -> Any:
    """POST a JSON body and return the parsed JSON response."""
    resp = _send(token, endpoint, accept="application/json", json_body=body)
    try:
        return resp.json()
    except ValueError as e:
        raise EventTableError(
            f"Expected JSON from {endpoint} but could not parse:\n{resp.text[:500]}"
        ) from e


def get_json(token: str, endpoint: str, *, params: dict[str, str] | None = None) -> Any:
    """GET a JSON route and return the parsed body."""
    resp = _send(token, endpoint, accept="application/json", params=params)
    try:
        return resp.json()
    except ValueError as e:
        raise EventTableError(
            f"Expected JSON from {endpoint} but could not parse:\n{resp.text[:500]}"
        ) from e


def get_text(
    token: str,
    endpoint: str,
    *,
    params: dict[str, str] | None = None,
    path_params: dict[str, str] | None = None,
) -> str:
    """GET a text route (the Dhall export) and return the body verbatim."""
    resp = _send(
        token,
        endpoint,
        accept="application/vnd.plow.event-table+dhall, text/plain",
        params=params,
        path_params=path_params,
    )
    return resp.text
