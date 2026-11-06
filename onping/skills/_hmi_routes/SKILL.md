---
name: _hmi_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, hmi_http.py, hmi_args.py) imported by the onping-hmi-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _hmi_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs `routes.py`, `hmi_http.py` and `hmi_args.py`
into the synced skills root.

The `onping-hmi-*` skills import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _hmi_routes.routes import ROUTES, BASE_URL
from _hmi_routes.hmi_http import get_dhall, get_json, post_dhall, post_json, delete
from _hmi_routes.hmi_args import parse
```

- `routes.py` — the `/hmi/*` route table (single source of truth), `BASE_URL`
  (honors `ONPING_BASE_URL`), and `TIMEOUT_SECONDS`. Each entry records the
  handler `file:line` in onping for traceability.
- `hmi_http.py` — bearer-auth GET/POST/DELETE helpers with the auth-redirect and
  HTML-login fallthrough hardening shared by the whole OnPing skill family.
- `hmi_args.py` — `parse(p, argv, uuid=..., reads_stdin=...)` replaces
  `p.parse_args()` in every HMI script. The access token comes from
  `$ONPING_ACCESS_TOKEN` or `--token-stdin` (via the shared `_token_input`
  helper), never from a required argument; a UUID-shaped first word is never
  read as a legacy token, and the `uuid` positional must be UUID-shaped
  (exit 2 before any request).

Without this marker, the directory is dropped during sync and every
`onping-hmi-*` skill fails on import with `ModuleNotFoundError`. Keep the marker;
the catalog ID (`_hmi_routes`) must equal the imported module name. See the
`skill-sync` capability spec, "Shared Helper Bundling via Marker SKILL.md".
