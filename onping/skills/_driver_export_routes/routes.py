"""Curated GET-route definitions for OnPing driver tag-export endpoints.

This module is the single source of truth for the on-disk skill tree. Each
entry in `ROUTES` describes one driver's "export tags to Excel" GET route:

  - `endpoint`     — HTTP method + path with `{placeholders}`
  - `handler`      — `file:line` of the handler in onping (traceability)
  - `path_params`  — placeholder name -> human description
  - `content_type` — declared response Content-Type (see CAVEATS below)
  - `variants`     — alternate routes (v1, cards, all, …) when present

Schemas are HAND-CURATED from reading the Haskell handlers under
`onping/Handler/<Driver>/ImportExport.hs` (or
`Service.hs`). When routes change, re-verify against the recorded `handler`
location and update the matching entry. All per-driver `export_tags.py`
scripts read from this dict; nothing else should redefine routes inline.

CAVEATS:
- Several handlers declare Content-Type `text/csv` while actually returning
  XLSX bytes (an OnPing handler quirk). The downloader treats the body as
  opaque binary regardless, so the local file is a real `.xlsx`.
- The `#String` second path param is documented in handler comments as a
  filename for `Content-Disposition`, but several handlers ignore it
  (pattern-match `_`). Pass any non-empty string (e.g. `tags.xlsx`).
- The `#Int` first path param is a `LocationIdRef` for most drivers, but
  for `sparkplug-bridge` it is an `LJSerial` (Lumberjack serial).
"""

from __future__ import annotations

ROUTES: dict[str, dict] = {
    "micrologix": {
        "driver": "micrologix",
        "endpoint": "GET /micrologix/export/params/{location_id}/{filename}",
        "handler": "onping/Handler/Micrologix/ImportExport.hs",
        "path_params": {
            "location_id": "int (LocationIdRef) — OnPing location for the Micrologix device",
            "filename": "string — handler ignores this (any non-empty token works, e.g. 'tags.xlsx')",
        },
        "content_type": "text/csv (handler quirk; body is real XLSX)",
    },
    "roc-tlp": {
        "driver": "roc-tlp",
        "endpoint": "GET /roc/tlp/export/params/{location_id}/{filename}",
        "handler": "onping/Handler/RocTlp/ImportExport.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — handler ignores this",
        },
        "content_type": "text/csv (handler quirk; body is real XLSX)",
    },
    "modbus-flexible": {
        "driver": "modbus-flexible",
        "endpoint": "GET /modbus/flexible/export/params/{location_id}/{filename}",
        "handler": "onping/Handler/ModbusFlexible/ImportExport.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — handler ignores this",
        },
        "content_type": "text/csv (handler quirk; body is real XLSX)",
    },
    "control-logix": {
        "driver": "control-logix",
        "endpoint": "GET /control/logix/params/export/{location_id}/{filename}",
        "handler": "onping/Handler/ControlLogix/ImportExport.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — handler ignores this",
        },
        "content_type": "text/csv (handler quirk; body is real XLSX)",
        "notes": "Path order differs from siblings: '/params/export/' not '/export/params/'.",
    },
    "total-flow": {
        "driver": "total-flow",
        "endpoint": "GET /total/flow/export/params/{location_id}/{filename}",
        "handler": "onping/Handler/TotalFlow/ImportExport.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — handler ignores this",
        },
        "content_type": "text/csv (handler quirk; body is real XLSX)",
    },
    "singlewell-manual": {
        "driver": "singlewell-manual",
        "endpoint": "GET /v2/singlewellmanual/export/params/{location_id}/{filename}",
        "handler": "onping/Handler/SingleWellManual/ImportExportV2.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — handler ignores this",
        },
        "content_type": "text/csv (handler quirk; body is real XLSX)",
        "variants": {
            "v1": {
                "endpoint": "GET /singlewellmanual/export/params/{location_id}/{filename}",
                "handler": "onping/Handler/SingleWellManual/ImportExport.hs",
                "path_params": {
                    "location_id": "int (LocationIdRef)",
                    "filename": "string — handler ignores this",
                },
                "content_type": "text/csv (handler quirk; body is real XLSX)",
                "notes": "V1 filters parameters to ManualValueDouble / ManualValueAsciiText24 / NaNTagValue only.",
            },
        },
    },
    "mqtt-json": {
        "driver": "mqtt-json",
        "endpoint": "GET /mqtt/json/param/export/{location_id}/{filename}",
        "handler": "onping/Handler/MQTT/JSON/Service.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — used in Content-Disposition",
        },
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "variants": {
            "all": {
                "endpoint": "GET /mqtt/json/param/export/all",
                "handler": "onping/Handler/MQTT/JSON/Service.hs",
                "path_params": {},
                "content_type": "application/json",
                "notes": "Developer-only; gated by MqttJsonDumpParametersFlag feature flag. Returns a JSON dump of all ungrouped locations' parameters, NOT XLSX.",
            },
        },
    },
    "opc-ua": {
        "driver": "opc-ua",
        "endpoint": "GET /opc/ua/param/export/{location_id}/{filename}",
        "handler": "onping/Handler/OPC/UA/Service.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — used in Content-Disposition",
        },
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "wellpilot": {
        "driver": "wellpilot",
        "endpoint": "GET /wellpilot/param/export/{location_id}/{filename}",
        "handler": "onping/Handler/WellPilot/Service.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — used in Content-Disposition",
        },
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "variants": {
            "cards": {
                "endpoint": "GET /wellpilot/card/export/{location_id}/{filename}",
                "handler": "onping/Handler/WellPilot/Service.hs",
                "path_params": {
                    "location_id": "int (LocationIdRef)",
                    "filename": "string — used in Content-Disposition",
                },
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "notes": "Exports pump cards (downhole card configs) instead of tag parameters.",
            },
        },
    },
    "sparkplug-bridge": {
        "driver": "sparkplug-bridge",
        "endpoint": "GET /sparkplug/bridge/export/{lumberjack_serial}/{filename}",
        "handler": "onping/Handler/SparkplugBridge/ImportExport.hs",
        "path_params": {
            "lumberjack_serial": "int (LJSerial) — Lumberjack serial number, NOT a location ID",
            "filename": "string — used in Content-Disposition",
        },
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "notes": "Outlier: keyed by Lumberjack serial, not LocationIdRef. Endpoint is /sparkplug/bridge/export/, not /location/export/.",
    },
    "lumberjack-remote": {
        "driver": "lumberjack-remote",
        "endpoint": "GET /lumberjack/remote/export-v2/params/{location_id}/{filename}",
        "handler": "onping/Handler/LumberjackRemote/ImportExport.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — used in Content-Disposition",
        },
        "content_type": "text/csv (handler quirk; body is real XLSX)",
        "notes": "V2 follows RocTlp pattern: converts parameters to LJRemoteItems before export.",
        "variants": {
            "v1": {
                "endpoint": "GET /lumberjack/remote/export/params/{location_id}/{filename}",
                "handler": "onping/Handler/LumberjackRemote/ImportExport.hs",
                "path_params": {
                    "location_id": "int (LocationIdRef)",
                    "filename": "string — used in Content-Disposition",
                },
                "content_type": "text/csv (handler quirk; body is real XLSX)",
            },
        },
    },
    "dnp3": {
        "driver": "dnp3",
        "endpoint": "GET /dnp3/export/params/{location_id}/{filename}",
        "handler": "onping/Handler/DNP3/ImportExport.hs",
        "path_params": {
            "location_id": "int (LocationIdRef)",
            "filename": "string — used in Content-Disposition",
        },
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
}
