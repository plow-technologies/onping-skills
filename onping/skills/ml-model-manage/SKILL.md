---
name: ml-model-manage
description: Manage OnPing Inferno ML parent models and local TorchScript model versions. Use when creating, listing, updating, deleting, exporting, or uploading `.pt` model versions.
allowed-tools: Bash(uv run *)
---

# ML Model Manage

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> `model-create`, `model-update`, `model-delete`, `version-upload`, and `version-delete` create, change, or delete Inferno ML models and model versions. Deletes cannot be undone (export a version first with `version-export`; re-uploading it creates a new version id); remove a created model or version with `model-delete` or `version-delete`. Every write command acts immediately: there is no preview and no confirmation.

Manage OnPing Inferno ML parent models and local `.pt` model-version artifacts.

## Use This Skill For

- Creating parent models
- Listing or fetching models and versions
- Updating parent model `name`, `gid`, or `visibility`
- Uploading a new local `.pt` model version
- Deleting models or versions
- Exporting a stored model version zip

## Do Not Use This Skill For

- Editing version documentation fields only
- Patching model-card summary, uses, datasets, metrics, or version labels without uploading a new artifact

Use `ml-model-docs` for version metadata and card updates.

## Related Skills

- `onping-login` for access tokens
- `ml-model-docs` for version metadata updates
- `parameter-import` when wiring model script hashes into downstream parameter workflows

## Commands

Resolve commands relative to this skill directory.

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/ml-model-manage/scripts/ml_model_manage.py "$ACCESS_TOKEN" model-list
```

### Parent models

```bash
uv run ~/.claude/skills/ml-model-manage/scripts/ml_model_manage.py "$ACCESS_TOKEN" model-create \
  --name "Alpha SAC Actor" \
  --gid "o00000000000000000000004d" \
  --visibility VCObjectPrivate
```

```bash
uv run ~/.claude/skills/ml-model-manage/scripts/ml_model_manage.py "$ACCESS_TOKEN" model-update \
  --model-id "<MODEL_UUID>" \
  --name "Alpha SAC Actor v2" \
  --visibility VCObjectPublic
```

```bash
uv run ~/.claude/skills/ml-model-manage/scripts/ml_model_manage.py "$ACCESS_TOKEN" model-delete \
  --model-id "<MODEL_UUID>"
```

### Model versions

Local uploads only. The script enforces a `.pt` path.

```bash
uv run ~/.claude/skills/ml-model-manage/scripts/ml_model_manage.py "$ACCESS_TOKEN" version-upload \
  --model-id "<MODEL_UUID>" \
  --file path/to/model.ts.pt \
  --version "v5.1.6" \
  --description "SAC actor for the Alpha well" \
  --card-summary "Trained SAC actor for plunger lift optimization" \
  --card-uses "Production optimization on Alpha 1-1-1-1XH"
```

Optional card flags on upload:

- `--card-evaluation`
- `--card-datasets`
- `--card-metrics`
- `--card-categories` as comma-separated integers; defaults to `8`
- `--card-base-model`

```bash
uv run ~/.claude/skills/ml-model-manage/scripts/ml_model_manage.py "$ACCESS_TOKEN" version-export \
  --version-id "<VERSION_UUID>" \
  --out exported-model.zip
```

```bash
uv run ~/.claude/skills/ml-model-manage/scripts/ml_model_manage.py "$ACCESS_TOKEN" version-delete \
  --version-id "<VERSION_UUID>"
```

## Notes

- Parent model fields are `name`, `gid`, and `visibility`.
- Binary artifact changes should be a new version upload, not a version-metadata update.
- `model-update` and docs updates use a read-modify-write workflow so unspecified fields are preserved.
- Set `ONPING_BASE_URL` to target a non-production environment.
- **Version ordering matters:** OnPing picks up the semantically highest version. A new upload must have a version string that sorts higher than the current latest (e.g. if latest is `v6.1.3`, upload as `v6.1.4` or higher). A lower version like `v2.0.0` will be stored but not used. List existing versions first to find the current highest before uploading.
