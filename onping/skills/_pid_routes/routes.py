"""Curated route definitions for OnPing PID lookup and PID value writes.

Single source of truth for the `onping-pid-locate` and `onping-pid-write`
skills. Each entry in `ROUTES` describes one route:

  - `endpoint`             — HTTP method + path
  - `handler`              — `file:line` of the handler in onping (traceability)
  - `request_content_type` — Content-Type the handler consumes
  - `request_body`         — the body shape
  - `success_status`       — the status the handler returns on success
  - `response`             — the response body shape
  - `notes`                — anything non-obvious about the route

Schemas are HAND-CURATED from reading the Haskell handlers under
`onping/Handler/` plus `onping-core` and `hmi-server`.
When routes change, re-verify against the recorded `handler` location.

FOUR THINGS DRIVE THE DESIGN OF THESE TWO SKILLS.

1. **`writeV2` trusts caller-supplied routing fields.** `postWriteDeviceV2R`
   rewrites only the username and forwards the rest; nothing re-derives
   `locationId` or `localParameterId` from `parameterId`. Downstream,
   `writeOnpingParameter'` dispatches on `(sourceId, result)` and hands the
   caller's `locationId` to whichever driver `sourceId` names. So a wrong
   `localParameterId` writes down the WRONG PROTOCOL DRIVER and a wrong
   `locationId` writes to ANOTHER LOCATION, both with a success status. This is
   why `write-onping-result` — which resolves both server-side from the PID — is
   the default route and `writeV2` is opt-in.

2. **Numeric writes pass through a per-PID WRITE MASK that can change the
   value.** `tagInfoListDefaultTransformResultWithWriteMask` looks up a
   configured script per PID and replaces the value with its output; on mask
   error it falls back to the unmasked value SILENTLY
   (`Persist/Mask.hs`). `OnPingText` and `OnPingBool` bypass masking
   entirely (`buildTag`, `hmi-server/.../Writes.hs`). A success status
   says the write was accepted, never what landed.

   The lister in this same table applies the READ mask
   (`ParameterLister.hs`) — a DIFFERENT configuration. So a read-back is an
   end-to-end round-trip check and cannot isolate either mask.

3. **The lister silently drops PIDs the caller cannot see.** `applyMask` keeps
   only tags whose `locationId` is in the caller's authorized-location map, with
   no marker emitted. Nonexistent, deleted, and unauthorized are therefore one
   indistinguishable outcome. Verified live 2026-08-21: `[99999999]` -> `[]`;
   `[500001, 99999999, 500002]` -> 2 items.

4. **Lister response order is NOT request order.** That same 3-PID request came
   back `[500002, 500001]`. Results MUST be keyed by `tagInfo.parameterId`; a
   positional zip would attribute one PID's location to another — and if that fed
   a `writeV2` envelope it would aim a write at the wrong location while
   reporting success.

5. **A BARE INTEGER MEANS `KeyPID`, so it cannot address a VPID — and getting
   this wrong produced a confident wrong answer about live equipment.**
   `FromJSON OnpingKey` falls back to `KeyPID` for any non-object
   (`Onping/Tag/Types.hs`). Until 2026-08-21 `lookup_pids` sent bare
   integers and `--vp` toggled only the option flags, so a VPID was asked for as
   a PID, matched nothing, fell into the not-found branch, and was reported as
   "does not exist, has been deleted, or belongs to a location this token cannot
   see" — ALL THREE FALSE for a VP updating every few minutes. That output was
   used to conclude the SAC/LLM control loop on four producing wells had been
   dead for 56 days; the loop was 3 hours fresh. Send TAGGED keys
   (`{"keyType": ..., "keyValue": n}`) for both kinds, and never let an
   un-addressable key inherit a note that asserts nonexistence.

   Corollary: this route returns a VP's description but NEVER its value — no
   option flag changes that (measured four-way sweep). VP values require the
   location-scoped `locate_by_location` query, so a VPID lookup costs TWO calls
   where a PID lookup costs one.

AUTH: `Authorization: Bearer <token>` from `onping-login` works on all three
routes; confirmed live for the lister. Every route here falls through to
`isInGroupList ["User"]` (`onping/Foundation.hs`).

WRITE PERMISSIONS are `ownedGroupsByUserId` — OWNED, which is stricter than the
read visibility the lister uses. A PID this tree can locate is not necessarily
one it can write. And a location in ZERO or 2+ groups is unwritable through any
of these routes regardless of the caller's rights (`Writes.hs`).
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 60

ROUTES: dict[str, dict] = {
    "locate": {
        "endpoint": "POST /json/listers/v3/parameters",
        "handler": "onping/Handler/JSON/Listers/ParameterLister.hs",
        "request_content_type": "application/json",
        "request_body": (
            "ParameterListerRequest — {preq_query: {tag: ParameterRequestOnpingKey, "
            "contents: [<pid>, ...]}, preq_optionVP, preq_optionVPCalculateResult, "
            "preq_optionExcludePID}"
        ),
        "success_status": 200,
        "response": (
            "JSON [TagInfoWithLocations] — [{tagInfo: {parameterId, locationId, "
            "companyId, siteId, localParameterId, description, unit, writeability, "
            "lastUpdate, result}, tagLocations: [{refId, name, slaveId, url, site, "
            "company, delete}]}]"
        ),
        "notes": (
            "A BARE INTEGER IN `contents` MEANS KeyPID — FromJSON OnpingKey falls "
            "back to it for any non-object (Onping/Tag/Types.hs) — so a bare "
            "integer CANNOT ADDRESS A VPID. Verified live 2026-08-21: "
            "`contents: [500109]` with preq_optionVP=true returned 0 items for a "
            "healthy VPID. Send tagged keys instead: "
            "`{\"keyType\": \"PID\"|\"VPID\", \"keyValue\": n}`. Explicit PID tagging "
            "returns a byte-identical item to a bare integer, and a MIXED batch "
            "resolves both kinds in one request, so tag everything unconditionally. "
            "THIS ROUTE NEVER COMPUTES A VP RESULT: a tagged VPID comes back with "
            "the right description but `result.tag OnPingNoData` / `value null` / "
            "`lastUpdate 0` under ALL FOUR combinations of "
            "preq_optionVPCalculateResult x preq_optionExcludePID (measured sweep). "
            "VP VALUES COME FROM `locate_by_location` BELOW. Missing PIDs are "
            "dropped silently and order is not preserved (see module docstring) — "
            "true for tagged requests too: [VPID 500109, PID 500006] returned "
            "[500006, 500109]. Duplicate PIDs collapse server-side. `tagLocations` "
            "is typed as a list but makeTagInfoWithLocations wraps exactly ONE "
            "location for a PID (ParameterLister.hs); the plural is "
            "SUPPOSED to be real for VPIDs, but every VPID measured so far "
            "(500101-500110) also returned exactly one. Numeric `result` values are "
            "READ-masked."
        ),
    },
    "locate_by_location": {
        "endpoint": "POST /json/listers/v3/parameters",
        "handler": "onping/Handler/JSON/Listers/ParameterLister.hs",
        "request_content_type": "application/json",
        "request_body": (
            "ParameterListerRequest — {preq_query: {tag: ParameterRequestLookupId, "
            "contents: {getLocationLookupList: [<locationId>, ...], "
            "getCompanyLookupList: [], getSiteLookupList: []}}, preq_optionVP: true, "
            "preq_optionVPCalculateResult: true, preq_optionExcludePID: true}"
        ),
        "success_status": 200,
        "response": "JSON [TagInfoWithLocations] — same item shape as `locate`",
        "notes": (
            "SAME PATH as `locate`, different query constructor. THE ONLY WAY TO GET "
            "A VP'S VALUE: the OnpingKey query above returns a VP's description but "
            "never its result. Verified live 2026-08-21: location 20002 returned all "
            "10 of its VPs WITH values (500109's operator message, 500103 = "
            "1037.130126953125). Two consequences. (1) It returns EVERY VP at the "
            "location, so a caller MUST filter to the ids actually requested — 10 "
            "came back for a request about 1. (2) preq_optionExcludePID=true makes "
            "it VP-ONLY, so plain PIDs must be sourced from the OnpingKey call; that "
            "is deliberate, and it is what keeps the plain-PID path untouched by "
            "this second request. Costs one extra call per distinct location, and "
            "only when VPIDs are requested."
        ),
    },
    "write": {
        "endpoint": "POST /source/param/write-onping-result",
        "handler": "onping/Handler/Source/Params.hs",
        "request_content_type": "application/json",
        "request_body": "JSON 2-tuple — [<pid>, <OnPingResult>]",
        "success_status": 201,
        "response": "JSON null on success; {\"error\": \"<text>\"} with 400 on failure",
        "notes": (
            "THE DEFAULT WRITE ROUTE. Looks the PID up server-side "
            "(getTagInfoByParameterId) and builds the TagInfo itself, hardcoding "
            "companyId/siteId to 0 and description/unit/lastUpdate to placeholders — "
            "which proves those fields are inert on the write path. Requires exactly "
            "one matching tag, else 400 'Failed to lookup parameter by pid before "
            "writing'. SUCCESS IS 201, NOT 200. Masks OnPingDouble/Int/Word16/32/64 "
            "(its explicit shouldApplyMask list, Params.hs); passes "
            "OnPingText/OnPingBool through unmasked."
        ),
    },
    "write_hmi": {
        "endpoint": "POST /hmi/devices/writeV2",
        "handler": "onping/Handler/Hmi/HmiViewer.hs",
        "request_content_type": "application/json",
        "request_body": (
            "WriteRequest — {reqWriteOtc: <full TagInfo>, reqWriteUsername: \"\"}"
        ),
        "success_status": 200,
        "response": "JSON [] on success; tagged HmiError with 500 on failure",
        "notes": (
            "OPT-IN ONLY (--via-hmi). Trusts caller routing fields — see module "
            "docstring point 1. Its one unique capability: writeOnpingParameter' has "
            "a SourceTotalFlow + OnPingText arm that writeOnpingParameter (V1) lacks "
            "entirely, so V2 is the only route that writes a STRING to a TotalFlow "
            "parameter; V1 falls through to 'incorrect protocol type'. That single "
            "arm is the ONLY behavioral difference between /hmi/devices/write and "
            "writeV2 (Writes.hs), hence no --v1 flag. `reqWriteUsername` is "
            "REQUIRED by the parser but DISCARDED — overwritten from the session at "
            "HmiViewer.hs — so it is always sent as \"\" and has no flag. "
            "FAILURES INCLUDING PERMISSION DENIALS ARRIVE AS 500, so status alone "
            "cannot classify them; read the HmiError tag chain."
        ),
    },
    # ── reference-only routes (used for --names enrichment) ──
    "sites": {
        "endpoint": "GET /json/listers/siteLister",
        "handler": "onping/Handler/JSON/Listers/SiteLister.hs",
        "success_status": 200,
        "response": "JSON [{key, value: {refId, name, cid, pull, delete}}]",
        "notes": (
            "Query param getCompanyLookupList=<companyId>. Only used by --names; the "
            "lister above returns a numeric site ref, not a name. Also wrapped by "
            "the onping-sites skill."
        ),
    },
    "companies": {
        "endpoint": "GET /json/listers/companyLister",
        "handler": "onping/Handler/JSON/Listers/CompanyLister.hs",
        "success_status": 200,
        "response": "JSON [{key, value: {refId, name, address, city, state, zip, delete}}]",
        "notes": "No params; returns the companies visible to the token. Only used by --names.",
    },
}

# ─────────────────────── OnPingResult value constructors ───────────────────────
#
# The 4 constructors these skills emit, of the 15 in
# Onping/Result/Types.hs. The other 11 are excluded deliberately:
# OnPingNaN / OnPingNoData / OnPingNotYetPolled / OnPingMaskUnit / OnPingLocal
# are STATES rather than values, and OnPingSource / OnPingEpoch /
# OnPingWord16/32/64 / OnPingDownHoleCard have no established write use through
# these routes.
#
# `masked` records whether a write of that constructor passes through the write
# mask. Text and bool short-circuit in `buildTag`
# (hmi-server/src/Hmi/Server/Services/Writes.hs) and are excluded from
# the source route's `shouldApplyMask` list (Source/Params.hs).
VALUE_TAGS: dict[str, dict] = {
    "double": {"tag": "OnPingDouble", "masked": True},
    "int": {"tag": "OnPingInt", "masked": True},
    "text": {"tag": "OnPingText", "masked": False},
    "bool": {"tag": "OnPingBool", "masked": False},
}

# ───────────────────── server error text -> what it means ─────────────────────
#
# Three messages read as something other than what they are. Each is surfaced
# verbatim AND translated; see the onping-pid-write spec.
ERROR_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    (
        "failed to lookup one group by LocationId",
        "The location belongs to ZERO or 2+ permission groups, so it cannot be "
        "written through any of these routes regardless of your rights "
        "(Writes.hs rejects it before the permission test). This is a "
        "configuration fact about the location, not a lookup bug.",
    ),
    (
        "insufficient permissions",
        "You do not OWN the location's permission group. Ownership "
        "(ownedGroupsByUserId) is stricter than the read visibility that let the "
        "lookup succeed — being able to locate a PID does not mean you can write it.",
    ),
    (
        "Failed to lookup parameter by pid before writing",
        "The PID does not exist, or it resolved to other than exactly one tag. "
        "The write route requires a unique match.",
    ),
    (
        "WriteErrorDoubleConversion",
        "The value could not be converted to a Double for a numeric write path — "
        "e.g. text sent to a numeric parameter (Onping/Result/Types.hs).",
    ),
    (
        "values are mismatched",
        "The value's type does not match the parameter's stored type — e.g. "
        "OnPingText sent to a parameter holding a ManualValueDouble. Verified live: "
        "the singlewell-manual driver rejects the mismatch itself with a 400, "
        "rather than the write reaching WriteErrorDoubleConversion. Check the "
        "parameter's current value tag (onping-pid-locate reports it) and use the "
        "matching value flag.",
    ),
    (
        "WriteErrorEmptyMasks",
        "The write mask produced no value, so NOTHING WAS WRITTEN.",
    ),
    (
        "problem occured applying write mask",
        "The write mask produced no value, so NOTHING WAS WRITTEN.",
    ),
    (
        "Parameter is not writable",
        "The driver refused the write based on its OWN STORED writeability. The "
        "writeability field you send is never consulted.",
    ),
    (
        "Parameter is read only",
        "The driver refused the write based on its OWN STORED writeability — "
        "verified live against a TagReadOnly modbus-flexible tag, which returned "
        "400 rather than being blocked client-side. This is the server enforcing "
        "read-only, not the writeability value in your request (which is ignored). "
        "onping-pid-locate reports writeability so you can see this coming.",
    ),
)


def translate_error(text: str) -> str | None:
    """Return a plain-language explanation for a known server error, else None.

    Callers MUST still surface the server's verbatim text — this only adds
    context, never replaces it.
    """
    for needle, explanation in ERROR_TRANSLATIONS:
        if needle in text:
            return explanation
    return None
