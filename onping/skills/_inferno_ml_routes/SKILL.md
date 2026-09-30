---
name: _inferno_ml_routes
description: Internal helper — do not invoke. Shared Python module (inferno_ml_models.py) imported by the ml-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _inferno_ml_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs `inferno_ml_models.py` into the
synced skills root.

The `ml-*` skills import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _inferno_ml_routes.inferno_ml_models import (
    OnPingRequestError,
    emit_json,
    export_inference_params,
    list_inference_params,
    update_inference_param,
)
```

- `inferno_ml_models.py` — the `/inferno/ml/*` API layer: bearer-auth
  `_request` (3-attempt retry on 502/503/504, `allow_redirects=False`), model and
  model-version CRUD, model-card merging, and the inference-parameter helpers
  (list / get / with-sources / export / read-modify-write update). `BASE_URL`
  honors `ONPING_BASE_URL`. The comment block heading the inference section is
  the de-facto route table and records each route's request/response shape.

Dependent skills: `ml-parameter-export`, `ml-parameter-update`,
`ml-model-manage`, `ml-model-docs`, `ml-model-upload`.

## Why the marker, and why this name

Without this marker, the directory is dropped during sync and every `ml-*` skill
fails on import with `ModuleNotFoundError: No module named 'inferno_ml_models'`.
That was the state of the whole ML family until the `add-ml-parameter-export`
change: this directory was named `shared/` and carried no `SKILL.md`, so the
skills worked from a repo checkout and were broken in every synced skills root.

Two rules follow from the `skill-sync` capability spec, "Shared Helper Bundling
via Marker SKILL.md":

1. The catalog ID (`_inferno_ml_routes`) must equal the imported top-level module
   name. Keep them in sync if either is renamed.
2. Helpers install as **flat siblings** into one destination root shared by every
   provider, so the name must be `_`-prefixed and domain-scoped. A generic name
   like `shared` would squat a collision-prone top-level name — which is why this
   directory is no longer called that.

Import the inner module as a package attribute
(`from _inferno_ml_routes.inferno_ml_models import …`) after putting the skills
root on `sys.path`. Do **not** put this directory itself on `sys.path` to import
`inferno_ml_models` by bare name: that resolves in a checkout and fails after
sync, which is the exact defect this marker exists to prevent.

See also the sibling markers `_hmi_routes`, `_line_graph_routes`,
`_driver_export_routes`, `_driver_update_routes`, and `_driver_add_schemas`.
