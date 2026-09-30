---
name: _pid_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, pid_http.py) imported by onping-pid-locate and onping-pid-write; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _pid_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs `routes.py` and `pid_http.py`
into the synced skills root.

`onping-pid-locate` and `onping-pid-write` import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _pid_routes.routes import ROUTES, VALUE_TAGS, translate_error
from _pid_routes.pid_http import lookup_pids, lookup_one, post_json, resolve_names

lookup_pids(token, [500001])                  # PIDs, one request
lookup_pids(token, [], vpids=[500109])        # VPIDs — tagged keys + value fetch
lookup_pids(token, [500006], vpids=[500109])  # mixed, both kinds in one request
lookup_one(token, 500001)                     # single PID; as_vpid=True for a VPID
```

**Ids must be declared by kind, because a bare integer means `KeyPID`.** The
request sends tagged `{"keyType","keyValue"}` keys for both kinds; an id in
`vpids` is addressed as a VPID, everything in the first argument as a PID.
Passing an id as the wrong kind yields an explicit *not addressable* entry rather
than a claim that it does not exist.

- `routes.py` — the route table for the PID lookup, the location-scoped VP-value
  lookup, and both write routes (single source of truth), the four emittable
  `OnPingResult` constructors and whether each is write-masked, the server-error
  translation table, `BASE_URL` (honors `ONPING_BASE_URL`), and
  `TIMEOUT_SECONDS`. Each entry records the handler `file:line` in onping for
  traceability.
- `pid_http.py` — bearer-auth POST/GET with the auth-redirect and HTML-login
  fallthrough hardening shared by the whole OnPing skill family, plus the PID
  lookup itself.

**Changing `lookup_pids` reaches a skill that writes to physical equipment.** Any
edit here must keep the plain-PID path byte-identical: `onping-pid-write`'s
dry-run resolution, its `--verify` read-back, and its `--via-hmi` envelope all
run through this one function, and the envelope is built from it precisely so a
caller cannot mis-target a write. Capture a plain-PID baseline before editing —
a regression here can aim a write at the wrong location while reporting success.
`lookup_one(token, pid)` must stay positional and PID-only by default for the
same reason.

**Why the lookup lives here rather than in the locate skill.** Three callers need
it and they must agree: `onping-pid-locate` (the whole skill), `onping-pid-write
--verify` (the read-back), and `onping-pid-write --via-hmi` (which builds the
`writeV2` envelope from the live lookup instead of user-supplied routing fields).
If those drifted, `--via-hmi` could send an envelope inconsistent with what
`locate` reports — the mis-targeting failure the default write route exists to
prevent.

Without this marker, the directory is dropped during sync and both skills fail on
import with `ModuleNotFoundError`. Keep the marker; the catalog ID (`_pid_routes`)
must equal the imported module name. See the `skill-sync` capability spec,
"Shared Helper Bundling via Marker SKILL.md".
