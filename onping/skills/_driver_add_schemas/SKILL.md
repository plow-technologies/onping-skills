---
name: _driver_add_schemas
description: Internal helper — do not invoke. Shared Python module (schemas.py) imported by the onping-add-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _driver_add_schemas (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs `schemas.py` into the synced
skills root.

The 21 `onping-add-*` skills import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _driver_add_schemas.schemas import SCHEMAS
```

Without this marker, the directory is dropped during sync and every
`onping-add-*` skill fails on import with `ModuleNotFoundError`. Keep the
marker; the catalog ID (`_driver_add_schemas`) must equal the imported module
name. See the `skill-sync` capability spec, "Shared Helper Bundling via Marker
SKILL.md".
