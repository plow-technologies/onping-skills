"""Shared HTTP helpers for the OnPing line-graph widget skills.

Every `onping-line-graph-*` skill goes through these functions so the base URL,
bearer-token auth, and the auth-redirect / HTML-fallthrough hardening live in
one place. The hardening is carried over verbatim from `_hmi_routes/hmi_http.py`:
an expired bearer token makes OnPing answer `303 -> /auth/login` and a 200 HTML
login page. We detect both the auth-redirect and an HTML body on every call and
fail fast, so a login page is never mistaken for a Dhall export, a JSON widget,
or a successful write.

Endpoints are passed as routes-table strings of the form "METHOD /path" (see
`routes.py`); the leading method is stripped and `{widget_id}` is substituted
before the request. Response verbs:

  - get_dhall     — GET returning Dhall text (export, export-data)
  - get_json      — GET returning parsed JSON (widget, permission)
  - post_dhall    — POST a Dhall body, returns the raw Response (import, import-data)
  - post_empty    — POST an empty body, returns the raw Response (config → mint)

`_fail(msg)` prints to stderr and exits non-zero. Read verbs fail-fast through
it directly; write verbs return the raw Response so the caller can gate on
status and surface `{"error": ...}` envelopes, but still fail-fast on the
auth-redirect / HTML fallthrough (which can never be a legitimate write result).

Response envelope on POST /import and /import-data (verified live 2026-07-13):
the success body is a RAW JSON LineGraphWidget (no wrapping envelope). The
error path is HTTP 400 with a JSON body `{"error": "<message>"}`. Callers use
`extract_error(resp)` to surface the error string when a non-2xx status arrives.
"""

from __future__ import annotations

import sys

import requests

from .routes import BASE_URL, TIMEOUT_SECONDS


# ─────────────────────────────── auth checks ───────────────────────────────


def _auth_redirected(resp: requests.Response) -> bool:
    return bool(resp.history) and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    )


def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:5].lower() in ("<!doc", "<html")


def _fail(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(1)


# ─────────────────────────────── url building ──────────────────────────────


def _url(endpoint: str, **path_params: str) -> str:
    """Turn a routes-table "METHOD /path/{widget_id}" into an absolute URL.

    The HTTP method prefix is stripped; each `{name}` placeholder is replaced by
    the matching keyword argument. Any leftover unresolved placeholder is a
    programming error and raises.
    """
    path = endpoint.split(" ", 1)[1] if " " in endpoint else endpoint
    for name, value in path_params.items():
        path = path.replace("{" + name + "}", str(value))
    if "{" in path:
        raise ValueError(f"unresolved path placeholder in {path!r}")
    return path if path.startswith("http") else BASE_URL + path


def _guard(resp: requests.Response, expected: str) -> None:
    """Fail fast on the auth-redirect / HTML-login fallthrough."""
    if _auth_redirected(resp):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url})."
        )
    if _looks_like_html(resp.text):
        _fail(
            f"Expected {expected} but received HTML — access token may be "
            f"expired or the route returned an error page."
        )


# ─────────────────────────────── read verbs ────────────────────────────────


def get_dhall(token: str, endpoint: str, *, widget_id: str) -> str:
    """GET a Dhall route (export / export-data); return the Dhall text verbatim.

    Fails fast on request error, auth-redirect, HTML body, or a non-2xx status.
    """
    url = _url(endpoint, widget_id=widget_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.plow.haskell-type+dhall, text/x-dhall, text/plain",
    }
    try:
        resp = requests.get(
            url, headers=headers, allow_redirects=True, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "Dhall")
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} from {url}\n{resp.text[:500]}")
    return resp.text


def get_json(token: str, endpoint: str, *, widget_id: str | None = None):
    """GET a JSON route (widget / permission); return the parsed body."""
    url = (
        _url(endpoint, widget_id=widget_id) if widget_id is not None else _url(endpoint)
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(
            url, headers=headers, allow_redirects=True, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} from {url}\n{resp.text[:500]}")
    try:
        return resp.json()
    except ValueError:
        _fail(f"Expected JSON but could not parse response from {url}:\n{resp.text[:500]}")


# ─────────────────────────────── write verbs ───────────────────────────────


def post_dhall(
    token: str, endpoint: str, dhall: str, *, widget_id: str
) -> requests.Response:
    """POST a Dhall body (import / import-data). Returns the raw Response.

    Fails fast on auth-redirect / HTML fallthrough; the caller inspects status
    and JSON. Content-Type is text/plain;charset=UTF-8 to match the OnPing
    convention for Dhall bodies.
    """
    url = _url(endpoint, widget_id=widget_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=dhall.encode("utf-8"),
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    return resp


def post_empty(token: str, endpoint: str) -> requests.Response:
    """POST an empty body (config → mint). Returns the raw Response.

    Fails fast on auth-redirect / HTML fallthrough; the caller inspects status
    and JSON. Body is empty; server ignores Content-Type on this route.
    """
    url = _url(endpoint)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=b"",
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    return resp


# ─────────────────────────────── envelope helpers ──────────────────────────


def extract_error(resp: requests.Response) -> str:
    """Pull the error string from a non-2xx line-graph response.

    OnPing's line-graph error envelope is `{"error": "<message>"}` on HTTP 400
    (verified live 2026-07-13). Falls back to the raw body when parsing fails.
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"]
    return str(body)
