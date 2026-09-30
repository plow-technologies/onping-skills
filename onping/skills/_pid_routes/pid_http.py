"""Shared HTTP + lookup helpers for onping-pid-locate and onping-pid-write.

The PID lookup lives here because THREE callers need it and they must agree:

  - `onping-pid-locate` — it is the whole skill
  - `onping-pid-write --verify` — the post-write read-back
  - `onping-pid-write --via-hmi` — builds the writeV2 envelope from the LIVE
    lookup rather than from user-supplied routing fields

If those three drifted apart, `--via-hmi` could send an envelope inconsistent
with what `locate` reports — which is exactly the mis-targeting failure the
default route exists to prevent. One implementation, imported by both skills.

The auth-redirect / HTML-fallthrough hardening is carried over verbatim from
`_hmi_routes/hmi_http.py`: an expired bearer token makes OnPing answer
`303 -> /auth/login` and a 200 HTML login page. Both are detected on every call
so a login page is never mistaken for a lookup result or a successful write.
"""

from __future__ import annotations

import sys

import requests

from .routes import BASE_URL, ROUTES, TIMEOUT_SECONDS

# ─────────────────────────── the not-found notes ───────────────────────────
#
# TWO notes, because there are two different failures and conflating them is how
# this module once reported a live virtual parameter as nonexistent.
#
# `applyMask` (ParameterLister.hs) keeps only tags whose locationId is in
# the caller's authorized-location map and drops the rest with NO marker. So all
# three causes below are one indistinguishable outcome, and the note has to name
# all three rather than guessing one. This note is correct for a key that was
# addressed CORRECTLY and still came back absent.
NOT_FOUND_NOTE = (
    "not returned by the lister — the PID does not exist, has been deleted, or "
    "belongs to a location this token cannot see. The route drops all three "
    "identically with no marker, so they cannot be distinguished from the response."
)

# What the note above must NEVER be used for: a key this tool failed to ADDRESS.
# Before 2026-08-21 a VPID was sent as a bare integer, which the server reads as
# KeyPID (Onping/Tag/Types.hs), so it matched nothing and inherited the note
# above — asserting nonexistence, deletion, and invisibility about a parameter
# that was alive and updating every few minutes. A `NOT FOUND` on live equipment
# was read as "the control loop is dead" for four producing wells over 56 days.
# The encoding is fixed below; this note exists so that if a key is ever again
# un-addressable, the output says THAT instead of inventing a cause.
UNADDRESSABLE_NOTE = (
    "could not be addressed as a {key_type} by the route this skill used. This is "
    "a statement about this tool's reach, NOT about the parameter — it may well "
    "exist and be healthy. Nothing here says it does not exist."
)

# A VP whose description resolved but whose value the OnpingKey route declined to
# compute. Verified live 2026-08-21: the route returns `result.tag OnPingNoData`
# with `lastUpdate 0` for a VPID under ALL FOUR combinations of
# preq_optionVPCalculateResult x preq_optionExcludePID. Values live on the
# location-scoped ParameterRequestLookupId query instead. If the second call
# cannot supply one, the entry says so rather than printing `None` — which would
# be indistinguishable from a parameter genuinely holding no data.
VALUE_UNCOMPUTED_NOTE = (
    "description resolved, but no value could be computed for this virtual "
    "parameter. The OnpingKey route never computes a VP result (it returns "
    "OnPingNoData with lastUpdate 0 under every option combination) and the "
    "location-scoped ParameterRequestLookupId query did not return this VPID. "
    "The value is UNKNOWN — this is not a report that the parameter has no value."
)


# ─────────────────────────────── auth checks ───────────────────────────────


def _auth_redirected(resp: requests.Response) -> bool:
    return bool(resp.history) and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    )


def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:5].lower() in ("<!doc", "<html")


def fail(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(1)


def _url(endpoint: str) -> str:
    path = endpoint.split(" ", 1)[1] if " " in endpoint else endpoint
    return path if path.startswith("http") else BASE_URL + path


def _guard(resp: requests.Response, expected: str) -> None:
    """Fail fast on the auth-redirect / HTML-login fallthrough."""
    if _auth_redirected(resp):
        fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url})."
        )
    if _looks_like_html(resp.text):
        fail(
            f"Expected {expected} but received HTML — access token may be "
            f"expired or the route returned an error page."
        )


# ──────────────────────────────── transport ────────────────────────────────


def post_json(token: str, endpoint: str, body) -> requests.Response:
    """POST a JSON body; return the raw Response for the caller to classify.

    Returns rather than fails on a non-2xx, because both write routes carry
    meaningful error payloads that the caller must read (the source route's
    `{"error": ...}` and the HMI route's tagged HmiError). Still fails fast on
    the auth-redirect / HTML fallthrough, which can never be a real result.
    """
    url = _url(endpoint)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=body,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    return resp


def get_json(token: str, endpoint: str, params: dict | None = None):
    """GET a JSON route; fail fast on any non-2xx (used only for --names)."""
    url = _url(endpoint)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(
            url,
            headers=headers,
            params=params,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        fail(f"Request error ({endpoint}): {e}")
    _guard(resp, "JSON")
    if not (200 <= resp.status_code < 300):
        fail(f"HTTP {resp.status_code} from {url}\n{resp.text[:500]}")
    try:
        return resp.json()
    except ValueError:
        fail(f"Expected JSON but could not parse response from {url}:\n{resp.text[:500]}")


# ───────────────────────────────── lookup ─────────────────────────────────


def _entry_from_item(item: dict) -> dict | None:
    """Flatten one TagInfoWithLocations item. Returns None if unusable.

    `tagLocations` is typed `[Location]` and for a PID always carries exactly one
    (`makeTagInfoWithLocations` does `let locations = [location]`,
    ParameterLister.hs) — confirmed live across all 43 parameters at
    location 20001. The plural is real for VPIDs, so every location is kept in
    `locations` while `location` exposes the first for the PID case.

    An EMPTY tagLocations is treated as unusable rather than indexed blindly:
    `[0]` on an empty list would raise instead of reporting not-found.
    """
    tag_info = item.get("tagInfo")
    if not isinstance(tag_info, dict):
        return None
    locations = item.get("tagLocations") or []
    if not isinstance(locations, list) or not locations:
        return None

    primary = locations[0] if isinstance(locations[0], dict) else {}
    result = tag_info.get("result") or {}
    unit = tag_info.get("unit") or {}

    return {
        "found": True,
        "pid": tag_info.get("parameterId"),
        "location_id": tag_info.get("locationId"),
        "location_name": primary.get("name"),
        "location_slave_id": primary.get("slaveId"),
        "location_url": primary.get("url"),
        "site": tag_info.get("siteId"),
        "company": tag_info.get("companyId"),
        # `localParameterId` IS the SourceId — the driver descriptor writeV2
        # dispatches on. Kept whole: its extra keys (slave-id / tag-id / tlp)
        # vary by driver and all of them matter to the envelope.
        "source": tag_info.get("localParameterId"),
        "unit": unit.get("unit"),
        "description": tag_info.get("description"),
        "writeability": tag_info.get("writeability"),
        "last_update": tag_info.get("lastUpdate"),
        "value": result.get("value"),
        "value_tag": result.get("tag"),
        "locations": locations,
    }


def _pid_of(item: dict):
    """The parameterId an item is about, or None.

    For a PID the lister returns a bare integer. For a VPID (with --vp) it
    returns the tagged object `{"keyType": "VPID", "keyValue": n}`, since the v3
    route is keyed by OnpingKey rather than PID (Onping/Tag/Types.hs).
    """
    tag_info = item.get("tagInfo") or {}
    raw = tag_info.get("parameterId")
    if isinstance(raw, dict):
        return raw.get("keyValue")
    return raw


def _onping_key(key_value: int, key_type: str) -> dict:
    """One tagged OnpingKey for the request side.

    EVERY key is tagged, both kinds, because a bare integer MEANS KeyPID:
    `FromJSON OnpingKey` falls back to it for any non-object
    (Onping/Tag/Types.hs). That is why the pre-2026-08-21 code could not
    address a VPID at all — `include_vp` toggled the option flags and never the
    key encoding, so a VPID was asked for as a PID, matched nothing, and was
    reported NOT FOUND.

    Tagging unconditionally is safe and measured: explicit `PID` tagging returns
    a byte-identical item to a bare integer, and a MIXED batch resolves both
    kinds in one request — so there is no per-type request branching to get
    wrong.
    """
    return {"keyType": key_type, "keyValue": key_value}


def _parse_lister_payload(resp, endpoint: str) -> list:
    """Validate a lister response into a list of items, or fail."""
    if not (200 <= resp.status_code < 300):
        fail(f"HTTP {resp.status_code} from {endpoint}\n{resp.text[:500]}")
    try:
        payload = resp.json()
    except ValueError:
        fail(f"Response was not JSON:\n{resp.text[:500]}")

    # An {"error": ...} envelope is a failure even with a 2xx.
    if isinstance(payload, dict):
        if "error" in payload:
            fail(f"Lister failed: {payload['error']}")
        fail(f"Unexpected lister payload type: {type(payload).__name__}")
    if not isinstance(payload, list):
        fail(f"Unexpected lister payload type: {type(payload).__name__}")
    return payload


def _index_by_parameter_id(payload: list) -> dict[int, dict]:
    """Key items by their OWN parameterId, never by list position.

    The lister does not preserve request order — verified live, and it holds for
    tagged requests too: a request for [VPID 500109, PID 500006] came back
    [500006, 500109]. A positional zip would attribute one parameter's location
    to another, and since `onping-pid-write --via-hmi` builds its envelope from
    this lookup, that mistake could aim a WRITE at the wrong location while
    reporting success.
    """
    by_pid: dict[int, dict] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        pid = _pid_of(item)
        if pid is None:
            continue
        entry = _entry_from_item(item)
        if entry is None:
            continue  # empty tagLocations -> reported not-found by the caller
        by_pid[int(pid)] = entry
    return by_pid


def _value_was_computed(entry: dict) -> bool:
    """Whether a resolved entry carries a real value or the route declined one.

    Verified live: for a VPID the OnpingKey route returns `result.tag`
    `OnPingNoData` with `lastUpdate 0` under all four option combinations. That
    is a positive signal the route declined to compute, distinct from a
    parameter that genuinely holds no data at a real timestamp — so this checks
    the tag rather than inferring from `value is None`.
    """
    return not (entry.get("value") is None and entry.get("value_tag") == "OnPingNoData")


def _fetch_vp_values(token: str, entries: dict[int, dict], vpids: set[int]) -> None:
    """Fill in VP values from the location-scoped route, in place.

    The OnpingKey route returns a VP's description but NOT its value under any
    option combination (measured four-way sweep). Values live on
    `ParameterRequestLookupId`, scoped by location — so step 1's `locationId` is
    what makes step 2 possible.

    One request per batch of distinct locations. Only called when VPIDs were
    requested, so the plain-PID path still costs exactly one call.
    """
    locations = sorted(
        {
            entries[v]["location_id"]
            for v in vpids
            if entries.get(v, {}).get("found")
            and not _value_was_computed(entries[v])
            and entries[v].get("location_id") is not None
        }
    )
    if not locations:
        return

    route = ROUTES["locate"]
    body = {
        "preq_query": {
            "tag": "ParameterRequestLookupId",
            "contents": {
                "getLocationLookupList": locations,
                "getCompanyLookupList": [],
                "getSiteLookupList": [],
            },
        },
        "preq_optionVP": True,
        "preq_optionVPCalculateResult": True,
        # VP-ONLY on purpose. Plain PIDs are absent from this response, which is
        # what keeps the plain-PID path provably untouched by this second call.
        "preq_optionExcludePID": True,
    }
    # Through post_json so the auth-redirect / HTML-login guards wrap this call
    # too: a login page read as an empty VP list would present as "this VP has
    # no value" — the same genus of error as the bug being fixed.
    resp = post_json(token, route["endpoint"], body)
    by_pid = _index_by_parameter_id(_parse_lister_payload(resp, route["endpoint"]))

    # FILTER to what was asked for. This route returns EVERY VP at the location
    # (10 for location 20002), and an unrequested VP must never enter the output
    # or be recorded against an id the caller did not ask about.
    for vpid in vpids:
        fresh = by_pid.get(vpid)
        if fresh is None or not _value_was_computed(fresh):
            continue
        entry = entries.get(vpid)
        if not entry or not entry.get("found"):
            continue
        # Take the value and its timestamp; keep step 1's identity/location
        # fields, which are already correct and were resolved by key.
        entry["value"] = fresh.get("value")
        entry["value_tag"] = fresh.get("value_tag")
        entry["last_update"] = fresh.get("last_update")


def lookup_pids(
    token: str,
    pids: list[int],
    *,
    include_vp: bool = False,
    vpids: list[int] | None = None,
) -> dict[int, dict]:
    """Resolve PIDs and VPIDs to their location and current value.

    Returns a dict keyed by the REQUESTED id, with an entry for every id asked
    for — `found: True` with the resolved fields, or `found: False` with a note.
    Never silently short.

    `pids` are addressed as PIDs; ids in `vpids` are addressed as VPIDs. Both
    kinds ride in ONE tagged request (measured: a mixed batch resolves both).
    Passing `vpids` implies virtual-parameter options; `include_vp` remains
    accepted so existing callers keep working, and turns the option flags on
    without changing how `pids` are encoded.

    A VPID additionally costs ONE location-scoped request, because the OnpingKey
    route returns a VP's description but never its value. A plain-PID lookup is
    still exactly one call.

    Results are matched by the response's own `parameterId`, NEVER by list
    position (verified live — `[500001, 99999999, 500002]` returned
    `[500002, 500001]`).
    """
    vp_list = [int(v) for v in (vpids or [])]
    vp_set = set(vp_list)
    # Requested order is preserved for output; a VPID declaration wins over a
    # plain-PID one for the same integer, since the caller said it is virtual.
    plain = [int(p) for p in pids if int(p) not in vp_set]
    want_vp = include_vp or bool(vp_set)

    route = ROUTES["locate"]
    contents = [_onping_key(p, "PID") for p in plain] + [
        _onping_key(v, "VPID") for v in vp_list
    ]
    body = {
        "preq_query": {
            "tag": "ParameterRequestOnpingKey",
            "contents": contents,
        },
        "preq_optionVP": want_vp,
        "preq_optionVPCalculateResult": want_vp,
        "preq_optionExcludePID": False,
    }
    resp = post_json(token, route["endpoint"], body)
    by_pid = _index_by_parameter_id(_parse_lister_payload(resp, route["endpoint"]))

    out: dict[int, dict] = {}
    for pid in list(pids) + [v for v in vp_list if v not in set(pids)]:
        pid = int(pid)
        if pid in by_pid:
            entry = by_pid[pid]
            entry["key_type"] = "VPID" if pid in vp_set else "PID"
            out[pid] = entry
        elif pid in vp_set:
            # A VPID absent from a request that ADDRESSED it as a VPID. Do not
            # reach for the three-cause note: this tool could not address it.
            out[pid] = {
                "found": False,
                "pid": pid,
                "key_type": "VPID",
                "unaddressable": True,
                "note": UNADDRESSABLE_NOTE.format(key_type="VPID"),
            }
        else:
            out[pid] = {
                "found": False,
                "pid": pid,
                "key_type": "PID",
                "note": NOT_FOUND_NOTE,
            }

    if vp_set:
        _fetch_vp_values(token, out, vp_set)
        # Any VPID whose value the second call could not supply says so
        # explicitly rather than rendering as `None`.
        for vpid in vp_set:
            entry = out.get(vpid, {})
            if entry.get("found") and not _value_was_computed(entry):
                entry["value_uncomputed"] = True
                entry["note"] = VALUE_UNCOMPUTED_NOTE

    return out


def lookup_one(token: str, pid: int, *, as_vpid: bool = False) -> dict:
    """Resolve a single id. Convenience wrapper over `lookup_pids`.

    PID-only by default and positional in `pid`, because `onping-pid-write`
    calls it as `lookup_one(token, pid)` at two sites (its dry-run resolution
    and its --verify read-back) and neither may change behavior.
    """
    if as_vpid:
        return lookup_pids(token, [], vpids=[pid])[pid]
    return lookup_pids(token, [pid])[pid]


# ───────────────────────── --names enrichment ─────────────────────────
#
# The lister returns the location's own name but only numeric site/company refs.
# Resolving those to names costs two more calls, which is why it is behind a flag
# rather than in the default path.


def _index_lister(payload) -> dict[int, str]:
    """Index a `[{key, value: {refId, name}}]` lister payload by refId."""
    out: dict[int, str] = {}
    if not isinstance(payload, list):
        return out
    for item in payload:
        value = item.get("value") if isinstance(item, dict) else None
        if not isinstance(value, dict):
            continue
        ref_id, name = value.get("refId"), value.get("name")
        if ref_id is not None and name is not None:
            out[int(ref_id)] = name
    return out


def resolve_names(token: str, entries: dict[int, dict]) -> None:
    """Add `site_name` / `company_name` to found entries, in place.

    Two extra calls: companyLister (all visible companies) and siteLister per
    distinct company id, since siteLister is scoped by company.
    """
    company_ids = {
        e["company"] for e in entries.values() if e.get("found") and e.get("company") is not None
    }
    if not company_ids:
        return

    companies = _index_lister(get_json(token, ROUTES["companies"]["endpoint"]))

    sites: dict[int, str] = {}
    for company_id in sorted(company_ids):
        sites.update(
            _index_lister(
                get_json(
                    token,
                    ROUTES["sites"]["endpoint"],
                    params={"getCompanyLookupList": str(company_id)},
                )
            )
        )

    for entry in entries.values():
        if not entry.get("found"):
            continue
        site_id, company_id = entry.get("site"), entry.get("company")
        if site_id is not None:
            entry["site_name"] = sites.get(int(site_id))
        if company_id is not None:
            entry["company_name"] = companies.get(int(company_id))
