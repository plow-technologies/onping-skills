"""HTTP layer for the LAS routes, with OnPing's expired-token hardening.

An expired bearer token makes OnPing answer `303 -> /auth/login`, a 200 HTML
login page, or a 401; all three are detected on every call. Every failure
raises `LASError` carrying the HTTP status. The token is never printed.

las-server errors arrive as OnPing's HTTP 500 `{"error": "<shown exception>"}`
whose text holds the inner servant response, escaped several times:

    ... Response {responseStatusCode = Status {statusCode = 404, ...}, ...,
    responseBody = \\"No configs for package P found for serial N\\\\n\\\\nTrace-ID:...\\"}))

`unwrap_500` recovers the inner status, message and trace ID.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, NoReturn

import requests

from . import routes


class LASError(Exception):
    """A failed call: network error, expired token, HTML body, or non-2xx status."""

    def __init__(self, message: str, *, status: int | None = None,
                 inner_status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.inner_status = inner_status
        self.body = body


def die(err: Exception, code: int = 1) -> NoReturn:
    print(str(err), file=sys.stderr)
    sys.exit(code)


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


_INNER_STATUS = re.compile(r"responseStatusCode = Status \{statusCode = (\d+)")
_INNER_BODY = re.compile(r'responseBody = \\*"(.*?)\\*"\}\)', re.S)
_TRACE = re.compile(r"\s*Trace-ID:\s*([0-9A-Za-z-]+)")


def unwrap_500(text: str) -> tuple[int, str, str | None] | None:
    """(inner status, message, trace id) from OnPing's wrapped las-server error, or None."""
    m = _INNER_STATUS.search(text)
    if not m:
        return None
    status = int(m.group(1))
    b = _INNER_BODY.search(text)
    message = ""
    trace = None
    if b:
        raw = b.group(1)
        raw = re.sub(r"\\+n", "\n", raw)
        raw = re.sub(r'\\+"', '"', raw)
        t = _TRACE.search(raw)
        if t:
            trace = t.group(1)
            raw = raw[: t.start()]
        message = raw.strip()
    return status, message, trace


def explain(status: int, text: str, endpoint: str, role: str) -> tuple[str, int | None]:
    """One actionable line for a non-2xx answer, and the inner status for a 500."""
    if status == 401:
        return (f"HTTP 401 from {endpoint}: the access token is missing or expired. "
                "Re-run onping-login."), None
    if status == 403:
        need = ("Owner of the Lumberjack's group" if role == "Owner"
                else "Member or Owner of the Lumberjack's group")
        return f"HTTP 403 from {endpoint}: {text.strip()}. This call needs {need}.", None
    if status == 400:
        return (f"HTTP 400 from {endpoint}: {text.strip()[:300]} "
                "(a missing or malformed serial or query parameter)."), None
    if status == 500:
        inner = unwrap_500(text)
        if inner:
            st, msg, trace = inner
            tail = f" (Trace-ID: {trace})" if trace else ""
            return (f"HTTP 500 from {endpoint}: las-server answered {st}: "
                    f"{msg or '(no message)'}{tail}"), st
    return f"HTTP {status} from {endpoint}: {text[:500]}", None


def _auth_redirected(resp: requests.Response) -> bool:
    return bool(resp.history) and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    )


def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:5].lower() in ("<!doc", "<html")


def _send(token: str, route: str, *, params: dict | None = None, body: Any = None,
          want: str = "json") -> Any:
    spec = routes.ROUTES[route]
    endpoint = spec["endpoint"]
    method, path = endpoint.split(" ", 1)
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/json" if want == "json" else "text/plain, */*"}
    kwargs: dict[str, Any] = {}
    if method == "POST":
        headers["Content-Type"] = "application/json"
        kwargs["data"] = json.dumps(body, separators=(",", ":"))
    try:
        resp = requests.request(
            method, routes.BASE_URL + path, params=params or {}, headers=headers,
            allow_redirects=True, timeout=spec.get("timeout", routes.TIMEOUT_SECONDS),
            **kwargs,
        )
    except requests.RequestException as e:
        raise LASError(f"Request error ({endpoint}): {type(e).__name__}") from e
    if _auth_redirected(resp):
        raise LASError(
            f"{endpoint} redirected to the login page: the access token is likely "
            "expired. Re-run onping-login.", status=resp.status_code)
    if _looks_like_html(resp.text):
        raise LASError(
            f"Expected {want} from {endpoint} but received HTML: the access token is "
            "likely expired. Re-run onping-login.", status=resp.status_code)
    if not (200 <= resp.status_code < 300):
        msg, inner = explain(resp.status_code, error_text(resp.text), endpoint,
                             spec.get("role", "Member"))
        raise LASError(msg, status=resp.status_code, inner_status=inner, body=resp.text)
    if want == "text":
        return resp.text
    if not resp.text.strip():
        return None
    try:
        return resp.json()
    except ValueError as e:
        raise LASError(
            f"Expected JSON from {endpoint} but could not parse: {resp.text[:300]}",
            status=resp.status_code) from e


def get_json(token: str, route: str, **params: Any) -> Any:
    return _send(token, route, params=params)


def get_text(token: str, route: str, **params: Any) -> str:
    return _send(token, route, params=params, want="text")


def post_json(token: str, route: str, body: Any, **params: Any) -> Any:
    return _send(token, route, params=params, body=body)
