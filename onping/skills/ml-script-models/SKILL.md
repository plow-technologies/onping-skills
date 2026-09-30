---
name: ml-script-models
description: Resolve which models an OnPing Inferno ML inference parameter or script uses, and the reverse — which scripts and parameters use a given model version. Read-only. The link lives in script metadata, not on the parameter.
allowed-tools: Bash(uv run *)
---

# ML Script Models

Answer "which models does this inference parameter run?" — and the reverse, "what
breaks if I swap this model?"

**An OnPing inference parameter carries no model reference.** `params` has no
model column, and no table links a parameter to a model. Every other route you
might reach for returns a script hash and nothing else. The link lives in the
**script's** version-control metadata, under a JSON key named `author`, which
reads like provenance rather than configuration.

## The two-hop chain

```
GET  /inferno/ml/inference/{uuid}   -> param.script  (a hash, nothing else)
POST /scripts/by-hash               -> [0].author.scriptTypes[].contents.models
                                       = { ident: model-VERSION-uuid }   <- THE LINK
GET  /inferno/ml/model/version/{id} -> version label, kind, parent model id
```

`InferenceOptions.models` (`plow-inferno/src/Plow/Inferno/Types/Metadata.hs`)
carries it, and the type's own comment says so: *"This is how model selections
are linked to scripts."* In Postgres the junction is `mselections (script, model,
ident)`, keyed on **script hash and never on parameter id** — which is why
inspecting a parameter never reveals the link.

## Use This Skill For

- Finding which model versions an inference parameter actually runs
- Confirming a retrain landed: which version is live right now
- Blast radius before a model swap — every script and parameter using a version
- Detecting a parameter left pinned to a superseded script revision

## Do Not Use This Skill For

- **Changing a model selection.** That means saving a new script revision, which
  belongs to the script LSP session, not an API wrapper. See `ml-parameter-update`.
- **Re-pointing a parameter at a new script hash** — `ml-parameter-update`.
- **Model or version lifecycle** (create, upload, delete) — `ml-model-manage`.
- **Version metadata / model cards** — `ml-model-docs`.
- **Control-parameter scripts** — `cp-script-fetch`.

## Related Skills

- `onping-login` — access tokens
- `ml-parameter-update` — the write path for script-hash and PID edits
- `ml-parameter-export` — a portable parameter snapshot, including `itype`
- `ml-model-manage` / `ml-model-docs` — the model side
- `inferno-lookup` — Inferno language reference for the scripts involved

## Commands

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
```

### Forward: which models does this parameter use?

```bash
uv run ~/.claude/skills/ml-script-models/scripts/ml_script_models.py \
  "$ACCESS_TOKEN" 00000000-0000-4000-8000-00000000a001
```

```
Parameter : 00000000-0000-4000-8000-00000000a001  Example MultiWell LLM SAC
Script    : AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=  ExampleMultiWellLLMSAC

IDENT                                        VERSION ID                            VERSION  KIND         PARENT MODEL
-------------------------------------------  ------------------------------------  -------  -----------  -------------------------------------
Alpha_1_1_1_1_1XH_sac_actor_model         00000000-0000-4000-8000-00000000b001  v5       torchscript  Alpha 1-1-1-1 1XH SAC Actor
Bravo_2H_22_02_sac_actor_model             00000000-0000-4000-8000-00000000b002  v15      torchscript  Bravo 2H-22-02 SAC Model
Charlie_3_3_3_3_1XH_sac_actor_model   00000000-0000-4000-8000-00000000b003  v5       torchscript  Charlie 3-3-3-3-1XH SAC Model
Charlie_4_4_4_4_1XH_sac_actor_model  00000000-0000-4000-8000-00000000b004  v4       torchscript  Charlie 4-4-4-4 1XH SAC Model
opus                                         00000000-0000-4000-8000-00000000b005  v7.5.0   bedrock      Claude Opus 5
```

A script hash works in place of the UUID, skipping the parameter hop.

### Reverse: what uses this model version?

```bash
uv run .../ml_script_models.py "$ACCESS_TOKEN" \
  00000000-0000-4000-8000-00000000b005 --reverse
```

A parent model id works too, and expands over that model's versions.

### Is this parameter running the newest script?

```bash
uv run .../ml_script_models.py "$ACCESS_TOKEN" <param-uuid> --check-latest
```

### Scripted use

```bash
# ident -> version-id pairs, tab separated
uv run .../ml_script_models.py "$ACCESS_TOKEN" <param-uuid> --map-only

# full record, including the resolved script hash
uv run .../ml_script_models.py "$ACCESS_TOKEN" <param-uuid> --json --pretty

# just the version ids in use
uv run .../ml_script_models.py "$ACCESS_TOKEN" <param-uuid> --map-only | cut -f2
```

The default is a table, matching the rest of the `ml-*` family. `--json` and
`--map-only` cover the scripted cases.

## CRITICAL: a model swap changes the script hash

`InferenceOptions` derives `VCHashUpdate`, and `vcHash` is applied to the whole
`VCMeta` — the `author` metadata included, not only the expression body. So the
model selection is part of the script's identity.

**Changing a model selection mints a new script hash.** Observed live on
2026-08-04, parameter `00000000-…a001` moved from `ZZZZZZZZ…` to `AAAAAAAA…`, and
exactly one of five selections changed:

| Ident | Before | After |
| --- | --- | --- |
| `Alpha_1_1_1_1_1XH_sac_actor_model` | `00000000-…b000` | **`00000000-…b001`** |
| `Bravo_2H_22_02_sac_actor_model` | `00000000-…b002` | `00000000-…b002` |
| `Charlie_3_3_3_3_1XH…` | `00000000-…b003` | `00000000-…b003` |
| `Charlie_4_4_4_4_1XH…` | `00000000-…b004` | `00000000-…b004` |
| `opus` | `00000000-…b005` | `00000000-…b005` |

CAUTION: Do not treat a model swap as an in-place edit. The old script hash stays
valid and keeps its old model bindings, so a parameter still pointing at it runs
the previous model versions with **no error**. A retrain is a script save *plus* a
parameter re-point, and the second step is easy to forget. Use `--check-latest`.

Two consequences for this skill:

1. **It never caches a hash.** Given a parameter UUID, it re-reads `param.script`
   on every call.
2. **Every result names the hash it resolved**, so a stale read is visible.

## Reverse results are group-scoped, and an empty result is not "unused"

`getParamsByInferenceScriptR` filters by the caller's authorized groups
(`onping/Handler/Inferno/ML/Parameters.hs`). A reverse result is
"parameters **you can see**", never every parameter in OnPing.

An empty reverse result is ambiguous, and the skill says so rather than claiming
the model is unused. `GET /inferno/ml/inference/list/script/{hash}` answers a
superseded hash with `200 []` — byte-identical to a genuine no-user result.

## Cost of the reverse sweep

No route answers "which parameters use this model version" directly, so the
reverse direction fetches **every** reachable script's metadata via `GET /scripts`
and matches locally. Measured 2026-08-04: 1506 scripts, of which 27 are ML. The
cost is proportional to the scripts your groups can reach.

That is the only route available today. An OnPing feature to serve this query
directly is in flight; when it lands, the reverse path is worth revisiting rather
than layering over.

## Shape gotchas

### 1. `models` values are model VERSION ids, not model ids

Despite the field name. Verified 2026-08-04: passing a version id to
`/inferno/ml/model/{uuid}` returns **HTTP 500**, while the parent id returns
`200`. The parent id comes off the version record's `model` field. Note also that
`/inferno/ml/model/history/{id}` lists versions of a *model* and has nothing to do
with a script's selections.

### 2. `scriptTypes` is a list

Scan it for the `MLInferenceScript` tag. Do not index element zero: the frontend
often matches exactly one element, while the backend `concatMap`s over the list
(`onping/Handler/Inferno/Scripts.hs`).

### 3. `author` holds `PlowMetadata`, not a user id

The actual user is `author.author`. The model map living under `author` is not a
documentation error.

### 4. `models` can be absent

Parsed server-side with `.:? … .!= mempty`, so older scripts can omit it. The
skill reports "no models selected" and exits 0, which is distinct from an error.
A non-ML script exits non-zero, naming the script types it found.

### 5. `GET /script/id/` has a side effect

It mints a session UUID and writes the server's LSP session map
(`onping/Handler/Inferno/Scripts.hs`), because that route exists to open
the editor. This skill uses `POST /scripts/by-hash` instead, which batches and
returns a byte-identical `models` map. `get_script()` is available in the shared
helper when the revision history or the editable flag is needed.

## Why the script cannot name a model

Worth knowing, because it explains why the metadata map is not redundant
bookkeeping. In the live script, `opus` appears exactly once:

```
let opusModel = ML.loadModel opus in
```

Nothing defines `opus`. It is a free variable — an argument to the script's
lambda, which the runtime binds at evaluation time from `mselections`. The
primitive accepts only a `VModelName` wrapping a UUID
(`inferno-ml-server/src/Inferno/ML/Server/Module/Prelude.hs`), with no text
overload, so a script author cannot write `ML.loadModel "my-model"`. The metadata
map is the only place the binding exists.

## Notes

- Set `ONPING_BASE_URL` to target a non-production environment.
- Read-only throughout. There is no `--yes` flag, and nothing here mutates OnPing.
- Enrichment is best-effort: if one model version fails to resolve, its ident and
  version id are still reported with the error noted, and the run fails only when
  nothing resolved.
- Exported `description` and script names are free text and can carry operational
  notes. Review before pasting output into a ticket or chat.

## Source of truth

- Routes: `onping/config/routes` (`InfernoScriptR`), `:819`
  (`InfernoScriptsByHashR`), `:1453` (`ParamsByInferenceScriptR`), `:1447`
  (`InferenceParamR`), `:1427` (`ModelVersionR`), `:1431` (`AllAvailableModelsR`)
- Wire type: `InferenceOptions` at
  `plow-inferno/src/Plow/Inferno/Types/Metadata.hs`
- Junction table: `mselections` in
  `inferno/nix/inferno-ml/migrations/v1-create-tables.sql`
- Runtime resolution: `getInferenceParamWithModels`,
  `inferno-ml-server/src/Inferno/ML/Server/Inference.hs`
- Selection write: `saveInferenceScript`,
  `inferno-ml-orchestrator/src/Inferno/ML/Orchestrator/Server/Inference.hs`
- Group filtering: `onping/Handler/Inferno/ML/Parameters.hs`
- Shared HTTP layer: `_inferno_ml_routes/inferno_ml_models.py`
