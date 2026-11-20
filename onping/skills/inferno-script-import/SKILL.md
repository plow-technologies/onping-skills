---
name: inferno-script-import
description: Import one OnPing Inferno script from an ExportedScript JSON file via POST /script/vp/import (VP script), /script/cp/import (CP script) or /script/ml/import (ML inference script). Saves a new version when the file's hash is the script's latest version, and otherwise creates a new script. MUTATING — requires --yes. Pair with inferno-script-export for an export → edit → re-import round trip.
allowed-tools: Bash(uv run *)
---

# Inferno Script Import

> **⚠️ WARNING: this skill changes live data, and its changes cannot be undone.**
> An import either adds a new version that becomes the script's latest, or creates a new script. No skill here deletes a script or rolls back a version. The server's `DELETE /script/delete/{hash}` (`/script/ml/delete/{hash}` for ML) removes a script's **whole history**, and only when no parameter uses it. No skill wraps it. Keep the exported file (`inferno-script-export`) so you know which hash you started from. It previews by default and changes nothing until you pass `--yes`. `--dry-run` also previews, and wins over `--yes`.

Import one Inferno script from the JSON that `inferno-script-export` (`GET /script/export/{hash}`) writes. The server parses the script and type-checks it against the route's prelude. If anything fails, it rejects the whole import with a list of diagnostics and saves nothing.

> **Verified live on 2026-10-01 and 2026-10-11** on `onping.plowtech.net`, with throwaway scripts that were then deleted. Checked on 2026-10-01: create, update from the head hash, a stale re-import (`inferno.import.version`), a wrong `--kind` between VP and ML (`inferno.import.scriptType`), a type error, and a non-`write` output on the ML route. Checked on 2026-10-11, after the #16187 routes: a CP script updated through `--kind cp`, even though the file's `type` was stale; a stale CP re-import; the CP file on `--kind vp` and the VP file on `--kind cp`, each with a hint naming the right `--kind`; an array output on `--kind cp`; `--as-new --kind cp`, listed as CP-typed; and a VP create on `/script/vp/import`. With a token, the retired `/script/import` returns 404 `{"error":"NotFound"}`. Checked read-only on 2026-10-15, after #16217: ML exports carry `inputs` and `outputs` and VP exports have no `models`. The local checks pass on two current ML exports and warn on a third with `inputs: {}`. Stripping `inputs` and `outputs` gets the old-format refusal, and `--ml-input` rebuilds the export's own split. No import was sent on 2026-10-15, so the server's `inferno.import.io` text was checked against the server source, not live.

## Pick the route with `--kind`

| `--kind` | Route | Prelude | Saved as | Can update |
|---|---|---|---|---|
| `vp` | `POST /script/vp/import` | VP/CP (no tensor types) | `VirtualParameterScript` | VP scripts only |
| `cp` | `POST /script/cp/import` | VP/CP (no tensor types) | `ControlParameterScript` | CP scripts only |
| `ml` | `POST /script/ml/import` | ML inference | `MLInferenceScript`, with the file's `models` and `inputs` | ML inference scripts only |

Pick the `--kind` for the script type of the script you exported. The file does not say which type it is, so `--kind` is always required. A wrong `--kind` on an update is rejected with `inferno.import.scriptType`, and the hint names the right one. With `--as-new`, nothing is updated, so the route alone decides the type: `--as-new --kind vp` on a CP script's file creates a new VP script. Mask and ML training scripts have no import route.

> **`/script/import` is gone.** onping 2026.10.4 (#16187) renamed it `/script/vp/import` and added `/script/cp/import`. Production returns 404 for the old path, and the skill never calls it. `inferno-cp-import` creates control parameters, not scripts.

## Input and output rules

The server checks every route's script the same way, after type inference. A failure rejects the import with a diagnostic:
- **Inputs** — Every argument must resolve to `series of 'a` or `array of series of 'a`. `'a` may be a base type such as `double`, and an argument whose type stays a bare type variable also passes. The ML route also allows `modelName`. Anything else is rejected with "Disallowed input type: … Did you mean to get the value from the input?".
- **Output, VP and CP** — The result can be a type variable, a base type, a `series`, an `option of` one of these, or a closed record of them. It cannot be a function, array, tuple, `rep`, open record, or nested record. A failure is `inferno.import.output` "Invalid output, output cannot be: <type>".
- **Output, ML** — The result must be `array of write`.
- **The file's `type`** — Not checked. The server infers the type from `body` and ignores the declared one, so you don't need to update `type` after editing the body.

## Update or create: the file's `hash` decides

- **The hash is on this server and is the latest version** — The import saves a **new version** on top of it, as an edit in the editor does. The version gets a **new hash**. It keeps the server's **group, visibility and description**, and **ignores** the file's `group` and `visibility`. You need edit permission on the script (owner, or a member of its group), otherwise you get a 403.
- **The hash is on this server but the script has been saved since** — **Rejected** with `inferno.import.version`. The server appends only to the head of a history, so saving on top would silently drop the newer changes. Export the latest version, re-apply your edit, and import that.
- **The hash is null, absent, or unknown to this server** (for example, exported from another server, or since deleted) — The import **creates** a new script with the file's `group` and `visibility`. You must belong to that group, otherwise you get a 403.
- `--as-new` sets `hash` to null before sending. It forces a create even when the hash would have matched, which is how you copy a script.

> **A new version does not repoint anything.** Virtual, control and ML parameters keep running the hash they were configured with. After an update, repoint them yourself: `ml-parameter-update` for ML parameters, and the UI or `inferno-cp-import` for CPs.

## Related Skills

- **onping-login** — Get the access token
- **inferno-script-export** — Produce the file this skill imports
- **ml-parameter-update** — Point an ML parameter at the new hash after an update
- **ml-script-models** — Check which models a script uses before and after
- **inferno-lookup** — Inferno language reference, for fixing a rejected body
- **inferno-cp-import** — Create or update Inferno **control parameters** (not scripts)

## Usage

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/inferno-script-import/scripts/import_inferno_script.py

# 1. Export the current version and keep the file as a backup
uv run ~/.claude/skills/inferno-script-export/scripts/export_inferno_script.py "SCRIPT_HASH" --output before.json
cp before.json edited.json   # edit "body", "name", "models", "inputs" or "outputs"

# 2. Preview (no request)
uv run $SKILL --kind vp --input edited.json

# 3. Apply
uv run $SKILL --kind vp --input edited.json --yes

# The same for a CP script
uv run $SKILL --kind cp --input edited-cp.json --yes

# Copy an ML script as a new script instead of a new version
uv run $SKILL --kind ml --input edited.json --as-new --yes

# An ML file exported before onping 2026.10.13: name its inputs (preview first)
uv run $SKILL --kind ml --input old-ml.json --ml-input flow --ml-input level=rw
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

Set `ONPING_BASE_URL` to target a different OnPing server (default `https://onping.plowtech.net`).

## Flags

- `--kind {vp,cp,ml}` — **Required.** Selects the route, the prelude, and the script type saved (see the table above).
- `--input PATH` — The ExportedScript JSON file (default: stdin).
- `--ml-input NAME[=r|w|rw]` — `--kind ml` only, repeatable. Makes `NAME` an input with that mode (`r` by default), and every other named argument that is not a model an output. It replaces the file's `inputs` and `outputs` in the posted body; the file on disk is not changed. When the file had its own split and it differs from the `--ml-input` split, the preview warns, shows the file's split as `file inputs (replaced)` / `file outputs (replaced)`, and `--json` reports it, as it was in the file, under `replaced`. A split that matches gives no warning. A malformed file value (for example a list `inputs` or a string `outputs`) is shown as raw JSON marked `(malformed)`, never split into characters. A malformed value (blank name, a mode other than `r`/`w`/`rw`, or one name with two modes) is a usage error, exit 2. A name that is not an argument, or is a model, is reported in the `inferno.import.io` wording, exit 1. See "Files exported before onping 2026.10.13". It is not `--input`, which names the file.
- `--allow-empty-inputs` — `--kind ml` only. Lets `--yes` send a file with no inputs (`inputs` is `{}`, null or absent) and a non-empty `outputs` (see below). If the file is not missing its inputs, or `--ml-input` is given, the flag has no effect and a `NOTICE` says so on stderr.
- `--allow-old-ml-format` — `--kind ml` only (with `--kind vp` or `--kind cp` it is a usage error, exit 2). Sends an ML file with neither `inputs` nor `outputs` unchanged, for a server older than onping 2026.10.13. onping 2026.10.13 and later reject that file (`inferno.import.io`), so the preview warns, and `--json` sets `oldFormat: true`. If the file is not in the old format, or `--ml-input` is given, the flag has no effect and a `NOTICE` says so on stderr.
- `--as-new` — Send `hash: null`, so the import creates a new script.
- `--yes` — Perform the import. **Required** for any network call.
- `--dry-run` — Preview only. This is the same as passing no flag, and it wins over `--yes`.
- `--json` — Emit JSON instead of text.

## Local Checks (before any request)

- The file is **one** JSON object. A list, which is what `POST /scripts/export` returns, is refused with the server's own wording.
- `name`, `args`, `body`, `type`, `author`, `group`, `visibility` and `timestamp` are present, and `name` is not blank. `hash`, `models`, `inputs` and `outputs` are optional. The server ignores `author` and `timestamp`: it records the importing user and the import time.
- `--kind vp` or `--kind cp`: a `models`, `inputs` or `outputs` with the wrong shape is refused, because the server parses all three on every route and would answer HTTP 400 (`FromJSON ExportedScript`). `models` and `inputs` must be objects, and `outputs` a list of names, so `[]` for `inputs`, `{}` or a string for `outputs`, and `[]` for `models` are all refused. A null, absent or empty value of the right shape (`{}`, `[]`) decodes to nothing and is sent, since the VP and CP import never reads it (`importPlowScript`). A non-empty `models`, `inputs` or `outputs` is refused, because those routes would drop them silently.
- `--kind ml`: `models` must be an object; anything else would get HTTP 400.
- `--kind ml`: every `models` key must be one of `args`, and every value must be a UUID. The server also checks that every argument inferred as `modelName` has a model, and that each model version exists.
- `--kind ml`: a file with neither `inputs` nor `outputs` (null counts as absent) was exported before onping 2026.10.13. It is refused, unless `--ml-input` or `--allow-old-ml-format` is given, when some named argument is not a model; the message says that onping 2026.10.13 and later reject it, and names `--allow-old-ml-format` for an older server. If the file also has no `models` (or `"models": {}`), the refusal says it may be a VP or CP file and suggests `--kind vp` or `--kind cp`. A file whose named arguments are all models, or that has none, is sent, because the server accepts it. See the next section.
- `--kind ml`: `inputs` must be an object whose values are `"r"`, `"w"` or `"rw"`; the server would answer 400 to any other mode. `outputs` must be a list of names.
- `--kind ml`: the server's `inferno.import.io` check (`checkInputOutputArguments`), run locally with the same wording. Unnamed (`null`) arguments are skipped.
  - Every `inputs` key and `outputs` item must be an argument: "`<name>` is not an argument of the script."
  - Every named argument must be exactly one of an input, an output or a model: "The argument `<name>` is not listed as an input, an output or a model.", or "The argument `<name>` is listed as an input and an output." (the roles joined with " and ").
- `--kind ml --yes` with no inputs (`inputs` is `{}`, null or absent, which the server decodes as `{}`) and a non-empty `outputs` is refused unless `--ml-input` or `--allow-empty-inputs` is given. Nothing is sent, and the exit code is **4**, distinct from the input, HTTP and transport errors (1). With `--json`, stdout gets the dry-run preview object with `mode` and `status` set to `"refused"`, the reason in `error`, `exitCode: 4`, and the warning in `warnings`. The preview warns, and says so when `--allow-empty-inputs` is set. `inferno-script-export` warns using the same rule. See the next section.

## Files exported before onping 2026.10.13

onping 2026.10.13 (#16217) changed the ML export format. An ML export now carries `inputs` (argument → `"r"`, `"w"` or `"rw"`) and `outputs` next to `models`. `/script/ml/import` saves the inputs, and rejects a file unless every named argument is exactly one of the three (`inferno.import.io`). A VP or CP export no longer has any of the three keys.

- **An old ML file** (it has `models`, but no `inputs` or `outputs`) — The server rejects it, so the skill refuses it locally. Export the script again with `inferno-script-export`. If the source server is gone, name the inputs instead: `--ml-input flow --ml-input level=rw`. Every other named argument that is not a model becomes an output, which is the rule the export itself uses. The preview shows the split. To send the file unchanged to a server older than onping 2026.10.13, pass `--allow-old-ml-format`; a server on 2026.10.13 or later rejects it.
- **A mangled ML file** (`inputs` is `{}`, null or absent, and `outputs` is non-empty) — Before 2026.10.13, the ML import saved no inputs, so a script imported then has none. Its export, even a current one, lists every non-model argument as an output. The server accepts that file, but the imported script still has no inputs. The preview warns, and `--yes` refuses until you name the real inputs with `--ml-input`. A script that really has no inputs can pass `--allow-empty-inputs`. `inferno-script-export` warns about the same shape. The import saves a new version (or a new script); it does not repair the mangled version in place.

Do not infer inputs from `type`. It is display text, and the server does not check it.

## Output

- **Preview** — The route, name, args, type, models, and the plan. With `--kind ml` it also lists the inputs with their modes, the outputs, whether `--ml-input` set them, the file's own split if `--ml-input` replaced a different one, and any mangled-file, old-format or replacement warning. The plan reads: `UPDATE if this server has <hash> …, otherwise CREATE …`, or `CREATE a new script in group …`. No request is sent. Exit 0.
- **Refused (`--yes` on a mangled ML file)** — The reason on stderr, or with `--json` the preview object with `status: "refused"`, `error` and `exitCode: 4` on stdout. No request is sent. Exit **4**.
- **Created** — `CREATED '<name>': <new hash>`, plus the inferred type and inputs. Exit 0.
- **Updated** — `UPDATED '<name>': <old hash> -> <new hash>`. Exit 0.
- **Rejected (422)** — One line per diagnostic, `line:col-line:col severity source: message`, on stderr. Positions are **1-based** and relative to the script body. The server sends 0-based LSP positions, and `--json` passes them through unchanged. `inferno.import.*` diagnostics are about the whole file and print `file` instead of a position. Exit **3**. The sources you will see:
  - `inferno.import.version` — The file is not the latest version. Export the latest and redo the edit.
  - `inferno.import.scriptType` — The script belongs to another route. The hint reads the script type from the message and names the `--kind` to retry with: `virtual parameter` → `vp`, `control parameter` → `cp`, `Inferno ML inference` → `ml`. For a mask or ML training script, or a script with no script type, the hint says no import route updates it.
  - `inferno.import.models` — A `models` key that is not an argument, or a model argument with no version. The ML route only.
  - `inferno.import.io` — An `inputs` key or `outputs` item that is not an argument, or an argument that is not exactly one of an input, an output or a model. The ML route only, since onping 2026.10.13. The hint says to re-export a file from before 2026.10.13, or to name the inputs with `--ml-input`. The local check catches these first, so you see this only when the server and the skill disagree.
  - `inferno.import.name` — The name is blank.
  - `inferno.import.output` — The output type is not allowed on this route; see "Input and output rules". The hint gives the rule for the `--kind` used. For example, a plain `double` on the ML route gives `Invalid output, output cannot be: double`.
  - `inferno.infer`, and the other `inferno.*` sources from the LSP — The parse or type error itself, positioned in the body.
- **Error** — `Import FAILED — HTTP <status>: <message>`. Exit 1. The cases:
  - 401 `NotAuthenticated`: the token is expired or invalid. Run `onping-login` again.
  - 400: invalid JSON, a list, a `models`, `inputs` or `outputs` with the wrong shape, an `inputs` mode other than `r`, `w` or `rw`, or the body is a function. The local checks catch all but the last.
  - 403: you cannot edit the script, or cannot use its group.
  - 404 `NotFound`: the server has no route for this `--kind`. `/script/vp/import` and `/script/cp/import` need onping 2026.10.4 or later. The skill names the route.
  - 500: the script's history could not be looked up.

`warnings` in the success body is always `[]` for now. The server drops LSP warnings until inferno-lsp re-exports them.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/script/vp/import` | POST | `application/json` | One `ExportedScript` | `ScriptImported` / `{"typed-error": ScriptImportRejected}` / `{"error": msg}` |
| `/script/cp/import` | POST | `application/json` | One `ExportedScript` | same |
| `/script/ml/import` | POST | `application/json` | One `ExportedScript` (with `models`, `inputs`, `outputs`) | same |

- **`ScriptImported`** — `{hash, name, type, inputs, warnings, updatedFrom}`. `updatedFrom` is `null` when the import created a new script.
- **`ScriptImportRejected`** — `{diagnostics: [{range: {start: {line, character}, end: {…}}, severity, source, message}]}`.

Source: `importScriptWith` in `onping/Handler/Inferno/Scripts/Import.hs`. The route wiring is in `Scripts.hs`, where `postVPInfernoScriptImportR` and `postCPInfernoScriptImportR` both call `importPlowScript` with their script type, and in `Scripts/ML.hs` (`postMLInfernoScriptImportR`, which runs `checkModelArguments` and `checkInputOutputArguments` from `Import.hs`). The types are in `onping-frontend-types/src/OnPing/Frontend/Types/InfernoScript.hs`.

## Authentication

All three routes take the bearer token from `onping-login`, which was verified live on 2026-10-01. An invalid or expired token gets **401** `{"error": "NotAuthenticated"}`. A 3xx redirect or an HTML body is also treated as an auth failure. Either way the skill exits 1 and imports nothing.
