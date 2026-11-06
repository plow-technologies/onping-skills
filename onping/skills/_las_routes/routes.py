"""Curated LAS (Lumberjack Application System) routes for the lj-config-* skills.

OnPing serves `/las/api/v1/*` itself (onping `Handler/LAS/Service.hs`): it
checks the caller's group for the serial, then calls las-server, which holds a
RON CRDT replica of every Lumberjack's LAS data and syncs it to the device's
las-local over the MQTT bridge.

Each `ROUTES` entry gives:
  - `endpoint`  — HTTP method + path (the serial is always the `serial` query param)
  - `role`      — the group role OnPing checks: "Member" or "Owner"
  - `response`  — the success body
  - `notes`     — anything non-obvious

PERMISSIONS: a missing or malformed serial is 400. A failed group check is
403 with the bare JSON string "User is not authorized to access Lumberjack".
The `profiles` list is filtered to the caller's OWNED groups, so a serial in it
is one the caller may write.

ERRORS FROM las-server reach the caller as OnPing's HTTP 500
`{"error": "<shown Haskell exception>"}`; `las_http.unwrap_500` pulls the inner
status and message out of it.

VERIFIED LIVE on 2026-10-28, read-only, against the test Lumberjack: profiles,
configs, configs/export (200, a missing package, no package), is-storage-synced
and is-mqtt-bridge-up.
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 60

_H = "onping/Handler/LAS/Service.hs"

ROUTES: dict[str, dict] = {
    "profiles": {
        "endpoint": "GET /las/api/v1/lumberjack/profiles",
        "handler": f"{_H} (profiles GET)",
        "role": "Owner",
        "response": "JSON [[serial, LumberjackProfile]] for the caller's OWNED groups",
        "notes": (
            "Large (about 1 MB for an admin) and slow (seconds). Each profile carries "
            "lumberjackPassword, a bcrypt hash: never print it."
        ),
        "timeout": 180,
    },
    "configs": {
        "endpoint": "GET /las/api/v1/lumberjack/configs",
        "handler": f"{_H} (getLasLumberjackConfigsR)",
        "role": "Member",
        "response": (
            "JSON [PackageConfig]; PackageConfig = {pkgConfName, pkgConfMonitorName, "
            "pkgConfPath, pkgConfSchema: [{configKey, configType, configValue}]}"
        ),
        "notes": "No configs for the serial -> 500 wrapping las-server's 404.",
    },
    "configs_post": {
        "endpoint": "POST /las/api/v1/lumberjack/configs",
        "handler": f"{_H} (postLasLumberjackConfigsR) -> las-server postConfigs",
        "role": "Owner",
        "request": "one PackageConfig",
        "response": "200, empty body",
        "notes": (
            "las-server finds the stored entry by pkgConfName and REPLACES its whole "
            "pkgConfSchema (path and monitor are kept). It checks neither keys nor "
            "types, and never consults the bridge. On the device, las-local rewrites "
            "the YAML and restarts pkgConfMonitorName only when the config changed."
        ),
    },
    "configs_export": {
        "endpoint": "GET /las/api/v1/lumberjack/configs/export",
        "handler": f"{_H} (configs/export GET, Owner check)",
        "role": "Owner",
        "response": "text/plain flat YAML `key: value`, keys sorted",
        "notes": (
            "Needs `package`; without it -> 400 \"Missing 'package' query param\". "
            "Unknown package -> 500 wrapping las-server's 404."
        ),
    },
    "storage_synced": {
        "endpoint": "GET /las/api/v1/is-storage-synced",
        "handler": f"{_H} -> las-server areAllEntitiesSynced",
        "role": "Member",
        "response": "JSON bool: lastAcked >= lastSaved for the serial's RON partition",
        "notes": "False between a save and the device's acknowledgement.",
    },
    "bridge_up": {
        "endpoint": "GET /las/api/v1/is-mqtt-bridge-up",
        "handler": f"{_H} -> las-server BridgeStateMonitor",
        "role": "Member",
        "response": "JSON bool or null",
        "notes": (
            "Answered from the cloud broker's $SYS bridge state, which the cloud does "
            "not have for device-side bridges: it was null for a live, synced "
            "Lumberjack. Informational only; never used to decide."
        ),
    },
}
