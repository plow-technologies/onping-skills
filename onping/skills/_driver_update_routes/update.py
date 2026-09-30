"""Shared read-modify-write helper for OnPing driver location-update skills.

`update_location(...)` performs a SAFE single-field update of a driver location's
config by read-modify-write:

  1. FETCH the current full config from the driver's fetch endpoint.
  2. NORMALIZE the response (Group A: config object directly; Group B: the
     OnpingResponse wrapper whose ToJSON unwraps to the inner config).
  3. SET only the allowlisted field(s) requested (poll time + verified safe
     fields), leaving every other key byte-for-byte as fetched.
  4. ASSERT every locked field (lumberjack-binding + identity) is unchanged.
  5. POST the whole object back to the update endpoint (unless --dry-run or
     confirmation was withheld).

Why read-modify-write: the OnPing update handlers parse the FULL config record,
not a patch. Sending a partial body would null the omitted fields — including the
lumberjack routing keys. So we always round-trip the entire fetched record.

Lumberjack safety: drivers run on Lumberjack edge devices. The lumberjack-binding
fields (url/port pair, or LJSerial) are ROUTING KEYS. Changing them via the normal
update silently desyncs routing or retargets the wrong device. This helper never
exposes them as settable and refuses to POST if any locked field would change.

Auth hardening (reused from _driver_export_routes/download.py): an expired bearer
token makes OnPing answer `303 -> /auth/login` with a 200 HTML login page. We
detect the auth-redirect and HTML-body fallthrough on BOTH fetch and update and
fail fast, so a login page is never mistaken for a config or a successful write.
"""

from __future__ import annotations

import json
import sys

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 60


# ─────────────────────────── dotted-path helpers ───────────────────────────


def _get_path(obj: dict, path: str):
    """Get a value by dotted path (e.g. 'a.b.c'). Raises KeyError if missing."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def _has_path(obj: dict, path: str) -> bool:
    try:
        _get_path(obj, path)
        return True
    except KeyError:
        return False


def _set_path(obj: dict, path: str, value) -> None:
    """Set a value by dotted path. Intermediate objects must already exist."""
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"cannot set {path}: missing intermediate '{part}'")
        cur = cur[part]
    cur[parts[-1]] = value


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


def _post(token: str, path: str, body, params: dict | None = None) -> requests.Response:
    """Authenticated POST with auth-redirect / HTML-fallthrough hardening.

    `path` may be a routes-table endpoint of the form "POST /some/path"; the
    leading HTTP method is stripped before building the URL.
    """
    if " " in path:  # "POST /foo" -> "/foo"
        path = path.split(" ", 1)[1]
    url = path if path.startswith("http") else BASE_URL + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=body,
            params=params,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        _fail(f"Request error ({path}): {e}")

    if _auth_redirected(resp):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url})"
        )
    if _looks_like_html(resp.text):
        _fail(
            "Expected JSON but received HTML — access token may be expired "
            f"or route returned an error page ({path})"
        )
    return resp


# ──────────────────────────── fetch / normalize ────────────────────────────


def _fetch_body(route: dict, ref_id: int, serial: str | None):
    conv = route["fetch_body"]
    if conv == "tuple":
        return [ref_id, False]  # [refId, pollImmediate=false] -> read stored config
    if conv == "refid":
        return ref_id
    if conv == "ljserial":
        if not serial:
            _fail(
                f"Driver '{route['driver']}' is keyed by Lumberjack serial; "
                f"pass --serial <LJSerial>."
            )
        return serial
    _fail(f"Unknown fetch_body convention: {conv!r}")


def _normalize(route: dict, parsed):
    """Return the config object from a fetch response (A=direct, B=unwrapped)."""
    if isinstance(parsed, dict) and "error" in parsed and len(parsed) == 1:
        _fail(f"Fetch failed: {parsed['error']}")
    # OnpingResponse ToJSON unwraps to the inner config, so by the time we parse
    # JSON both groups present the config object directly. Anything that isn't an
    # object is unusable for round-trip.
    if not isinstance(parsed, dict):
        _fail(
            f"Fetch returned a non-object body ({type(parsed).__name__}); "
            f"cannot round-trip config for '{route['driver']}'."
        )
    return parsed


def fetch_config(token: str, route: dict, ref_id: int, serial: str | None) -> dict:
    params = {"serial": serial} if route.get("fetch_serial") else None
    if route.get("fetch_serial") and not serial:
        _fail(
            f"Driver '{route['driver']}' fetch requires a Lumberjack serial; "
            f"pass --serial <LJSerial>."
        )
    resp = _post(token, route["fetch_endpoint"], _fetch_body(route, ref_id, serial), params)
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} fetching config:\n{resp.text[:500]}")
    try:
        parsed = resp.json()
    except ValueError:
        _fail(f"Fetch response was not JSON:\n{resp.text[:500]}")
    return _normalize(route, parsed)


# ──────────────────────────────── update ────────────────────────────────────


def _diff(before: dict, after: dict, paths: list[str]) -> str:
    lines = []
    for p in paths:
        b = _get_path(before, p) if _has_path(before, p) else "<absent>"
        a = _get_path(after, p) if _has_path(after, p) else "<absent>"
        flag = " " if b == a else "*"
        lines.append(f"  {flag} {p}: {b!r} -> {a!r}")
    return "\n".join(lines)


def update_location(
    token: str,
    route: dict,
    ref_id: int,
    *,
    poll_time: int | None = None,
    extra_fields: dict | None = None,
    serial: str | None = None,
    dry_run: bool = False,
    confirm: bool = False,
) -> None:
    """Fetch -> set allowlisted fields -> assert locked fields -> POST (or preview).

    Prints a human summary. Exits non-zero on any failure or refused mutation.
    """
    driver = route["driver"]
    extra_fields = extra_fields or {}

    # ---- validate requested fields against the allowlist BEFORE any network ----
    changes: dict[str, object] = {}  # path -> new value

    if poll_time is not None:
        if route["poll_field"] is None:
            _fail(
                f"Driver '{driver}' does not poll — it has no poll-time field, "
                f"so --poll-time is not applicable."
            )
        if poll_time < 1:
            _fail(f"--poll-time must be a positive integer (seconds); got {poll_time}.")
        changes[route["poll_field"]] = poll_time

    for key, value in extra_fields.items():
        if key not in route["safe_fields"]:
            _fail(
                f"Field '{key}' is not in the safe allowlist for driver "
                f"'{driver}'. Allowed: {route['safe_fields'] or '(poll time only)'}."
            )
        changes[key] = value

    if not changes:
        _fail("No editable field requested. Pass --poll-time (or a safe field).")

    # Refuse if any requested change targets a locked field.
    for path in changes:
        if path in route["locked_fields"]:
            _fail(f"Refusing to modify locked field '{path}' on driver '{driver}'.")

    # ---- fetch current config ----
    before = fetch_config(token, route, ref_id, serial)
    after = json.loads(json.dumps(before))  # deep copy

    # ---- apply allowlisted changes ----
    for path, value in changes.items():
        if not _has_path(after, path):
            _fail(
                f"Fetched config has no field '{path}' for driver '{driver}'. "
                f"The route metadata may be stale (re-verify against the handler)."
            )
        _set_path(after, path, value)

    # ---- defense-in-depth: assert locked fields unchanged ----
    for path in route["locked_fields"]:
        b = _get_path(before, path) if _has_path(before, path) else None
        a = _get_path(after, path) if _has_path(after, path) else None
        if b != a:
            _fail(
                f"Refusing to POST: locked field '{path}' would change "
                f"({b!r} -> {a!r}). Lumberjack/identity fields must not be edited."
            )

    # ---- preview ----
    preview_paths = list(changes) + list(route["locked_fields"])
    print(f"Driver: {driver}  refId: {ref_id}")
    print("Payload changes (* = changed; locked fields shown for safety):")
    print(_diff(before, after, preview_paths))

    if dry_run:
        print("\n[dry-run] No update POSTed.")
        return

    if not confirm:
        print(
            "\nNo --yes given: not mutating. Re-run with --yes to apply this update."
        )
        return

    # ---- POST the full updated config ----
    resp = _post(token, route["update_endpoint"], after)
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} updating config:\n{resp.text[:500]}")
    try:
        parsed = resp.json()
        if isinstance(parsed, dict) and "error" in parsed:
            _fail(f"Update failed: {parsed['error']}")
        summary = json.dumps(parsed)[:300]
    except ValueError:
        summary = resp.text[:300]

    changed_desc = ", ".join(
        f"{p} {_get_path(before, p)!r}->{_get_path(after, p)!r}" for p in changes
    )
    print(f"\n✓ Updated {driver} refId {ref_id}: {changed_desc}")
    print(f"  response: {summary}")
