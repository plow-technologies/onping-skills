"""Curated route definitions for the OnPing mqtt-json-INTEGRATOR endpoints.

This module is the single source of truth for the `onping-mqtt-integrator-*`
skill family. Each entry in `ROUTES` describes one `/mqtt/json/integrator/*`
route:

  - `endpoint`             — HTTP method + path with `{serial}` / `{filename}` placeholders
  - `handler`              — module path of the OnPing handler (traceability)
  - `path_params`          — placeholder name -> human description (or {} if none)
  - `request_content_type` — Content-Type the handler consumes (POST only)
  - `response`             — the response body shape / Content-Type
  - `mutating`             — True if the route changes state
  - `notes`                — anything non-obvious about the route

Schemas are HAND-CURATED from reading the Haskell in
`onping/Handler/MqttJsonIntegrator/` and the types in
`mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs`.
When routes change, re-verify against the recorded `handler` location.

WHAT THE INTEGRATOR IS. It is the automation layer ABOVE the mqtt-json driver,
not a replacement for it. You write rules; the integrator matches them against
live MQTT topic/message pairs and generates location + PID definitions, which it
then pushes into the mqtt-json driver. The driver skills
(`onping-{add,update,export,import}-mqtt-json`) operate one layer down, on
locations and parameters that already exist. Data flow:

    MQTT data -> Unprocessed -> [rules] -> Uncreated -> Created -> mqtt-json driver

Keyed by **LJSerial**, not by location refId — every stateful route is scoped to
one Lumberjack. This differs from the driver skills, which key on location id.

SIX GOTCHAS drive the skill design:

1. **Rules/artifacts import+export are XLSX, not JSON.** Both export handlers
   return `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
   The `{filename}` path segment is accepted and then IGNORED by the handler
   (same as `onping-export-mqtt-json`) — it exists only so browsers name the
   download. There is no JSON import route; to write rules you must build a
   spreadsheet.

2. **The multipart field name is `f1`, NOT `File`.** Both import handlers define
   their form as `renderDivs $ fileAFormReq "File"`. `"File"` is a LABEL;
   Yesod's `renderDivs` auto-generates the actual field NAME by position, so it
   is `f1`. Posting `File` yields `400 FormFailure`. Confirmed in the frontend:
   `src/OnpingFetch/OnpingFetch_ImportParameters.res`
   (`importFileBlob` does `ret.append("f1", blob)`). Same trap as the logtable
   and singlewell-manual imports.

3. **Rules import REPLACES ALL RULES.** `POST .../rules/import` routes to
   `postImportGenerationRules`, whose docstring reads "this overwrite any
   existing rules". Per the upstream `data-lifetime-and-uniqueness-rules.md`:
   "when you import it deletes everything and rebuilds the rule system from the
   excel file." Worse, `reconstructGenerationRules` re-derives every
   `LocationRuleIdentifier` / `PidRuleIdentifier` from ROW ORDER, so a
   round-trip renumbers all rule ids even when the content is unchanged. The
   sheet must contain every rule you intend to keep.

4. **`POST .../artifacts` is NOT the artifacts setter — it CREATES REAL OBJECTS.**
   Despite reading like a repsert, it takes a `CreateArtifacts` body and runs a
   five-stage pipeline: integrator step-one, then the mqtt-json driver's
   `addMqttJsonLocation`, then `addMqttJsonParameters`, then integrator
   step-two. It creates locations and parameters in OnPing. The idempotent
   record setter is `POST .../artifacts/import` (XLSX), which touches only the
   integrator's own store. Do not confuse them.

5. **`CreateArtifactsReport` returns HTTP 200 on PARTIAL OR TOTAL FAILURE.**
   Errors live in the `createLocationErrors` / `createPidErrors` arrays, not the
   status code. A naive `resp.ok` check reports success when nothing was
   created. Callers MUST inspect both arrays.

6. **Artifacts XLSX round-trip is LOSSY.** `Artifacts/ImportExport.hs` flattens
   `LocalParameterValue`: `localParameterTime` is dropped entirely (re-imported
   as `null`), and any value that does not match a known constructor falls back
   to `DoubleValue 0.0` / the string `"0.0"`. Export -> import is not identity.

JSON WIRE SHAPES — verified against the checked-in golden files at
`mqtt-json-integrator-types/golden/`,
NOT inferred. There are no custom aeson Options anywhere in `Types.hs`
(`grep unwrapUnaryRecords` is empty), so plain derived instances apply:

  * Sum types use aeson's default TaggedObject:
        {"tag": "BlacklistAddPid", "contents": {...}}
    A NULLARY constructor omits `contents` entirely:
        {"tag": "DeleteUncreatedAll"}
    A MULTI-ARG constructor makes `contents` a POSITIONAL ARRAY:
        {"tag": "RemovePidRule", "contents": [{"unLocationRuleIdentifier": 16},
                                              {"unPidRuleIdentifier": 9}]}

  * Record newtypes WRAP — they are not transparent:
        {"unLocationRuleIdentifier": 29}   {"unMqttRuleText": "..."}
        {"unPidType": "DoubleValueType"}   {"unJQSelectorText": "..."}
        {"unLocationUniqueIdentifier": "..."}
    `LocalTopic` DOUBLE-wraps: {"unLocalTopic": {"unTopic": "..."}}

  * These enums are BARE STRINGS (no tag object):
        LocalOnly           "LocalOnly" | "PushToRTUClient"
        ReadOnly            "ReadOnly"  | "Writeable"
        ExecuteRulesSource  "ExecuteRulesManual" | "ExecuteRulesAutomatic"

  * `TimeFormat` IS tagged: {"tag": "ISO"} | {"tag": "LumberjackTime"} |
    {"tag": "Format", "contents": "<fmt>"}

  * `PidUniqueIdentifier` is a two-field record, NOT a scalar — a PID is
    identified by its location key plus its source id:
        {"pidLocationUniqueIdentifier": {"unLocationUniqueIdentifier": "..."},
         "pidMqttJsonSourceId": {"mqttJsonSourceTopic": "...",
                                 "valueSelector": "..."}}

ENVELOPE: OnPing wraps handler results in `OnpingResponse` — an error is
`{"error": "..."}` and a success is the BARE payload, with no wrapper key
(`onping/OnpingResponse.hs`). A 200 carrying `{"error": ...}` is a
failure.

AUTH: `Authorization: Bearer <token>` from `onping-login` works on every route.
None of the integrator routes carry the `!` prefix in `config/routes`.

OUT OF SCOPE for this skill family: the five
`/mqtt/json/integrator/router/#LJSerial/address*` routes. Those register the
integrator server's host:port in the driver-switcher index — deployment
plumbing that belongs with `lj-deploy`, not with rule authoring. Note for
whoever picks them up: `POST .../address/update/auto` derives the address from
the LJ profile plus the `server-port` key of the installed
`mqtt-json-integrator-server` package config, and 404s when that package is
absent (`Handler/MqttJsonIntegrator/Service.hs`).
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net").rstrip("/")

TIMEOUT_SECONDS = 120

# The integrator create pipeline calls four services in sequence and the
# frontend warns it "can be a significant operation" for big requests, so the
# create route gets a longer budget than the default.
CREATE_TIMEOUT_SECONDS = 600

# The mqtt-json driver's parameter listener port on the Lumberjack. The OnPing
# frontend HARDCODES this when building a CreateArtifacts request
# (MqttJsonIntegrator_CreatableObjects.res). Mirrored here as the default so
# our skill matches UI behavior; overridable via --port.
DEFAULT_MQTT_JSON_PORT = 2000

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

_H = "onping/Handler/MqttJsonIntegrator/Service.hs"

ROUTES = {
    # ─────────────────────────────── config ────────────────────────────────
    "get_config": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/mqtt/config",
        "handler": f"{_H}:121 (getMqttJsonIntegratorMqttConfigR)",
        "path_params": {"serial": "LJSerial of the Lumberjack running the integrator"},
        "response": "MqttConfig JSON",
        "mutating": False,
        "notes": (
            "Broker string is expected to start with mqtt://. "
            "mqttConfigUnprocessedJsonObjectsSize is nullable — null means unlimited."
        ),
    },
    "post_config": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/mqtt/config",
        "handler": f"{_H}:126 (postMqttJsonIntegratorMqttConfigR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "application/json",
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "Whole-record PUT semantics: the handler does requireInsecureJsonBody "
            "on the full MqttConfig, so a partial body drops fields. Always "
            "read-modify-write via get_config."
        ),
    },
    # ──────────────────────────── generation rules ─────────────────────────
    "get_rules": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/generation/rules",
        "handler": f"{_H}:132 (getMqttJsonIntegratorGenerationRulesR)",
        "path_params": {"serial": "LJSerial"},
        "response": "[GenerationRule] JSON",
        "mutating": False,
        "notes": (
            "Each GenerationRule is {generationRuleLocation, generationRulePids}. "
            "This is the JSON read path; the XLSX read path is export_rules."
        ),
    },
    "post_rules": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/generation/rules",
        "handler": f"{_H}:137 (postMqttJsonIntegratorGenerationRulesR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "application/json",
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "Takes [UpdateGenerationRules] — a list of INCREMENTAL ops "
            "(RepsertLocationRule / RemoveLocationRule / RepsertPidRule / "
            "RemovePidRule), NOT a full rule set. This is the surgical "
            "alternative to import_rules, which replaces everything."
        ),
    },
    "execute_rules": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/generation/rules/execute",
        "handler": f"{_H}:265 (postMqttJsonIntegratorExecuteGenerationRulesR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": None,
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "No body. Runs all stored rules against all stored unprocessed data. "
            "Blocking and single-threaded server-side (the server refuses "
            "concurrent executions). Needed when "
            "mqttConfigExecuteRulesOnMessageReceive is False, or to reprocess "
            "without waiting for new MQTT traffic. Produces an ExecuteRulesReport "
            "readable via get_reports — the POST itself returns nothing useful."
        ),
    },
    "export_rules": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/rules/export/{filename}",
        "handler": f"{_H}:322 (getMqttJsonIntegratorExportRulesR)",
        "path_params": {
            "serial": "LJSerial",
            "filename": "IGNORED by the handler; any non-empty string works",
        },
        "response": f"XLSX bytes ({XLSX_CONTENT_TYPE})",
        "mutating": False,
        "notes": (
            "12-column generation-rule sheet. See rules_sheet.RULES_HEADERS. "
            "The handler discards the filename argument (`_`)."
        ),
    },
    "import_rules": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/rules/import",
        "handler": f"{_H}:304 (postMqttJsonIntegratorImportRulesR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "multipart/form-data",
        "response": "empty success envelope, or 400 with a JSON error string",
        "mutating": True,
        "notes": (
            "DESTRUCTIVE: replaces the ENTIRE rule set (gotcha 3) and renumbers "
            "all rule ids from row order. Multipart field is f1 (gotcha 2). "
            "Parse failures return 400 with the xlsx error as a JSON string."
        ),
    },
    # ───────────────────────────── rule parsing ────────────────────────────
    "parse_rule": {
        "endpoint": "POST /mqtt/json/integrator/rule/parse",
        "handler": f"{_H}:287 (postMqttJsonIntegratorParseRuleR)",
        "path_params": {},
        "request_content_type": "application/json",
        "response": 'RulesParseResult: {"tag":"ParsedRulesSuccesfully"} or '
        '{"tag":"FailedToParseRules","contents":"<err>"}',
        "mutating": False,
        "notes": (
            "NOT serial-scoped and completely stateless — validates a rule string "
            "only. Body is a bare JSON STRING (requireInsecureJsonBody :: Text), "
            "not an object. Accepts the full grammar: static text, "
            "{topic|s#pat#rep#} sed, and {jq} with template fields. "
            "NOTE the misspelling in the success tag: ParsedRulesSuccesfully. "
            "A parse failure is reported as HTTP 200 with the FailedToParseRules "
            "tag, not as a 4xx."
        ),
    },
    "parse_jq_rule": {
        "endpoint": "POST /mqtt/json/integrator/jq/rule/parse",
        "handler": f"{_H}:296 (postMqttJsonIntegratorParseJqRuleR)",
        "path_params": {},
        "request_content_type": "application/json",
        "response": "RulesParseResult (same shape as parse_rule)",
        "mutating": False,
        "notes": (
            "JQ-only variant (Rules.parseRuleJqOnly) — rejects the sed/topic "
            "forms that parse_rule accepts. Use for validating a PID Value or "
            "PID Time selector specifically."
        ),
    },
    # ────────────────────────────── unprocessed ────────────────────────────
    "get_unprocessed": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/unprocessed/data",
        "handler": f"{_H}:143 (getMqttJsonIntegratorUnprocessedDataR)",
        "path_params": {"serial": "LJSerial"},
        "response": "UnprocessedData JSON: {unprocessedJsonObjects, "
        "uncreatedLocations, uncreatedPids}",
        "mutating": False,
        "notes": (
            "unprocessedJsonObjects is a list of [topic, message] PAIRS "
            "(2-element arrays), stored as a set — one copy per exact "
            "topic+message pair. The uncreated* sets are what the rules have "
            "generated but not yet pushed to OnPing."
        ),
    },
    "export_unprocessed": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/unprocessed/data/export",
        "handler": f"{_H}:148 (getMqttJsonIntegratorExportUnprocessedDataR)",
        "path_params": {"serial": "LJSerial"},
        "response": "JSON file (application/json), Content-Disposition attachment",
        "mutating": False,
        "notes": (
            "Exports ONLY the unprocessedJsonObjects field, not the whole "
            "UnprocessedData record. Filename is fixed server-side as "
            "unprocessed-json-objects.json. There is NO import counterpart."
        ),
    },
    "delete_unprocessed": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/unprocessed/json/objects/delete",
        "handler": f"{_H}:270 (postMqttJsonIntegratorDeleteUnprocessedJsonObjectsR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": None,
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "No body, no choice — clears ALL stored unprocessed topic/message "
            "pairs unconditionally (the UI's 'Clear All Unprocessed'). Does not "
            "touch rules, uncreated, or created objects. Needed to resume "
            "ingestion once mqttConfigUnprocessedJsonObjectsSize is hit."
        ),
    },
    # ─────────────────────────────── artifacts ─────────────────────────────
    "get_artifacts": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/artifacts",
        "handler": f"{_H}:155 (getMqttJsonIntegratorArtifactsR)",
        "path_params": {"serial": "LJSerial"},
        "response": "Artifacts JSON: {storedLocations, storedPids}",
        "mutating": False,
        "notes": (
            "The integrator's record of what it believes it created. Data flow "
            "is one-way: the integrator CANNOT verify these still exist in "
            "OnPing or the driver, and does not trend their values — each "
            "storedPidValue is the value captured at rule-execution time."
        ),
    },
    "create_artifacts": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/artifacts",
        "handler": f"{_H}:162 (postMqttJsonIntegratorArtifactsR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "application/json",
        "response": "CreateArtifactsReport JSON",
        "mutating": True,
        "notes": (
            "THE REAL CREATE (gotcha 4) — five stages, creating live OnPing "
            "locations and mqtt-json parameters. Body is CreateArtifacts: "
            "{createArtifactsLocationUrl (the LJ's lumberjackUrl), "
            "createArtifactsLocationPort (frontend hardcodes 2000), "
            "createArtifactsLocations, createArtifactsPids}. Blacklisted items "
            "are filtered server-side in step one. RETURNS 200 EVEN ON TOTAL "
            "FAILURE (gotcha 5) — check createLocationErrors/createPidErrors."
        ),
    },
    "export_artifacts": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/artifacts/export/{filename}",
        "handler": f"{_H}:347 (getMqttJsonIntegratorExportArtifactsR)",
        "path_params": {
            "serial": "LJSerial",
            "filename": "IGNORED by the handler; any non-empty string works",
        },
        "response": f"XLSX bytes ({XLSX_CONTENT_TYPE})",
        "mutating": False,
        "notes": (
            "12-column artifacts sheet — a DIFFERENT schema from the rules "
            "sheet. See rules_sheet.ARTIFACTS_HEADERS. Lossy (gotcha 6)."
        ),
    },
    "import_artifacts": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/artifacts/import",
        "handler": f"{_H}:329 (postMqttJsonIntegratorImportArtifactsR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "multipart/form-data",
        "response": "empty success envelope, or 400 with a JSON error string",
        "mutating": True,
        "notes": (
            "Routes to postArtifacts — a repsert of the integrator's OWN record "
            "store. Creates NOTHING in OnPing or the driver. Its real use is "
            "suppression: recording an object as already-created stops the "
            "create pipeline from making it again. Multipart field is f1."
        ),
    },
    # ─────────────────────────────── blacklist ─────────────────────────────
    "get_blacklist": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/blacklist",
        "handler": f"{_H}:242 (getMqttJsonIntegratorBlacklistR)",
        "path_params": {"serial": "LJSerial"},
        "response": "Blacklist JSON: {blacklistLocationUniqueIdentifiers, "
        "blacklistPidUniqueIdentifiers}",
        "mutating": False,
        "notes": "Entries persist until removed; nothing expires them.",
    },
    "update_blacklist": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/blacklist",
        "handler": f"{_H}:247 (postMqttJsonIntegratorBlacklistR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "application/json",
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "Takes [UpdateBlacklist] — incremental ops, not a whole list: "
            "BlacklistAddPid / BlacklistRemovePid / BlacklistAddLocation / "
            "BlacklistRemoveLocation. Blacklisting only blocks CREATION; it "
            "does not delete anything already created."
        ),
    },
    # ──────────────────────────────── deletes ──────────────────────────────
    "delete_uncreated": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/uncreated/delete",
        "handler": f"{_H}:253 (postMqttJsonIntegratorUncreatedDeleteR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "application/json",
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "Body is DeleteUncreated: {'tag':'DeleteUncreatedAll'} or "
            "{'tag':'DeleteUncreatedByChoice','contents':{deleteUncreatedLocations,"
            "deleteUncreatedPids}}. Integrator-local only — affects neither "
            "OnPing nor the driver. Deleting a location cascades to its PIDs. "
            "Re-running the rules will regenerate anything deleted here unless "
            "it is also blacklisted."
        ),
    },
    "delete_stored": {
        "endpoint": "POST /mqtt/json/integrator/{serial}/stored/delete",
        "handler": f"{_H}:259 (postMqttJsonIntegratorStoredDeleteR)",
        "path_params": {"serial": "LJSerial"},
        "request_content_type": "application/json",
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "Body is DeleteStored: {'tag':'DeleteStoredAll'} or "
            "{'tag':'DeleteStoredByChoice','contents':{deleteStoredLocations,"
            "deleteStoredPids}}. Integrator-local: it FORGETS the record but "
            "does NOT delete the real OnPing location or driver parameter, "
            "which are left orphaned. Forgetting also un-suppresses creation, "
            "so the next create pass can make DUPLICATES."
        ),
    },
    # ──────────────────────────────── reports ──────────────────────────────
    "get_reports": {
        "endpoint": "GET /mqtt/json/integrator/{serial}/execute/rules/report",
        "handler": f"{_H}:275 (getMqttJsonIntegratorExecuteRulesReportsR)",
        "path_params": {"serial": "LJSerial"},
        "response": "[ExecuteRulesReport] JSON",
        "mutating": False,
        "notes": (
            "Each report: {executeRulesReportSource (bare string "
            "ExecuteRulesManual|ExecuteRulesAutomatic), "
            "executeRulesReportExecuteTime, executeRulesCount, "
            "executeRulesNewUncreatedLocationsCount, "
            "executeRulesNewUncreatedPidsCount, executeRulesErrors}. This is "
            "the ONLY place rule-execution errors surface — execute_rules "
            "itself returns an empty envelope."
        ),
    },
    "delete_reports": {
        "endpoint": "DELETE /mqtt/json/integrator/{serial}/execute/rules/report",
        "handler": f"{_H}:281 (deleteMqttJsonIntegratorExecuteRulesReportsR)",
        "path_params": {"serial": "LJSerial"},
        "response": "empty success envelope",
        "mutating": True,
        "notes": (
            "Clears ALL reports — no per-report delete exists. Note this route "
            "is a real HTTP DELETE; every other integrator mutation is a POST."
        ),
    },
}


def route(key: str) -> dict:
    """Look up a route entry by key, failing loudly on a typo."""
    try:
        return ROUTES[key]
    except KeyError:
        raise KeyError(
            f"unknown mqtt-json-integrator route {key!r}; "
            f"known routes: {', '.join(sorted(ROUTES))}"
        ) from None


def endpoint(key: str) -> str:
    """The 'METHOD /path' string for a route key."""
    return route(key)["endpoint"]
