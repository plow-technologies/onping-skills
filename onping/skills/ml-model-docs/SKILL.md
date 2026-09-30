---
name: ml-model-docs
description: Update OnPing Inferno ML model-version documentation fields. Use when changing version description, version label, or model-card metadata such as summary, uses, datasets, metrics, categories, or base model.
allowed-tools: Bash(uv run *)
---

# ML Model Docs

Update the documentation layer of an OnPing Inferno ML model version without re-uploading the model artifact.

## Documentation Scope

This skill manages model-version metadata:

- `description`
- `version`
- model card `summary.evaluation`
- model card `summary.summary`
- model card `summary.uses`
- model card `metadata.categories`
- model card `metadata.datasets`
- model card `metadata.metrics`
- model card `metadata.base-model`

It preserves the existing binary `contents`, `size`, and untouched card fields by fetching the current version first and then updating only requested fields.

## Related Skills

- `onping-login` for access tokens
- `ml-model-manage` for parent model lifecycle and `.pt` uploads

## Commands

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/ml-model-docs/scripts/ml_model_docs.py "$ACCESS_TOKEN" show \
  --version-id "<VERSION_UUID>"
```

```bash
uv run ~/.claude/skills/ml-model-docs/scripts/ml_model_docs.py "$ACCESS_TOKEN" update \
  --version-id "<VERSION_UUID>" \
  --description "Updated production model for the Alpha well" \
  --version "v5.1.7" \
  --card-summary "Retrained SAC actor for plunger lift optimization" \
  --card-uses "Production optimization on Alpha wells" \
  --card-datasets "Alpha field run history" \
  --card-metrics "offline reward, constraint violations" \
  --card-categories "8,12"
```

Optional flags:

- `--card-evaluation`
- `--card-base-model`
- `--clear-base-model`

## Notes

- Use empty strings intentionally if a text field should be cleared.
- Use an empty string for `--card-categories` to clear the category list.
- This skill is for version metadata only. Use `ml-model-manage` for uploads, deletes, exports, and parent model updates.
