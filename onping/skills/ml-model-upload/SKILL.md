---
name: ml-model-upload
description: Compatibility wrapper for older OnPing Inferno ML upload workflows. Prefer `ml-model-manage` for model lifecycle and uploads, and `ml-model-docs` for version metadata updates.
allowed-tools: Bash(uv run *)
---

# ML Model Upload

> **⚠️ WARNING: this skill changes live data.**
> `ml_model_create.py` creates an Inferno ML parent model and `ml_model_version_upload.py` uploads a new model version. Undo by deleting the created model or version with `ml-model-manage model-delete` or `version-delete`. Both act immediately: there is no preview and no confirmation.

This skill remains as a compatibility wrapper for the older create/list/upload workflow.

Prefer the new skills:

- `ml-model-manage` for parent model create/list/update/delete and local `.pt` version upload/export/delete
- `ml-model-docs` for version `description`, `version`, and model-card metadata updates

## Backward-Compatible Commands

These wrappers preserve the old script names and forward to `ml-model-manage`.

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/ml-model-upload/scripts/ml_model_list.py "$ACCESS_TOKEN"
```

```bash
uv run ~/.claude/skills/ml-model-upload/scripts/ml_model_create.py "$ACCESS_TOKEN" \
  --name "Alpha SAC Actor" \
  --gid "o00000000000000000000004d"
```

```bash
uv run ~/.claude/skills/ml-model-upload/scripts/ml_model_version_upload.py "$ACCESS_TOKEN" \
  --model-id "<MODEL_UUID>" \
  --file path/to/model.ts.pt \
  --version "v5.1.6" \
  --description "SAC actor for the Alpha well"
```

## Notes

- The old skill never covered update/delete/export correctly; use the new skills for those flows.
- “Documentation” updates now live in `ml-model-docs`, not this wrapper.
