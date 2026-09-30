"""HTTP transport for the OnPing documentation site's MCP and REST surfaces.

Every `onping-doc-*` skill goes through these functions, so the SSE framing, the
mandatory Accept header, the JSON-RPC envelope, and the error detection live in
one place.

THE LOAD-BEARING FUNCTION IS `_raise_on_error_text`. Every MCP tool returns its
payload as a human-readable string at `result.content[0].text`, and a FAILED
operation returns a JSON-RPC `result` — not an `error` member — whose text merely
begins with an error sentence:

    findDocs id=99999   -> 'Error: Document with ID "99999" not found in collection "docs"'
    getDocsByCategory   -> 'Error fetching documents by category: Failed query: ... params: NaN'
    compareDoc (no id)  -> 'Error: Could not find document with ID "undefined"'

All three arrive as HTTP 200 with a `result`. A client that checks only for a
JSON-RPC `error` member reports every one of them as SUCCESS. That is the defect
this module exists to prevent.

TRANSPORT NOTES

  - `/api/mcp` responds with Server-Sent Events, not plain JSON:
        event: message
        data: {"result":{...},"jsonrpc":"2.0","id":1}
    The `data: ` prefix must be stripped before parsing. A client that parses the
    raw body fails on an HTTP 200.
  - `Accept` must carry BOTH `application/json` and `text/event-stream`, or the
    server returns 406. `mcp_headers()` handles this.
  - NO `initialize` handshake is sent. The server accepts `tools/call` as the
    first request on a fresh connection and returns no session id, so the client
    stays stateless.
  - Every AUTH failure is a bodiless 500 (see `auth_failure_hint`).
"""

from __future__ import annotations

import json
import sys

import requests

from .routes import (
    TIMEOUT_SECONDS,
    mcp_headers,
    mcp_url,
    rest_headers,
    rest_url,
)

# Prefixes that mark a tool result as a failure despite the HTTP 200 + `result`.
# Matched case-insensitively against the start of the returned text.
_ERROR_PREFIXES = (
    "error:",
    "error fetching",
    "error creating",
    "error updating",
    "error deleting",
    "failed to",
)


def _fail(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(1)


def auth_failure_hint(status: int, body: str, header_form: str) -> str | None:
    """Diagnose a bodiless 500, which is how this server reports every auth failure.

    The server returns HTTP 500 with a zero-byte body and no JSON envelope for a
    garbage credential, for the wrong header form, and for an uncredentialed read
    of a key-gated route. It names neither the credential nor the header at fault,
    and it is indistinguishable from a genuine server fault. This message is
    therefore the only diagnosis available, so it always reports the header form
    that was actually sent.

    An earlier reading of this service recorded a `401` here. It does not
    reproduce; do not promise one.
    """
    if status != 500 or body.strip():
        return None
    return (
        f"HTTP 500 with an empty body, sent with the {header_form} header form.\n"
        "This service reports EVERY authentication failure this way, so the cause "
        "is most likely one of:\n"
        "  - the wrong Authorization form for this route "
        "(/api/mcp needs Bearer; /api/users and /api/payload-mcp-api-keys need "
        "the API-Key form)\n"
        "  - a missing, invalid, or revoked API key\n"
        "  - a genuine server fault, which looks identical\n"
        "The response carries no further diagnosis."
    )


# ────────────────────────────────── MCP ─────────────────────────────────────


def _post_rpc(key: str, method: str, params: dict | None = None) -> dict:
    """POST one JSON-RPC request to /api/mcp and return the de-framed envelope."""
    payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params

    try:
        resp = requests.post(
            mcp_url(),
            headers=mcp_headers(key),
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        _fail(f"Request to {mcp_url()} failed: {exc}")

    hint = auth_failure_hint(resp.status_code, resp.text, "Bearer")
    if hint:
        _fail(hint)

    if resp.status_code == 406:
        # Unreachable through mcp_headers(); kept because the message is specific.
        _fail(
            "HTTP 406 — /api/mcp requires "
            "'Accept: application/json, text/event-stream' (both media types)."
        )

    if resp.status_code >= 400:
        _fail(f"HTTP {resp.status_code} from {mcp_url()}: {resp.text[:800]}")

    return _parse_sse(resp.text)


def _parse_sse(body: str) -> dict:
    """Strip the SSE framing and parse the JSON-RPC envelope.

    Responses look like:
        event: message
        data: {"result":{...},"jsonrpc":"2.0","id":1}

    Tolerates a plain-JSON body, in case the server stops using SSE.
    """
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            raw = line[len("data:") :].strip()
            if not raw:
                continue
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                _fail(f"Could not parse SSE data payload as JSON: {exc}\n{raw[:500]}")

    stripped = body.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    _fail(f"No SSE 'data:' payload in response from /api/mcp:\n{body[:500]}")
    raise AssertionError("unreachable")  # pragma: no cover


def _raise_on_error_text(tool: str, text: str) -> None:
    """Exit non-zero when a tool's text reports a failure.

    A failed tool call arrives as HTTP 200 with a JSON-RPC `result`, so the text
    is the only failure signal. The server's wording is surfaced verbatim because
    it carries the SQL parameter and column that identify the cause.
    """
    head = text.lstrip()[:200].lower()
    for prefix in _ERROR_PREFIXES:
        if head.startswith(prefix):
            _fail(f"{tool} failed:\n{text.strip()}")


def call_tool(key: str, name: str, arguments: dict | None = None) -> str:
    """Call one MCP tool and return `result.content[0].text`.

    Exits non-zero on a JSON-RPC `error` member AND on a `result` whose text
    reports a failure. See `_raise_on_error_text`.
    """
    envelope = _post_rpc(
        key, "tools/call", {"name": name, "arguments": arguments or {}}
    )

    if "error" in envelope:
        err = envelope["error"]
        if isinstance(err, dict):
            _fail(
                f"{name} returned a JSON-RPC error "
                f"(code {err.get('code')}): {err.get('message')}"
            )
        _fail(f"{name} returned a JSON-RPC error: {err}")

    result = envelope.get("result")
    if not isinstance(result, dict):
        _fail(f"{name} returned no result object: {json.dumps(envelope)[:500]}")

    content = result.get("content")
    if not isinstance(content, list) or not content:
        _fail(f"{name} returned an empty content list: {json.dumps(result)[:500]}")

    text = content[0].get("text")
    if not isinstance(text, str):
        _fail(f"{name} returned no text payload: {json.dumps(content[0])[:500]}")

    _raise_on_error_text(name, text)
    return text


def list_tools(key: str) -> list[str]:
    """Return the tool names the server currently offers.

    The roster is a function of the API key's grants, so it is read from the
    server rather than hardcoded. A grant change alters it.
    """
    envelope = _post_rpc(key, "tools/list")
    if "error" in envelope:
        _fail(f"tools/list returned a JSON-RPC error: {envelope['error']}")
    tools = (envelope.get("result") or {}).get("tools")
    if not isinstance(tools, list):
        _fail(f"tools/list returned no tool array: {json.dumps(envelope)[:500]}")
    return [t.get("name", "") for t in tools if isinstance(t, dict)]


def extract_json_blocks(text: str) -> list[dict]:
    """Pull JSON objects out of a tool's prose response.

    `findDocs` embeds a document as JSON inside a fenced ```json block within a
    human-readable string, while `getDocsByCategory` returns prose with
    `Document ID: <n>` lines and no JSON at all. Two response shapes for two tools
    in the same collection, so a caller must handle both.

    Returns every parseable object found, or [] when the text carries no JSON.
    """
    blocks: list[dict] = []
    marker = "```"
    idx = 0
    while True:
        start = text.find(marker, idx)
        if start == -1:
            break
        newline = text.find("\n", start)
        if newline == -1:
            break
        end = text.find(marker, newline)
        if end == -1:
            break
        body = text[newline + 1 : end].strip()
        idx = end + len(marker)
        if not body.startswith(("{", "[")):
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            blocks.append(parsed)
        elif isinstance(parsed, list):
            blocks.extend(x for x in parsed if isinstance(x, dict))

    if blocks:
        return blocks

    # Fall back to a bare object spanning the first '{' to the last '}'.
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        try:
            parsed = json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, dict):
            return [parsed]
    return []


# ────────────────────────────────── REST ────────────────────────────────────


def get_rest(key: str | None, route: str, params: dict | None = None, **path_params):
    """GET one read-only REST route and return parsed JSON.

    The docs collections are world-readable, so the key is sent defensively rather
    than because the route needs it. See `routes.rest_headers`.
    """
    url = rest_url(route, **path_params)
    try:
        resp = requests.get(
            url,
            headers=rest_headers(key),
            params=params or {},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        _fail(f"Request to {url} failed: {exc}")

    hint = auth_failure_hint(resp.status_code, resp.text, "payload-mcp-api-keys API-Key")
    if hint:
        _fail(hint)

    if resp.status_code >= 400:
        _fail(f"HTTP {resp.status_code} from {url}: {resp.text[:800]}")

    try:
        return resp.json()
    except ValueError:
        _fail(f"Non-JSON response from {url}: {resp.text[:500]}")
