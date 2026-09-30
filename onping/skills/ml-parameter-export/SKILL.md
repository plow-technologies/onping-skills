---
name: ml-parameter-export
description: Export OnPing Inferno inference (ml-) parameters as portable JSON via POST /inferno/ml/inference/export. Read-only. Use to back up, inspect, or transfer a parameter's full definition — including the `itype` instance sizing, which no other route returns.
allowed-tools: Bash(uv run *)
---

# ML Parameter Export

Pull a complete, self-contained JSON snapshot of one or more OnPing inference
parameters (`InferenceParamX`). Wraps `POST /inferno/ml/inference/export`.

**Read-only despite being a POST.** The request body is the list of parameter ids
to export; the handler reads, permission-checks, and serializes. Nothing on the
server changes, so there is no `--yes` gate.

The output is exactly the shape `POST /inferno/ml/inference/import` consumes, so
an export is a valid backup and transfer artifact.

## Use This Skill For

- Backing up a parameter's full definition before a risky edit
- Capturing `itype` (the EC2 instance sizing) — **no other route returns it**
- Inspecting a parameter's script hash, PID wiring, schedule, and resolution in
  one flat record
- Batch-exporting several parameters in a single call
- Producing an import-shaped artifact to move a parameter between environments

## Do Not Use This Skill For

- **Live runtime state** (`active`, `terminated`) — those are omitted by design.
  Use `ml-parameter-update get`.
- **Full `SourceInfo`** per binding (parameter type, location) — export carries
  bare PIDs only. Use `ml-parameter-update get --with-sources`.
- **Writing a parameter back.** `POST /inferno/ml/inference/import` is the
  inverse and is deliberately NOT wrapped by any skill: with `id` present it may
  upgrade the EC2 instance (`Parameters.hs`), and with `id` absent it
  **provisions a brand-new inference server** (`:612`). That needs its own
  safety design. Exports are import-ready for whenever that lands.
- Editing script hashes or PID bindings — use `ml-parameter-update`.
- Model or model-version artifacts — use `ml-model-manage` / `ml-model-docs`.

## Related Skills

- `onping-login` — access tokens
- `ml-parameter-update` — the nested runtime view (`get`) and the write path for
  script-hash / PID / resolution edits. Discover ids with its `list`.
- `ml-model-manage` — parent models and TorchScript version upload
- `inferno-lookup` — Inferno language reference for the referenced scripts

## Commands

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
```

### Export one parameter

```bash
uv run ~/.claude/skills/ml-parameter-export/scripts/ml_parameter_export.py \
  "$ACCESS_TOKEN" 00000000-0000-4000-8000-00000000a001 --pretty
```

### Export several, to a file

```bash
uv run ~/.claude/skills/ml-parameter-export/scripts/ml_parameter_export.py \
  "$ACCESS_TOKEN" \
  00000000-0000-4000-8000-00000000c002 \
  00000000-0000-4000-8000-00000000c003 \
  --output params-backup.json --pretty
```

### Pipe ids in from `ml-parameter-update list`

```bash
uv run .../ml-parameter-update/scripts/ml_parameter_update.py "$ACCESS_TOKEN" list \
  | awk '{print $1}' \
  | uv run .../ml-parameter-export/scripts/ml_parameter_export.py "$ACCESS_TOKEN" --stdin-ids \
      --output all-params.json
```

### Single bare object instead of a one-element array

```bash
uv run .../ml_parameter_export.py "$ACCESS_TOKEN" <UUID> --unwrap-single --pretty
```

`--unwrap-single` refuses (non-zero, no file) if more than one record came back,
rather than silently discarding data.

## CRITICAL: the route silently omits ids it cannot serve

A requested id that is unknown, or whose group/location the caller cannot reach,
is **absent from the response array**. There is no error, no warning, and nothing
in the body names the dropped id. Verified live 2026-07-31:

| Request | Response |
| --- | --- |
| `[valid, bogus]` | `200` with **1** record — bogus silently dropped |
| `[bogus]` | `200 []` |
| `[]` | `200 []` |

For a backup tool that is the worst failure mode: you find out when you try to
restore. So:

1. **`--strict` is the default.** The script diffs requested ids against returned
   ids, and on any mismatch names the missing ids, **writes nothing** to
   `--output`, and exits non-zero. A partial export can never be mistaken for a
   complete one.
2. **`--no-strict`** downgrades this to a stderr warning with exit 0, for
   deliberate "export whatever I can reach" sweeps.
3. **UUIDs are validated locally** before the request. OnPing cannot distinguish
   a typo'd id from one you lack access to — both vanish silently — so a
   malformed id is rejected client-side, naming it, with no request sent.
4. **An empty id list is refused locally**, since the route answers it with an
   ambiguous `200 []`.

## Shape gotchas

### 1. `itype` is export-only

`itype` — `{"device": "gpu", "cap": "medium"}`, the EC2 instance sizing — appears
in this route's output and **nowhere else**: not `GET /inferno/ml/inference/{uuid}`,
not `/inference/all`, not the with-sources list. Any round-trip that does not go
through this route loses the parameter's instance sizing.

### 2. Export is flat; `ml-parameter-update get` is nested

These two are **not** interchangeable:

```
export (this skill)          get (ml-parameter-update)
------------------           -------------------------
id                           id
name                         name
description                  description
company                      company
schedule                     schedule
gid                          active         ← runtime only
script                       param.gid
inputs                       param.id
outputs                      param.script
resolution                   param.inputs
itype        ← export only   param.outputs
                             param.resolution
                             param.terminated  ← runtime only
```

Reach for **this skill** for a portable snapshot; **`get`** for live runtime
state.

### 3. `inputs` / `outputs` hold bare PIDs, not `SourceInfo`

Values are a PID integer or an array of PID integers, keyed by binding name:

```json
"inputs":  { "casing_psis": [300001, 300002], "well_names": [300201] },
"outputs": { "off_time_outs": [300101, 300102] }
```

The handler strips source info via `exportedParamStripSourceInfo`
(`Parameters.hs`) because the import side can neither require nor trust
caller-supplied metadata. For parameter type and location per binding, use
`ml-parameter-update get --with-sources`.

## Output shape

A JSON array (even for one id, so the artifact is always import-shaped), each
record flat:

```json
[
  {
    "id": "00000000-0000-4000-8000-00000000a001",
    "name": "Example MultiWell LLM SAC",
    "description": "Example MultiWell LLM SAC - LLM-Enhanced Soft Actor Critic Model",
    "company": 100,
    "gid": "o000000000000000000000001",
    "script": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
    "inputs": { "casing_psis": [300001, 300002, 300003, 300004] },
    "outputs": { "off_time_outs": [300101, 300102, 300103, 300104] },
    "resolution": 60,
    "schedule": { "enabled": true, "stype": { "tag": "OnCron", "contents": "0 * * * *" } },
    "itype": { "device": "gpu", "cap": "medium" }
  }
]
```

The response is shape-checked before anything is emitted: a missing required key
fails non-zero (signalling the OnPing API contract changed), while an
unrecognized **extra** top-level key is noted on stderr and passed through
unchanged, so a server-side field addition is forward-compatible.

## Notes

- Set `ONPING_BASE_URL` to target a non-production environment.
- `--output` is written only after a verified 200 that passed the shape guard.
  Every failure path writes nothing.
- The skill sends `Content-Type: application/json`. The OnPing web UI sends
  `text/plain;charset=UTF-8` (a `fetch()` default) and the handler accepts
  either — `parseInsecureJsonBody` ignores the content-type. Do not "fix" this
  to match a browser trace.
- Errors are surfaced verbatim from OnPing's `{"error": "..."}` envelope. Auth
  failure is `401 {"error":"NotAuthenticated"}`; a non-array body is
  `400 {"error":"JSON not properly formatted: ..."}`.
- **Permission failures are 500s, not 403s** (unverified — see below). Both
  `NoAuthorizedGroup` ("None of the current user's groups are authorized to
  access this param") and `UnauthorizedLocation` ("PID N cannot be used as I/O
  parameter; user is not authorized for location M") are raised inside
  `tryMlErrors send500` (`Parameters.hs`, messages at `:801-810`), so they
  should arrive as HTTP 500 with an `{"error": ...}` body. This was **not
  verified live** — the token available during development had access to every
  parameter probed. The script surfaces whatever error string the server sends,
  so behavior does not depend on the exact status code.
- Exported `description` fields are free text and may contain operational notes.
  Review before pasting an export into a ticket or chat.

## Source of truth

- Route: `onping/config/routes` (`ExportInferenceParamsR POST`)
- Handler: `onping/Handler/Inferno/ML/Parameters.hs` — group check
  `:554`, per-PID location check `:562`, source-info stripping `:548`
- Wire type: `ExportedInferenceParam` at
  `inferno-ml-orchestrator-types/src/Inferno/ML/Orchestrator/Types.hs`,
  flattening `ToJSON` instance at `:2052`
- Frontend caller (the UI's export button):
  `OnpingFetch/OnpingFetch_InfernoML.res`
- Shared HTTP layer: `_inferno_ml_routes/inferno_ml_models.py`
