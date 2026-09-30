---
name: _mqtt_integrator_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, integrator_http.py, rules_sheet.py) imported by the onping-mqtt-integrator-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _mqtt_integrator_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs `routes.py`,
`integrator_http.py`, and `rules_sheet.py` into the synced skills root.

The `onping-mqtt-integrator-*` skills import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _mqtt_integrator_routes.routes import ROUTES, BASE_URL, endpoint
from _mqtt_integrator_routes.integrator_http import (
    get_json, get_bytes, post_json, post_empty, post_multipart_xlsx, delete,
    report_write,
)
from _mqtt_integrator_routes import rules_sheet
```

- `routes.py` — the `/mqtt/json/integrator/*` route table (single source of
  truth), `BASE_URL` (honors `ONPING_BASE_URL`), `TIMEOUT_SECONDS`,
  `CREATE_TIMEOUT_SECONDS`, and `DEFAULT_MQTT_JSON_PORT`. Each entry records the
  handler module path for traceability. Its docstring is the
  authoritative reference for the six behavioral gotchas and for the JSON wire
  shapes, which were verified against the checked-in golden files at
  `mqtt-json-integrator-types/golden/` rather than inferred.
- `integrator_http.py` — bearer-auth GET/POST/DELETE, a no-body POST, a
  multipart XLSX POST (field `f1`), and the auth-redirect / HTML-login
  fallthrough hardening shared by the whole OnPing skill family. Also
  `unwrap_envelope` / `report_write`, which reject the `{"error": ...}` body
  OnPing can return alongside a 200.
- `rules_sheet.py` — the two 12-column sheet schemas (generation rules and
  artifacts), their cell vocabularies, and `validate_row`, which reproduces the
  server's own row checks locally so a bad sheet is caught before the upload.

Without this marker, the directory is dropped during sync and every
`onping-mqtt-integrator-*` skill fails on import with `ModuleNotFoundError`.
Keep the marker; the catalog ID (`_mqtt_integrator_routes`) must equal the
imported module name. See the `skill-sync` capability spec, "Shared Helper
Bundling via Marker SKILL.md".

## Layer boundary

These routes drive the **mqtt-json integrator**, the rule-based automation layer
that generates locations and PIDs from live MQTT traffic. It sits *above* the
mqtt-json **driver**, which is covered by a separate, older skill family
(`onping-add-mqtt-json`, `onping-update-mqtt-json`,
`onping-export-mqtt-json`, `onping-import-mqtt-json`) and keys on location
refIds. Integrator routes key on **LJSerial**. Do not cross-wire the two.
