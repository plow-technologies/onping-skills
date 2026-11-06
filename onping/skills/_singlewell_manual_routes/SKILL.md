---
name: _singlewell_manual_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, swm_http.py) imported by onping-create-singlewell-manual and onping-delete-singlewell-manual; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _singlewell_manual_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs its modules into the synced
skills root.

`onping-create-singlewell-manual` and `onping-delete-singlewell-manual` import
it as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _singlewell_manual_routes import routes as R
from _singlewell_manual_routes import swm_http as H
```

| Module | What it holds |
|--------|---------------|
| `routes.py` | The singlewell-manual add, get, list and delete routes, the ownership, LAS profile and site-lister reads, the server's `get/loc` error messages, the add route's step order with the records each failure leaves, and what a delete removes and leaves. `BASE_URL` honors `ONPING_BASE_URL`. |
| `swm_http.py` | Bearer-auth transport with the auth-redirect and HTML-login guards. Reads raise `RouteFailure`. `post_once` sends a write exactly once and returns a `WriteResult` (a lost response is "sent", not "failed"). `read_location` classifies one `get/loc` answer as present, missing, partial or unknown, for both skills. `classify_add_failure` parses a 500 into its step, its LocationIdRef and its residue. |

The tests live with the two skills that use the module:

```bash
uv run --with pytest --with requests pytest onping/skills/onping-create-singlewell-manual/tests onping/skills/onping-delete-singlewell-manual/tests
```

Without this marker, the directory is dropped during sync and both dependent
skills fail on import with `ModuleNotFoundError`. Keep the marker; the catalog
ID (`_singlewell_manual_routes`) must equal the imported module name.
