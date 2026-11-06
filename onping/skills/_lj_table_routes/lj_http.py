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
import re
import sys
import urllib.parse
from typing import Any, NoReturn

import requests

from . import pace
from .routes import BASE_URL, ROUTES, TIMEOUT_SECONDS

RATE_LIMITED_EXIT = 6
BAD_INPUT_EXIT = 2


class LJTableError(Exception):
    """A failed call: network error, expired token, HTML body, or non-2xx status."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class RateLimited(LJTableError):
    """The server answered HTTP 429. The call is not resent; the caller stops (exit 6)."""

    def __init__(self, endpoint: str):
        super().__init__(f"HTTP 429 (rate-limited) from {endpoint}", status=429)
        self.endpoint = endpoint


class ForbiddenRoute(LJTableError):
    """A route marked `forbidden` in ROUTES was asked for. Nothing is sent."""


def exit_code(err: Exception) -> int:
    if isinstance(err, RateLimited):
        return RATE_LIMITED_EXIT
    return BAD_INPUT_EXIT if isinstance(err, PathParamError) else 1


def stop_message(err: RateLimited, state: str) -> str:
    """The exit-6 message: what was done so far, the run's write count, and that nothing is resent."""
    return (f"STOP rate-limited: {err}. {state} This run sent {pace.sent()} write POST(s). Nothing is "
            "resent; this goes back to the user, with no rerun until the user has ruled on the 429")


def die(err: Exception) -> NoReturn:
    print(str(err), file=sys.stderr)
    sys.exit(exit_code(err))


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


_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ID_RE = re.compile(r"[A-Za-z0-9]+")
_NAME_BAD = re.compile(r"[/?#%\\\x00-\x1f\x7f]")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]+)\}")


class PathParamError(ValueError):
    """A path parameter is unsafe or the wrong shape. Nothing was sent; skills map this to exit 2."""


def check_uuid(value: Any, what: str = "id") -> str:
    """Return `value` if it is a canonical uuid string, else raise PathParamError."""
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise PathParamError(f"{what} {str(value)[:80]!r} is not a uuid")
    return value


def _check_param(name: str, value: Any) -> str:
    if isinstance(value, bool):
        raise PathParamError(f"path parameter {name!r} must not be a boolean")
    if name == "lj":
        text = str(value)
        if isinstance(value, (int, str)) and text.isascii() and text.isdigit():
            return text
        raise PathParamError(f"Lumberjack serial {text[:40]!r} must be digits only")
    if name == "widget":
        if isinstance(value, str) and _ID_RE.fullmatch(value) and value.isascii():
            return value
        raise PathParamError(f"widget id {str(value)[:80]!r} must be letters and digits only")
    if name == "name":
        if (isinstance(value, str) and value and not value.isspace() and value not in (".", "..")
                and ".." not in value and not _NAME_BAD.search(value)):
            return urllib.parse.quote(value, safe="")
        raise PathParamError(
            f"name {str(value)[:80]!r} must be non-empty and contain none of / ? # % \\ .. or control characters")
    raise PathParamError(f"unknown path parameter {name!r}")


def _url(endpoint: str, **path_params: Any) -> str:
    template = endpoint.split(" ", 1)[1]
    wanted = _PLACEHOLDER_RE.findall(template)
    extra = sorted(set(path_params) - set(wanted))
    if extra:
        raise PathParamError(f"unexpected path parameter(s) {extra} for {template}")
    path = template
    for name in wanted:
        if name not in path_params:
            raise PathParamError(f"missing path parameter {name!r} for {template}")
        path = path.replace("{" + name + "}", _check_param(name, path_params[name]))
    if "{" in path or "}" in path:
        raise PathParamError(f"unresolved path placeholder in {path!r}")
    if not _same_shape(template, path) or any(c in path for c in "?#\\"):
        raise PathParamError(f"resolved path {path!r} does not match the route shape {template!r}")
    return BASE_URL + path


def _same_shape(template: str, path: str) -> bool:
    """True when `path` has the same segments as `template`, a placeholder matching one non-empty segment."""
    t_parts, p_parts = template.split("/"), path.split("/")
    if len(t_parts) != len(p_parts):
        return False
    return all((t.startswith("{") and t.endswith("}") and p != "") or t == p for t, p in zip(t_parts, p_parts))


def _hits_forbidden(path: str) -> str | None:
    """The endpoint of a forbidden route whose shape `path` has, else None."""
    for spec in ROUTES.values():
        if spec.get("forbidden"):
            template = spec["endpoint"].split(" ", 1)[1]
            if _same_shape(template, path.rstrip("/")):
                return spec["endpoint"]
    return None


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


def _request(token: str, route: str, *, body: Any = None, fields: dict[str, str] | None = None,
             file: tuple[str, str, bytes] | None = None, want_bytes: bool = False,
             **path_params: Any) -> Any:
    spec = ROUTES[route]
    endpoint = spec["endpoint"]
    if spec.get("forbidden"):
        raise ForbiddenRoute(
            f"{endpoint} is forbidden: no skill may call it (it can delete every row). Nothing was sent.")
    method = endpoint.split(" ", 1)[0]
    url = _url(endpoint, **path_params)
    hit = _hits_forbidden(url[len(BASE_URL):])
    if hit:
        raise ForbiddenRoute(f"{hit} is forbidden: the resolved path for {route} matches it. Nothing was sent.")
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "*/*" if want_bytes else "application/json"}
    kwargs: dict[str, Any] = {}
    if spec.get("multipart"):
        if file is None:
            raise ValueError(f"{route} needs a file")
        field, filename, content = file
        kwargs["files"] = {field: (filename, content, "application/octet-stream")}
        kwargs["data"] = dict(fields or {})
    elif method == "POST":
        headers["Content-Type"] = "application/json"
        kwargs["data"] = json.dumps(body, separators=(",", ":"))
    paced = bool(spec.get("writes"))
    try:
        if paced:
            with pace.post():
                resp = requests.request(method, url, headers=headers, allow_redirects=True,
                                        timeout=spec.get("timeout", TIMEOUT_SECONDS), **kwargs)
        else:
            resp = requests.request(method, url, headers=headers, allow_redirects=True,
                                    timeout=spec.get("timeout", TIMEOUT_SECONDS), **kwargs)
    except requests.RequestException as e:
        raise LJTableError(f"Request error ({endpoint}): {e}") from e
    if resp.status_code == 429:
        raise RateLimited(endpoint)
    if _auth_redirected(resp):
        raise LJTableError(
            f"Access token redirected to auth — the token is likely expired "
            f"(final URL: {resp.url}). Re-run onping-login."
        )
    ok = 200 <= resp.status_code < 300
    if want_bytes and ok:
        content = resp.content
        if _looks_like_html(content[:64].decode("utf-8", "ignore")):
            raise LJTableError(
                f"Expected a file from {endpoint} but received HTML — the access token is "
                "likely expired. Re-run onping-login."
            )
        return content
    if _looks_like_html(resp.text):
        raise LJTableError(
            f"Expected JSON from {endpoint} but received HTML — the access token is "
            "likely expired. Re-run onping-login."
        )
    if not ok:
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
    return _request(token, route, **path_params)


def post_json(token: str, route: str, body: Any, **path_params: Any) -> Any:
    """POST a JSON body to a `ROUTES` key and return the parsed body (None if empty)."""
    return _request(token, route, body=body, **path_params)


def post_bytes(token: str, route: str, body: Any, **path_params: Any) -> bytes:
    """POST a JSON body to a route that answers a file (export dump, template); returns the bytes."""
    return _request(token, route, body=body, want_bytes=True, **path_params)


def post_multipart(token: str, route: str, fields: dict[str, str], file: tuple[str, str, bytes],
                   **path_params: Any) -> Any:
    """POST a multipart form: `fields` as text parts and `file` = (field name, file name, bytes)."""
    return _request(token, route, fields=fields, file=file, **path_params)
