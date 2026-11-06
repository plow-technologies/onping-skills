---
name: _token_input
description: Internal helper — do not invoke. Shared Python module (token_source.py) that the onping-hmi-* and onping-dashboard-* skills use to read the access token from the environment or stdin; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _token_input (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler, which only ships directories that
contain a `SKILL.md`, installs the module into the synced skills root.

The skills import it as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _token_input import token_source
args = token_source.parse(parser, argv, is_id=looks_like_my_id)
```

- `token_source.py` — `parse(parser, argv)` replaces `parser.parse_args(argv)`.
  It adds `--token-stdin`, takes the access token from `$ONPING_ACCESS_TOKEN`
  or stdin, and still accepts a token as the first word (deprecated, warns that
  `ps` shows it). `access_token` and `access_token_source` (a name, never the
  value) are set on the result. Usage failures exit 2 before any request and
  never carry the token. `is_id` marks first words that are ids of the calling
  skill family, so they are never read as a token. `stdin_busy` marks scripts
  that read their own input from stdin, where `--token-stdin` needs `--input`.

Without this marker, the directory is dropped during sync and the skills that
import it fail with `ModuleNotFoundError`. Keep the marker; the catalog ID
(`_token_input`) must equal the imported module name. See the `skill-sync`
capability spec, "Shared Helper Bundling via Marker SKILL.md".
