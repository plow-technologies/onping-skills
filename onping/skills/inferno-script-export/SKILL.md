---
name: inferno-script-export
description: Export one OnPing Inferno script (VP, CP, or ML inference) as importable JSON via GET /script/export/{hash}. Read-only. The file is what inferno-script-import accepts, so use it to back up a script before editing, or to start an export → edit → re-import round trip.
allowed-tools: Bash(uv run *)
---

# Inferno Script Export

Export one version of an Inferno script as a single `ExportedScript` JSON object, via `GET /script/export/{hash}`. It works for any Inferno script, whether VP, CP, or ML inference. **Read-only.**

The output is exactly the input that `inferno-script-import` takes. That makes this the first step of an edit round trip: export, change the `body` (or `name`, `models`, `inputs`, `outputs`), then re-import as a new version.

> **Not the same as `vp-script-fetch` / `cp-script-fetch`.** Those return `/script/id/{hash}`, which is the editor's view, with LSP session metadata. They also mint an LSP session server-side. This skill returns the portable export format, which has the pretty-printed `body`, the argument names, the rendered type, and the ML `models`, `inputs` and `outputs`. It is the only format the import routes accept.

> **Verified live on 2026-10-01** on `onping.plowtech.net`, with a bearer token, for VP, CP and ML inference scripts. The ML export included `models`. **Checked again on 2026-10-15**, after onping 2026.10.13 (#16217): ML exports carry `models`, `inputs` and `outputs`, and a VP export has none of them. One ML export had `inputs: {}`, and the skill warned about it.

## Related Skills

- **onping-login** — Get the access token
- **inferno-script-import** — Import the file back as a new version or a new script
- **vp-scripts** / **cp-list** / **ml-script-models** — Find the hash of the script you want
- **vp-script-fetch** / **cp-script-fetch** — Read the editor view of a script (`/script/id`)

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)

# To stdout (the JSON goes to stdout; a one-line summary goes to stderr)
uv run ~/.claude/skills/inferno-script-export/scripts/export_inferno_script.py "SCRIPT_HASH"

# To a file
uv run ~/.claude/skills/inferno-script-export/scripts/export_inferno_script.py "SCRIPT_HASH" --output script.json
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

`SCRIPT_HASH` is a script version hash: 43 URL-safe base64 characters followed by `=` (for example `JJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJ=`). The skill checks the shape locally and percent-encodes it in the path. A hash that starts with `-` (about 1 in 64) is read as the hash, not as an option, so it needs no quoting or `--`.

Set `ONPING_BASE_URL` to target a different OnPing server (default `https://onping.plowtech.net`).

## Flags

- `--output PATH` — Write the JSON to a file instead of stdout.
- `--force` — Overwrite an existing `--output` file. Without it the skill refuses, so an earlier backup is never clobbered.
- `--json` — With `--output`, print a JSON status object (`output`, `hash`, `name`, `type`, `models`, plus `inputs` and `outputs` when the export has them) instead of the text summary.

The text summary counts args and models, and for an ML export also `N input(s), M output(s)`.

## Output Shape

An ML inference script:

```json
{
  "hash": "JJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJ=",
  "name": "Example Flow Forecast",
  "args": ["input0", "model_00000000-0000-4000-8000-000000000001", "output0"],
  "body": "…pretty-printed script body…",
  "type": "series of double → modelName → write → array of write",
  "author": "UserId (MongoKey <user id>)",
  "group": "<group id>",
  "visibility": "VCObjectPrivate",
  "timestamp": 1700000000,
  "models": { "model_00000000-0000-4000-8000-000000000001": "<model version UUID>" },
  "inputs": { "input0": "r" },
  "outputs": ["output0"]
}
```

A VP or CP script has no `models`, `inputs` or `outputs`:

```json
{
  "hash": "KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=",
  "name": "Example Daily Average",
  "args": ["input0"],
  "body": "…pretty-printed script body…",
  "type": "series of double → double",
  "author": "UserId (MongoKey <user id>)",
  "group": "<group id>",
  "visibility": "VCObjectPrivate",
  "timestamp": 1700000000
}
```

- `hash` — The version exported. On import, this decides whether the server **updates** that script or **creates** a new one (see `inferno-script-import`).
- `args` — Argument names, in order. `null` marks an unnamed argument.
- `body` — The script without its `fun args ->` wrapper.
- `type` — The rendered type signature, using `→`, for reading only. A record result is spread over several lines. Import does not check it.
- `author` — A display string such as `UserId (MongoKey …)`, not a bare id. Import ignores it.
- `visibility` — `VCObjectPrivate` or `VCObjectPublic`.
- `models` — Only for ML inference scripts. It maps each model argument to a model version UUID. Since onping 2026.10.13 (#16217), VP and CP exports have no `models` key at all. Before that release they had `"models": {}`.
- `inputs` — Only for ML inference scripts, since onping 2026.10.13. It maps each input argument to its mode: `"r"` (read), `"w"` (write) or `"rw"`.
- `outputs` — Only for ML inference scripts, since onping 2026.10.13. It lists every named argument that is neither an input nor a model. `/script/ml/import` requires every named argument to be exactly one of an input, an output or a model.

> **Mangled ML scripts.** Before onping 2026.10.13, `/script/ml/import` saved no inputs. A script imported then exports with `inputs: {}`, and every non-model argument appears in `outputs`. The skill still writes the file, but warns on stderr. It warns whenever `inputs` is `{}`, null or absent and `outputs` is non-empty, which is the same rule `inferno-script-import` uses. Fix the split before re-importing, with `inferno-script-import --ml-input NAME[=r|w|rw]` or by editing `inputs` and `outputs`. An ML file exported before 2026.10.13 has `models` only. `inferno-script-import` refuses it, so export it again.

The file is written unchanged, so any fields the server adds later survive the round trip.

The file does not record the script type, so pass the matching import `--kind` yourself: `--kind vp` for a VP script, `--kind cp` for a CP script, and `--kind ml` for an ML inference script.

## Error Handling

- **Bad hash shape** — Exits 1 before sending any request.
- **HTTP 500 containing `CouldNotFindPath`** — This server has no script with that hash. It was never saved here, or it has been deleted. The skill reports this as a missing script.
- **JSON 404 `{"error": "Script not found"}`** — The user can neither edit the script nor see it as public, **or** its body cannot be pretty-printed. The server gives the same answer for both.
- **HTTP 401 `{"error": "NotAuthenticated"}`** — The token is expired or invalid. Run `onping-login` again.
- **HTML 404** — The route is not on this server.
- **3xx redirect / HTML body** — Treated as an expired token. Run `onping-login` again.
- **Response hash differs from the request**, or a required field is missing — Exits 1 and writes no file.

## API Reference

| Endpoint | Method | Auth | Response |
|----------|--------|------|----------|
| `/script/export/{hash}` | GET | Bearer | One `ExportedScript` object (bare on success; `{"error": msg}` on failure) |

The source is `getInfernoExportScriptR` in `onping/Handler/Inferno/Scripts.hs`, and the type is `ExportedScript` in `onping-frontend-types/src/OnPing/Frontend/Types/InfernoScript.hs`. The older `POST /scripts/export` takes a list of hashes and returns a **list**, which the import routes reject.
