"""Curated fetch+update route + field metadata for OnPing driver location updates.

This module is the single source of truth for the on-disk skill tree. Each entry
in `ROUTES` describes how to safely UPDATE one driver location's config by
read-modify-write: fetch the current full config, change only an allowlisted
field, and POST the whole record back.

  - `driver`          — kebab-case slug (matches the dict key)
  - `fetch_endpoint`  — POST path that returns the config in the SAME shape as
                        the update body (NOT a *Return / *LocationInfo view)
  - `update_endpoint` — POST path that parses the full config record
  - `response_group`  — "A" (handler returns config JSON directly / {"error":..})
                        or "B" (OnpingResponse wrapper; ToJSON unwraps to the
                        inner config, so the fetched body POSTs straight back)
  - `fetch_body`      — how to shape the fetch request body:
                          "tuple"    -> [refId, false]  (LocationIdRef, Bool);
                                        the False = pollImmediate (read stored
                                        config without hitting the device)
                          "refid"    -> bare LocationIdRef (int)
                          "ljserial" -> bare LJSerial (string)
  - `fetch_serial`    — bool; if True the fetch ALSO requires a `?serial=<LJSerial>`
                        query param (elynx, sitepro, tank-logix, toku)
  - `poll_field`      — exact JSON key (or DOTTED PATH into a nested object) of
                        the poll-time/poll-frequency field, in SECONDS; or None
                        for non-polling drivers (singlewell-manual, mqtt-json,
                        sparkplug-bridge)
  - `locked_fields`   — JSON keys / dotted paths that MUST NOT change: the
                        lumberjack-binding fields (routing keys) plus identity
                        keys. The update helper asserts each is byte-identical to
                        the fetched value before POSTing, and never lets the user
                        set them. Editing them via the normal update silently
                        desyncs routing (url/port drivers) or retargets the wrong
                        device (LJSerial drivers); moving a location to another
                        lumberjack is a separate switcher/router operation.
  - `safe_fields`     — extra non-poll JSON keys the skill MAY set (conservative;
                        empty by default until a key is verified safe per driver)
  - `handler`         — file:line of the update handler in onping (traceability)

KEY-NAME CAVEAT: these JSON keys are HAND-VERIFIED (2026-06-04) against the live
Haskell record JSON instances in onping and its type
packages. They are camelCase generic-derived keys. They intentionally DIFFER from
the snake_case keys in `_driver_add_schemas/schemas.py` for opc-ua / wellpilot /
unico / lufkin — the add-schema module's keys are wrong for those drivers; trust
THIS module for update operations. When Haskell types drift, re-verify against the
recorded `handler` location and update the matching entry here.

Several drivers (lufkin, osi-integration, elynx, sitepro, tank-logix, toku) nest
the poll field and/or LJSerial inside a `<driver>Config`/`<driver>Data` object;
those are expressed as DOTTED PATHS (e.g. "lufkinLocationV2.locInfoV2PollingFrequency").
The helper walks dotted paths for get/set/assert.

`osi-integration` and `lufkin` have NO lumberjack-address binding to lock
(osi binds by GUID asset; lufkin binds by its own url/port = the device address),
so their `locked_fields` is identity-only. Neither can "move lumberjack" via this
skill regardless.
"""

from __future__ import annotations

BASE_URL = "https://onping.plowtech.net"

ROUTES: dict[str, dict] = {
    # ───────────────────────── Group A (Handler Value) ─────────────────────────
    "bristol": {
        "driver": "bristol",
        "fetch_endpoint": "POST /bristol/location/fetch",
        "update_endpoint": "POST /bristol/location/update",
        "response_group": "A",
        "fetch_body": "tuple",
        "fetch_serial": False,
        "poll_field": "pollTime",
        "locked_fields": ["id", "refId", "lumberjackUrl", "lumberjackPort"],
        "safe_fields": [],
        "handler": "onping/Handler/Bristol/Service.hs",
    },
    "roc-tlp": {
        "driver": "roc-tlp",
        "fetch_endpoint": "POST /roc/tlp/location/fetch",
        "update_endpoint": "POST /roc/tlp/location/update",
        "response_group": "A",
        "fetch_body": "tuple",
        "fetch_serial": False,
        "poll_field": "pollTime",
        "locked_fields": ["id", "refId", "lumberjackUrl", "lumberjackPort"],
        "safe_fields": [],
        "handler": "onping/Handler/RocTlp/Service.hs",
    },
    "modbus-flexible": {
        "driver": "modbus-flexible",
        "fetch_endpoint": "POST /modbus/flexible/location/fetch",
        "update_endpoint": "POST /modbus/flexible/location/update",
        "response_group": "A",
        "fetch_body": "tuple",
        "fetch_serial": False,
        "poll_field": "pollTime",
        "locked_fields": ["id", "refId", "lumberjackUrl", "lumberjackPort"],
        "safe_fields": [],
        "handler": "onping/Handler/ModbusFlexible/Service.hs",
    },
    "control-logix": {
        "driver": "control-logix",
        "fetch_endpoint": "POST /control/logix/location/fetch",
        "update_endpoint": "POST /control/logix/location/update",
        "response_group": "A",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "pollTime",
        "locked_fields": ["id", "refId", "lumberjackUrl", "lumberjackPort"],
        "safe_fields": [],
        "handler": "onping/Handler/ControlLogix/Service.hs",
    },
    "total-flow": {
        "driver": "total-flow",
        "fetch_endpoint": "POST /total/flow/location/fetch",
        "update_endpoint": "POST /total/flow/location/update",
        "response_group": "A",
        "fetch_body": "tuple",
        "fetch_serial": False,
        "poll_field": "pollTime",
        "locked_fields": ["id", "refId", "lumberjackUrl", "lumberjackPort"],
        "safe_fields": [],
        "handler": "onping/Handler/TotalFlow/Service.hs",
    },
    "micrologix": {
        "driver": "micrologix",
        "fetch_endpoint": "POST /micrologix/location",
        "update_endpoint": "POST /micrologix/location/update",
        "response_group": "A",
        "fetch_body": "tuple",
        "fetch_serial": False,
        "poll_field": "pollTime",
        "locked_fields": ["locationId", "locationRefId", "url", "port"],
        "safe_fields": [],
        "handler": "onping/Handler/Micrologix/Service.hs",
    },
    "singlewell-manual": {
        "driver": "singlewell-manual",
        "fetch_endpoint": "POST /singlewellmanual/get/loc",
        "update_endpoint": "POST /singlewellmanual/location/update",
        "response_group": "A",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": None,  # manual entry — does not poll
        "locked_fields": ["id", "location_ref_id", "url", "port"],
        "safe_fields": [],
        "handler": "onping/Handler/SingleWellManual/Service.hs",
    },
    # ───────────────────── Group B (OnpingResponse wrapper) ─────────────────────
    "mqtt-json": {
        "driver": "mqtt-json",
        "fetch_endpoint": "POST /mqtt/json/location/fetch",
        "update_endpoint": "POST /mqtt/json/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": None,  # push driver — does not poll (handler hardcodes 60)
        "locked_fields": [
            "mqttLocMongoId",
            "mqttLocInfo.locInfoLocId",
            "mqttLocUrl",
            "mqttLocPort",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/MQTT/JSON/Service.hs",
    },
    "opc-ua": {
        "driver": "opc-ua",
        "fetch_endpoint": "POST /opc/ua/location/fetch",
        "update_endpoint": "POST /opc/ua/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "opcUaLocConfigPollFrequency",
        "locked_fields": [
            "opcUaLocConfigLocId",
            "opcUaLocConfigRefId",
            "opcUaLocConfigUrl",
            "opcUaLocConfigPort",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/OPC/UA/Service.hs",
    },
    "wellpilot": {
        "driver": "wellpilot",
        "fetch_endpoint": "POST /wellpilot/location/fetch",
        "update_endpoint": "POST /wellpilot/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "wellPilotConfigPollFrequency",
        "locked_fields": [
            "wellPilotConfigLocId",
            "wellPilotConfigRefId",
            "wellPilotConfigUrl",
            "wellPilotConfigPort",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/WellPilot/Service.hs",
    },
    "unico": {
        "driver": "unico",
        "fetch_endpoint": "POST /unico/location/fetch",
        "update_endpoint": "POST /unico/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "unicoConfigPollFrequency",
        "locked_fields": [
            "unicoConfigLocId",
            "unicoConfigRefId",
            "unicoConfigUrl",
            "unicoConfigPort",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/Unico/Service.hs",
    },
    "lufkin": {
        "driver": "lufkin",
        "fetch_endpoint": "POST /lufkin/location/fetch",
        "update_endpoint": "POST /lufkin/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "lufkinLocationV2.locInfoV2PollingFrequency",
        # No LJSerial; binds by its own url/port (= the device address). Lock identity only.
        "locked_fields": [
            "lufkinLocationV2Id",
            "lufkinLocationV2.locInfoV2LocationId",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/Lufkin/Service.hs",
    },
    "osi-integration": {
        "driver": "osi-integration",
        "fetch_endpoint": "POST /osi/integration/location/query",
        "update_endpoint": "POST /osi/integration/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "osiLocationConfig.osiLocationConfigPollFrequency",
        # No lumberjack address — OSI binds by GUID asset. Lock identity only.
        "locked_fields": ["osiLocationId", "osiLocationRefId"],
        "safe_fields": [],
        "handler": "onping/Handler/Osi/Integration/Service.hs",
    },
    "hazard-pro": {
        "driver": "hazard-pro",
        "fetch_endpoint": "POST /hazard/pro/location/query",
        "update_endpoint": "POST /hazard/pro/location/update",
        "response_group": "B",
        "fetch_body": "tuple",
        "fetch_serial": False,
        "poll_field": "hazardProConfigPollFrequency",
        "locked_fields": [
            "hazardProConfigLocId",
            "hazardProConfigRefId",
            "hazardProConfigUrl",
            "hazardProConfigPort",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/Hazard/Pro/Service.hs",
    },
    "lumberjack-remote": {
        "driver": "lumberjack-remote",
        "fetch_endpoint": "POST /lumberjack/remote/lookup",
        "update_endpoint": "POST /lumberjack/remote/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "remoteConfigPollFrequency",
        "locked_fields": [
            "remoteConfigLocId",
            "remoteConfigRefId",
            "remoteConfigUrl",
            "remoteConfigPort",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/LumberjackRemote/Service.hs",
    },
    "elynx": {
        "driver": "elynx",
        "fetch_endpoint": "POST /elynx/integration/location/fetch",
        "update_endpoint": "POST /elynx/integration/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": True,
        "poll_field": "elynxLocationData.elynxLocationDataPollFrequency",
        "locked_fields": [
            "elynxLocationLocationId",
            "elynxLocationData.elynxLocationDataId",
            "elynxLocLJSerial",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/ElynxIntegration/Service.hs",
    },
    "sitepro": {
        "driver": "sitepro",
        "fetch_endpoint": "POST /sitepro/location/query",
        "update_endpoint": "POST /sitepro/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": True,
        "poll_field": "siteproLocationConfig.siteproLocationConfigPollFrequency",
        "locked_fields": [
            "siteproLocationRefId",
            "siteproLocationConfig.siteproLocationConfigLJSerial",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/Sitepro/Service.hs",
    },
    "tank-logix": {
        "driver": "tank-logix",
        "fetch_endpoint": "POST /tank-logix/location/query",
        "update_endpoint": "POST /tank-logix/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": True,
        "poll_field": "tankLogixLocationConfig.tankLogixLocationConfigPollFrequency",
        "locked_fields": [
            "tankLogixLocationRefId",
            "tankLogixLocationConfig.tankLogixLocationConfigLJSerial",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/TankLogix/Service.hs",
    },
    "toku": {
        "driver": "toku",
        "fetch_endpoint": "POST /toku/location/query",
        "update_endpoint": "POST /toku/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": True,
        "poll_field": "tokuLocationConfig.tokuLocationConfigPollFrequency",
        "locked_fields": [
            "tokuLocationRefId",
            "tokuLocationConfig.tokuLocationConfigLJSerial",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/Toku/Service.hs",
    },
    "dnp3": {
        "driver": "dnp3",
        "fetch_endpoint": "POST /dnp3/location/fetch",
        "update_endpoint": "POST /dnp3/location/update",
        "response_group": "B",
        "fetch_body": "refid",
        "fetch_serial": False,
        "poll_field": "dnp3ConfigPollingRate",
        "locked_fields": [
            "dnp3ConfigLocId",
            "dnp3ConfigRefId",
            "dnp3ConfigServerUrl",
            "dnp3ConfigServerPort",
        ],
        "safe_fields": [],
        "handler": "onping/Handler/DNP3/Service.hs",
    },
    "sparkplug-bridge": {
        "driver": "sparkplug-bridge",
        "fetch_endpoint": "POST /sparkplug/bridge/query",
        "update_endpoint": "POST /sparkplug/bridge/update",
        "response_group": "B",
        "fetch_body": "ljserial",  # bare LJSerial; serial IS the identity
        "fetch_serial": False,
        "poll_field": None,  # bridge — does not poll
        "locked_fields": ["sparkplugConfigLJSerial"],
        "safe_fields": [],
        "handler": "onping/Handler/SparkplugBridge/Service.hs",
    },
}
