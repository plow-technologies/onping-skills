"""Shared HTTP helpers for the OnPing mqtt-json-integrator skills.

Every `onping-mqtt-integrator-*` skill goes through these functions so the base
URL, bearer-token auth, and the auth-redirect / HTML-fallthrough hardening live
in one place. The hardening is carried over from `_hmi_routes/hmi_http.py` (in
turn from `_driver_update_routes/update.py`): an expired bearer token makes
OnPing answer `303 -> /auth/login` and a 200 HTML login page. We detect both on
every call and fail fast, so a login page is never mistaken for a spreadsheet,
a parsed config, or a successful write.

Endpoints are passed as routes-table strings of the form "METHOD /path" (see
`routes.py`); the leading method is stripped and `{serial}` / `{filename}` are
substituted before the request. Response verbs:

  - get_json      — GET returning parsed JSON (config, rules, artifacts, ...)
  - get_bytes     — GET returning raw bytes (the XLSX exports)
  - post_json     — POST a JSON body, returns the raw Response
  - post_empty    — POST with NO body (execute-rules, delete-unprocessed)
  - post_multipart— POST an XLSX as multipart field `f1`, returns raw Response
  - delete        — DELETE, returns the raw Response

`_fail(msg)` prints to stderr and exits non-zero. Read verbs fail-fast through
it directly; write verbs return the raw Response so the caller can gate on
status and surface `{"error": ...}` envelopes, but still fail-fast on the
auth-redirect / HTML fallthrough (which can never be a legitimate result).

`unwrap_envelope` handles the OnPing convention that a 200 may still carry
`{"error": "..."}` — see routes.py, ENVELOPE.
"""

from __future__ import annotations

import sys

import requests

from .routes import BASE_URL, TIMEOUT_SECONDS, XLSX_CONTENT_TYPE


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


def _url(endpoint: str, **path_params) -> str:
    """Turn a routes-table "METHOD /path/{serial}" into an absolute URL.

    The HTTP method prefix is stripped; each `{name}` placeholder is replaced by
    the matching keyword argument. Any leftover unresolved placeholder is a
    programming error and raises.
    """
    path = endpoint.split(" ", 1)[1] if " " in endpoint else endpoint
    for name, value in path_params.items():
        if value is not None:
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
    # An XLSX body is binary; decoding it as text can yield mojibake but never
    # a leading "<!doc"/"<html", so this check is safe for both flavors.
    if _looks_like_html(resp.text[:64]):
        _fail(
            f"Expected {expected} but received HTML — access token may be "
            f"expired or the route returned an error page."
        )


def _headers(token: str, **extra) -> dict:
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    h.update({k: v for k, v in extra.items() if v is not None})
    return h


# ────────────────────────────── envelope helper ────────────────────────────


def unwrap_envelope(payload, *, context: str):
    """Reject the `{"error": ...}` envelope that OnPing can return WITH a 200.

    A success is the bare payload, so anything that is not a dict carrying an
    "error" key passes through untouched.
    """
    if isinstance(payload, dict) and "error" in payload and len(payload) == 1:
        _fail(f"OnPing returned an error for {context}: {payload['error']}")
    return payload


# ─────────────────────────────── read verbs ────────────────────────────────


def get_json(token: str, endpoint: str, *, timeout: int | None = None, **path_params):
    """GET a JSON route; return the parsed body with the envelope unwrapped."""
    url = _url(endpoint, **path_params)
    try:
        resp = requests.get(
            url,
            headers=_headers(token),
            allow_redirects=True,
            timeout=timeout or TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} from {url}\n{resp.text[:500]}")
    try:
        payload = resp.json()
    except ValueError:
        _fail(f"Expected JSON but could not parse response from {url}:\n{resp.text[:500]}")
    return unwrap_envelope(payload, context=endpoint)


def get_bytes(
    token: str, endpoint: str, *, expect: str = "XLSX", timeout: int | None = None,
    **path_params,
) -> bytes:
    """GET a binary route (the XLSX exports); return the body bytes.

    Fails fast on request error, auth-redirect, HTML body, or non-2xx — the
    caller never writes a partial/garbage file. Also rejects a JSON error
    envelope served in place of a spreadsheet.
    """
    url = _url(endpoint, **path_params)
    try:
        resp = requests.get(
            url,
            headers=_headers(token, Accept="*/*"),
            allow_redirects=True,
            timeout=timeout or TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, expect)
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} from {url}\n{resp.text[:500]}")
    body = resp.content
    if expect == "XLSX" and not body.startswith(b"PK"):
        # Every .xlsx is a zip; a non-PK body means we got an error document.
        _fail(
            f"Expected an XLSX (zip) body from {url} but got "
            f"{body[:120]!r} — the route may have returned an error envelope."
        )
    return body


# ─────────────────────────────── write verbs ───────────────────────────────


def post_json(
    token: str, endpoint: str, body, *, timeout: int | None = None, **path_params
) -> requests.Response:
    """POST a JSON body. Returns the raw Response for the caller to gate on."""
    url = _url(endpoint, **path_params)
    try:
        resp = requests.post(
            url,
            headers=_headers(token, **{"Content-Type": "application/json"}),
            json=body,
            allow_redirects=True,
            timeout=timeout or TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    return resp


def post_empty(
    token: str, endpoint: str, *, timeout: int | None = None, **path_params
) -> requests.Response:
    """POST with no body — for execute-rules and delete-unprocessed.

    Those handlers take no request body at all; the frontend calls them with
    `postRequestNoBody`. Sending `{}` would be harmless but is not what the UI
    does, so we send nothing.
    """
    url = _url(endpoint, **path_params)
    try:
        resp = requests.post(
            url,
            headers=_headers(token),
            allow_redirects=True,
            timeout=timeout or TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    return resp


def post_multipart_xlsx(
    token: str,
    endpoint: str,
    xlsx_bytes: bytes,
    *,
    filename: str = "import.xlsx",
    timeout: int | None = None,
    **path_params,
) -> requests.Response:
    """POST an XLSX as multipart field `f1`. Returns the raw Response.

    The field name MUST be `f1` — see routes.py gotcha 2. The handler's
    `fileAFormReq "File"` label is not the field name, and posting `File`
    returns `400 FormFailure`.
    """
    url = _url(endpoint, **path_params)
    try:
        resp = requests.post(
            url,
            headers=_headers(token),  # requests sets the multipart Content-Type
            files={"f1": (filename, xlsx_bytes, XLSX_CONTENT_TYPE)},
            allow_redirects=True,
            timeout=timeout or TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    return resp


def delete(
    token: str, endpoint: str, *, timeout: int | None = None, **path_params
) -> requests.Response:
    """DELETE a route. Returns the raw Response for the caller to gate on."""
    url = _url(endpoint, **path_params)
    try:
        resp = requests.delete(
            url,
            headers=_headers(token),
            allow_redirects=True,
            timeout=timeout or TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    return resp


# ──────────────────────────── write-result helper ──────────────────────────


def report_write(resp: requests.Response, *, what: str) -> None:
    """Fail-fast on a non-2xx or an `{"error": ...}` body after a mutation.

    The import handlers return 400 with the xlsx parse error as a bare JSON
    string, so the error text is surfaced verbatim rather than summarized.
    """
    if not (200 <= resp.status_code < 300):
        _fail(f"{what} failed — HTTP {resp.status_code}:\n{resp.text[:1000]}")
    if resp.text.strip():
        try:
            payload = resp.json()
        except ValueError:
            return
        if isinstance(payload, dict) and "error" in payload:
            _fail(f"{what} failed — OnPing returned: {payload['error']}")
