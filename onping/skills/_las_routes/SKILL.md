---
name: _las_routes
description: Internal helper — do not invoke. Shared Python module (LAS routes, HTTP with expired-token and las-server error unwrapping, ConfigType validation, CPassword masking, PackageConfig patch/compare/backup) imported by the lj-config-list, lj-config-export and lj-config-set skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _las_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs its modules into the synced
skills root.

The `lj-config-*` skills import it as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _las_routes import config_types as ct, configs as cf
from _las_routes.las_http import LASError, get_json
```

| Module | What it holds |
|--------|---------------|
| `routes.py` | The LAS routes the skills call (single source of truth): endpoint, role (Member or Owner), response, notes. `BASE_URL` honors `ONPING_BASE_URL`. |
| `las_http.py` | Bearer-auth `get_json` / `get_text` / `post_json` with the auth-redirect, HTML-login and 401 guards. Failures raise `LASError` (with `status` and, for a wrapped las-server error, `inner_status`). `unwrap_500` pulls las-server's status, message and trace ID out of OnPing's 500 body. |
| `config_types.py` | The `ConfigType` rules: `validate`, `from_cli` (text after `KEY=`), `type_name`, `mask` / `render` (CPassword shown as `********`), `same_value` (JSON equality that keeps booleans apart from numbers). |
| `configs.py` | Find a package; `build_patch` (values only, schema order and types kept); diff lines; read-back compare; the backup document and `restore_updates`; `write_private` (mode 0600, no overwrite without force); profile lookup and `safe_profile` (never returns `lumberjackPassword`). |

Unit tests (synthetic fixtures, no network). `tests/las_fakes.py` is the
in-memory fake of the routes that every lj-config-* test suite uses:

```bash
uv run --with pytest --with requests --with pyyaml pytest onping/skills/_las_routes/tests
```

Without this marker, the directory is dropped during sync and every dependent
skill fails on import with `ModuleNotFoundError`. Keep the marker; the catalog
ID (`_las_routes`) must equal the imported module name.
