---
name: _generic_swd_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, model.py, guard.py, cli.py) imported by onping-generic-swd-list, onping-generic-swd-get and onping-generic-swd-update; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _generic_swd_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module. The `agent-skills-nix`
bundler only ships directories that contain a `SKILL.md`, so this marker
installs the module into the synced skills root, where the three
`onping-generic-swd-*` scripts import it as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _generic_swd_routes import cli, guard, model, routes
```

- `routes.py` — the generic-SWD routes the skills use (kiosk list, kiosk
  configuration, live lane states, recent tickets, and the lane update), the
  permission reads, and the transport. It imports the PID lookup from
  `_pid_routes`.
- `model.py` — reduces a kiosk configuration to its stored fields, validates
  it, applies one edit, prints the diff, and reads and writes backup files.
- `guard.py` — the ownership checks: the kiosk must be in one of your groups to
  read it, and in a group you own to change it; every PID a change adds must
  pass OnPing's PID-write rule. The server checks group access on each kiosk
  route too (HTTP 403 otherwise); this guard runs first and is stricter for
  changes, because it needs ownership, not membership.
- `cli.py` — the shared exit codes (0 to 4) and output helpers.

Keep the marker; the catalog ID (`_generic_swd_routes`) must equal the imported
module name.
