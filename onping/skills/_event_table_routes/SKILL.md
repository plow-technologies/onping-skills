---
name: _event_table_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, event_table_http.py, keys.py) imported by the onping-event-table-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _event_table_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs its modules into the synced
skills root.

The `onping-event-table-*` skills import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _event_table_routes.routes import ROUTES
from _event_table_routes.event_table_http import EventTableError, die, post_json, get_text
from _event_table_routes.keys import parse_key, bindings
```

- `routes.py` — the event-table and dashboard read routes (single source of
  truth), `BASE_URL` (honors `ONPING_BASE_URL`), `TIMEOUT_SECONDS`. Each entry
  records the handler `file:line` in onping for traceability.
- `event_table_http.py` — bearer-auth GET/POST helpers with the auth-redirect
  and HTML-login hardening shared by the OnPing skill family. Failures raise
  `EventTableError`, so a caller that reads many tables can report one failure
  and carry on. `die(err)` prints the error and exits 1.
- `keys.py` — the `OnpingKey` parser (a bare integer is a PID, an object
  carries `keyType`) and the flat bindings view of an `EventTableConfiguration`.

Without this marker, the directory is dropped during sync and every
`onping-event-table-*` skill fails on import with `ModuleNotFoundError`. Keep
the marker; the catalog ID (`_event_table_routes`) must equal the imported
module name.

## No per-table permission

Every `/event/table/*` route is open to any authenticated user in the `User`
group. No handler checks the caller's access to the table, its dashboard, or the
PIDs it reads, and no write route validates PIDs. The read skills add no exposure
beyond the UI. A future write skill must not assume that the server guards it.
