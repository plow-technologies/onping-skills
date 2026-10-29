---
name: _lj_table_routes
description: Internal helper — do not invoke. Shared Python module (routes, HTTP, pointers, filters, data-table and log-table transforms, CLI flows) imported by the onping-datatable-* and onping-logtable-* primitive skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _lj_table_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs its modules into the synced
skills root.

The `onping-datatable-*` and `onping-logtable-{list,get,fetch,create,column-*,delete}`
skills import it as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _lj_table_routes import datatable as dt
from _lj_table_routes.lj_http import LJTableError, die
```

| Module | What it holds |
|--------|---------------|
| `routes.py` | Every Lumberjack data-table and log-table route the skills call (single source of truth): endpoint, handler function, request/response shape, permission, notes. `BASE_URL` honors `ONPING_BASE_URL`. |
| `lj_http.py` | Bearer-auth `get_json` / `post_json` with the auth-redirect, HTML-login, and `{"error": …}` guards. Failures raise `LJTableError`; `die(err)` prints a hint and exits 1. Named `lj_http` so it never shadows the standard library's `http`. |
| `pointers.py` | The PID/VPID pointer forms: a data-table cell is text (`"1234"`, `"1234 VPID"`), a log-table column key is JSON (`1234`, `{"keyType":"VPID","value":1234}`). Parsing is as strict as the server's `parsePointerFromText`. Selector names. |
| `filters.py` | Find and drop stored filter rules that reference a column. |
| `datatable.py` | TableSource reads, the row query (content + pointers joined on `tableRowId`), and pure transforms: add/delete a column, set cells, replace a pointer; read-back comparisons. |
| `logtable.py` | LogTableSource reads, schema-by-version, `validate_schema` (the server's `isValidSchema` plus position checks), `next_version` (build a v+1 `schema/upgrade` body), column mutators, create bodies, the row query, read-back comparisons. |
| `logtable_template.py` | The log-table column definitions `onping-logtable-create` accepts: the `--column NAME=SOURCE[:TAG]` parser, the `tagAsText` tag words, a reader for the four header rows of an export XLSX (as strict as the server's `parseXlsxColumnHeaderMultipleRows`; openpyxl is imported only there), and `build_schema`, which puts every column into one version-1 schema. |
| `mutate.py` | `--yes` / `--dry-run` / `--backup`, the preview gate, and the backup writer. |
| `cli.py` | Shared argument parsing, grids, and the two verified write flows: data-table `metadata/update` and log-table `schema/upgrade`. |

Unit tests (synthetic fixtures, no network):

```bash
uv run --with pytest --with requests --with openpyxl pytest onping/skills/_lj_table_routes/tests
```

Without this marker, the directory is dropped during sync and every dependent
skill fails on import with `ModuleNotFoundError`. Keep the marker; the catalog
ID (`_lj_table_routes`) must equal the imported module name.

## The mutating contract

Every write skill follows the same steps: read the stored record, apply a pure
transform, validate, print a BEFORE/AFTER preview, stop unless `--yes`
(`--dry-run` always wins), write a JSON backup, POST, re-read, and exit
non-zero on any mismatch between what was sent and what came back.
