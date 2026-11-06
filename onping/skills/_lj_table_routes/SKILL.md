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
| `lj_http.py` | Bearer-auth `get_json` / `post_json` / `post_bytes` / `post_multipart` (fields `f1` file, `f2` table UUID) with the auth-redirect, HTML-login, and `{"error": …}` guards. Failures raise `LJTableError` (`RateLimited` on 429, exit 6; `ForbiddenRoute` for a route marked `forbidden`, which is never sent); `die(err)` prints a hint and exits 1. Named `lj_http` so it never shadows the standard library's `http`. |
| `pointers.py` | The PID/VPID pointer forms: a data-table cell is text (`"1234"`, `"1234 VPID"`), a log-table column key is JSON (`1234`, `{"keyType":"VPID","value":1234}`). Parsing is as strict as the server's `parsePointerFromText`. Selector names. |
| `filters.py` | Find and drop stored filter rules that reference a column. |
| `datatable.py` | TableSource reads, the row query (content + pointers joined on `tableRowId`), and pure transforms: add/delete a column, set cells, replace a pointer; read-back comparisons. |
| `logtable.py` | LogTableSource reads, schema-by-version, `validate_schema` (the server's `isValidSchema` plus position checks), `next_version` (build a v+1 `schema/upgrade` body), column mutators, create bodies, the row query, read-back comparisons. |
| `logtable_template.py` | The log-table column definitions `onping-logtable-create` accepts: the `--column NAME=SOURCE[:TAG]` parser, the `tagAsText` tag words, a reader for the four header rows of an export XLSX (as strict as the server's `parseXlsxColumnHeaderMultipleRows`; openpyxl is imported only there), and `build_schema`, which puts every column into one version-1 schema. |
| `datatable_rows.py` | Row helpers for the row, create, import and export skills: header-name to position map, `build_rows` cell check, `split_batches` (100 per request, ceiling 100), `add_mismatches` / `delete_mismatches` read-back diffs, `rows_hash`, the resume state (`make_state`, `plan_resume`: decides what an interrupted add still has to send by comparing the table to a baseline, never by a batch counter), the row backup shape, `create_body`, and thin POST wrappers (`post_add`, `post_delete`, `post_create`, `export_file`, `import_file`). |
| `datatable_view.py` | Views and widgets: `parse_view`, pure edits that never change the column set or filters (`set_hidden`, `reorder`, `set_page_size`, `set_frozen_column`), `preserved_problems`, `view_hash`, `view_mismatches`, `widget_state` (empty / unclaimed / own / foreign), `duplication_failures`, `sync_state`, and thin wrappers for the widget and view routes. Filter editing is out of scope for v1. |
| `pace.py` | One process leaves 10 s between its write POSTs (routes marked `writes`); reads are not paced. A 429 raises `RateLimited` and is never resent (exit 6). |
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

## The forbidden route

`datatable_content_delete_by_table` is documented in `routes.py` and marked `forbidden`: with the flag
false it clears the stored filters and deletes EVERY row, with no audit entry. `lj_http` refuses to send
it, and a test fails if any script outside `routes.py` and the tests names it. Delete rows by id. The
refusal is checked twice: on the route name, and on the FINAL resolved URL path, so a route that resolves to
the forbidden path is refused too.

## Path parameters

`lj_http._url` validates every path parameter before a request is built, and raises `PathParamError`
(a `ValueError`; `lj_http.exit_code` and `die` give it exit 2, nothing sent). `lj` is digits only; `widget` is letters and
digits only; `name` (export and template file name) is non-empty and has none of `/ ? # % \\ ..` or control
characters, and is percent-encoded once. A missing or extra parameter is also refused, and the resolved path
must still have the route template's segments. Table and view uuids travel in request bodies, not paths;
`lj_http.check_uuid(value, what)` checks them for skills that want the same refusal. Skills should catch
`PathParamError` where they parse user input and pass it to `die`.

## The fake Lumberjack

`tests/fixtures.py` holds `FakeLumberjack`, an in-memory stand-in for every data-table, widget and view
route that `install(monkeypatch)` puts over `requests.request`, so a skill's real code runs against it.
Switches: `deny_writes`, `deny_reads`, `fail_next(status)`, `apply_then_fail_next(status)` (the write
lands, the answer is an error), `drop_add_index`, `duplicate_add_index`, `short_rows`, `rate_limit_after`,
`view_drop_fields`, `view_ignore_update`, `routed`, `import_preset`. `save_card(dashboard, widget)` models
the server's copy-on-save for dashboard cards (read from the Haskell, not yet measured live).
`forbidden_calls` records any call to the delete-everything route.
