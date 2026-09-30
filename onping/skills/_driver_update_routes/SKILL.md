---
name: _driver_update_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, update.py) imported by the onping-update-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _driver_update_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs `routes.py` and `update.py`
into the synced skills root.

The 21 `onping-update-*` skills import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _driver_update_routes.routes import ROUTES
from _driver_update_routes.update import update_location
```

`routes.py` is the curated per-driver fetch/update endpoint + field table
(poll-time field, locked lumberjack/identity fields, fetch-body convention).
`update.py` is the shared read-modify-write helper that fetches the full config,
changes only allowlisted fields, refuses to touch lumberjack-binding/identity
fields, and POSTs the record back (with `--dry-run` / `--yes` safety).

Without this marker, the directory is dropped during sync and every
`onping-update-*` skill fails on import with `ModuleNotFoundError`. Keep the
marker; the catalog ID (`_driver_update_routes`) must equal the imported module
name. See the `skill-sync` capability spec, "Shared Helper Bundling via Marker
SKILL.md".
