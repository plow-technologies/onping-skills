---
name: inferno-cp-import
description: Import Inferno (cpInferno/*) OnPing control parameters from a JSON array file via POST /cpInferno/import. addOrUpdate keyed by cpId — MUTATING, requires --yes. The write path for cp-list / cp-import-json. NOT the classic /cp/import (classic-cp-import).
allowed-tools: Bash(uv run *)
---

# Inferno Control Parameter Import

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> It creates Inferno control parameters (entries with no `cpId`) or overwrites existing ones matched by `cpId`. There is no undo; save the current definitions with `cp-list` (normalized by `cp-import-json`) first so an overwrite can be re-imported, and note that a created CP can only be removed through `cpInferno/delete`, which no skill here wraps. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Import **Inferno** control parameters into OnPing from a JSON file — the write path that `cp-list` (read) and `cp-import-json` (shape/validate) were missing. Mirrors the OnPing v3 web UI's import action on `/v3/inferno/control-parameters?ljSerial=<n>`: a single `POST /cpInferno/import` with a JSON array of CP objects as the request body (`Content-Type: text/plain;charset=UTF-8`).

> **Inferno, not classic.** This skill operates on the **Inferno** control-parameter engine (`cpInferno/*`) — the same engine as `cp-list` (`cpInferno/list`), `cp-script-fetch`, and `cp-import-json`. It is **not** the classic CP system (`/cp/*`) used by `classic-cp-import` / `classic-cp-export`.

> **Import is a MUTATION — addOrUpdate keyed by `cpId`.** An entry whose `cpId` matches an existing Inferno CP **overwrites** that CP (name, description, inputs, outputs, resolution, script, trigger); a new (non-matching) `cpId` creates one. The skill will not touch OnPing unless you pass `--yes`; the default and `--dry-run` only preview the affected cpIds.

> **Omitting `cpId` creates a new CP (verified live 2026-07-01).** If an entry has **no `cpId` field at all**, the server **mints** a `perEngineId`, **infers** the `engineHost`/ljSerial from the output PIDs, and creates a new **enabled** CP. `cpId` is therefore optional in the input; the preview groups cpId-less entries under `<create>`. There is **no Inferno CP undo** — an accidentally-created CP must be removed with `POST /cpInferno/delete` (body: `{"engineHost": <ljSerial>, "perEngineId": "<uuid>"}`, the structured `cpId` echoed in the import response).

> **`cpId` carries a Lumberjack serial.** Each `cpId` is `{ljSerial}-{uuid}` — the prefix identifies which Lumberjack the CP belongs to. The preview groups cpIds by ljSerial so an unintended serial is visible before applying. Confirm a Lumberjack's current CPs with `cp-list` and capture the prior definition (so an overwrite can be rolled back) before importing.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **cp-import-json** — Normalize, expand, and validate CP JSON (the upstream shape/validate step; produces the array this imports)
- **cp-list** — List Inferno CPs by Lumberjack (`cpInferno/list`); confirm current state / discover `cpId`s before overwriting
- **cp-script-fetch** — Resolve the `script` base64 hash referenced by each CP
- **classic-cp-import** — The **classic** `/cp/import` counterpart (Dhall body, keyed by outputPID) — a **different** engine; not what this imports

## When to Use

- **Push** a CP array you built/validated with `cp-import-json` into OnPing.
- **Restore / re-apply** an Inferno CP after capturing its definition from `cp-list`.
- **Bulk edit**: fetch with `cp-list` → edit the JSON → import back.

## Usage

Requires a valid access token and a JSON file containing an **array** of Inferno CP objects (from `cp-import-json`, `cp-list`, or hand-built).

**Preview (default — makes no network call):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/inferno-cp-import/scripts/import_inferno_cp.py "$ACCESS_TOKEN" --input cps.json
```

**Apply (actually imports — overwrites matching cpIds):**

```bash
uv run ~/.claude/skills/inferno-cp-import/scripts/import_inferno_cp.py "$ACCESS_TOKEN" --input cps.json --yes
```

**From stdin:**

```bash
cat cps.json | uv run ~/.claude/skills/inferno-cp-import/scripts/import_inferno_cp.py "$ACCESS_TOKEN" --yes
```

**Recommended round-trip — snapshot, then import an edit:**

```bash
# 1. Snapshot the target Lumberjack's current Inferno CPs (capture what you'll overwrite)
uv run ~/.claude/skills/cp-list/scripts/list_control_parameters.py "$ACCESS_TOKEN" 1001 > before.json
# 2. Build/edit the CP array (optionally via cp-import-json), then preview and import
uv run ~/.claude/skills/inferno-cp-import/scripts/import_inferno_cp.py "$ACCESS_TOKEN" --input cps.json           # preview
uv run ~/.claude/skills/inferno-cp-import/scripts/import_inferno_cp.py "$ACCESS_TOKEN" --input cps.json --yes     # apply
```

## Input Shape

A JSON array of CP objects. Each object requires `name`, `inputs`, `outputs`, `script`, `trigger`. `cpId` is optional — **present** ⇒ update/overwrite that CP, **absent** ⇒ create a new one (server-assigned id). `resolution` and `description` are also optional (the web-UI import body carries `resolution`, but the export round-trip format omits it):

```json
[{
  "cpId": "1001-00000000-0000-4000-8000-00000000c001",
  "description": "24hAvg: 500012 -> 500013",
  "inputs": [500012],
  "name": "Example Casing PSI Daily Avg",
  "outputs": {"average": 500013},
  "resolution": 1024,
  "script": "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF=",
  "trigger": "0 0 1/1 * *"
}]
```

- `cpId` — `{ljSerial}-{uuid}`; the `ljSerial` prefix picks the Lumberjack. **Omit to create** (server assigns it and infers the Lumberjack from the output PIDs).
- `inputs` — array of input PIDs.
- `outputs` — depends on the script's return type: a **bare PID integer** for a `ScalarOutput` script, or an **object** mapping output-slot name → PID for a `RecordOutput` script. (The server echoes it back tagged, e.g. `{"contents": 500015, "tag": "ScalarOutput"}`.)
- `script` — base64 script-content hash (resolve/inspect with `cp-script-fetch`).
- `trigger` — cron expression. `resolution` — integer (defaults to `2048` if omitted).

**Create example** (no `cpId`; a single-input `ScalarOutput` passthrough writing to PID 500015):

```json
[{
  "name": "passthroughRound2 test",
  "inputs": [500014],
  "outputs": 500015,
  "script": "GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG=",
  "trigger": "0 0 1/1 * *"
}]
```

The import response echoes the server-assigned `cpId` (`{"engineHost": 1001, "perEngineId": "<uuid>"}`); keep it if you need to update or delete the CP later.

## Flags

- `--input PATH` — JSON CP-array file to import (default: read from stdin).
- `--yes` — Perform the import. **Required** for any network call.
- `--dry-run` — Explicit preview; same as passing no flag (lists affected cpIds by ljSerial, makes no request). Wins over `--yes`.
- `--json` — Emit JSON instead of text.

## Output

- **Preview:** the `cpId`s that would be created/overwritten, grouped by `ljSerial`, each with its `name`/`trigger`/`resolution`, plus the addOrUpdate/overwrite warning; no request is sent; exit 0.
- **Apply:** the server's JSON result, or a failure diagnostic. Exit 0 only on success; non-zero on failure.

The success body is a JSON array of tagged-`Either` results, one per CP — `{"Right": {"cpData": {...}, "cpId": {"engineHost": <ljSerial>, "perEngineId": "<uuid>"}}}` on success (a `Left` would carry a per-CP error). The echoed `cpData` is the fully-expanded server view: `outputs` becomes a tagged `RecordOutput`, `trigger` a tagged `OnCronSchedule`, and an omitted `resolution` is defaulted (observed: `2048`). (Verified live 2026-07-01.)

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/cpInferno/import` | POST | `text/plain;charset=UTF-8` | JSON array of `{ name, inputs, outputs, script, trigger, cpId?, resolution?, description? }` (omit `cpId` to create) | JSON result on success |

The body is a JSON array exactly as the v3 UI sends it (the shape `cp-import-json` produces and `cp-list` returns per CP). Same Inferno engine as `cpInferno/list`.

## Authentication

`/cpInferno/import` accepts **Bearer token auth** from `onping-login` (verified live 2026-07-01), matching the sibling `cpInferno/list` used by `cp-list`. (The browser capture used a session cookie; bearer tokens are preferred for scripted use.)

## Error Handling

- **Malformed input** — the body must be a JSON array of objects each carrying the required fields; a non-array, an empty array, a missing field, or a malformed `cpId` fails fast (non-zero exit) before any request.
- **Duplicate cpIds in the file** — rejected in validation before sending; the skill refuses to import.
- **Token expired** — a redirect to `/auth/login` or an HTML login body fails fast (non-zero exit) and imports nothing.
- **Script type-check failure / non-2xx** — a rejected `script` hash or other non-2xx / error envelope is surfaced verbatim, exit non-zero, nothing imported. Observed live: an invalid `script` value returns **HTTP 400** with `{"error": "...Base64-encoded bytestring has invalid padding..."}` (the endpoint tries Dhall/JSON/YAML parsing, then base64-validates `script`).
