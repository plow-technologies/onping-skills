---
name: classic-cp-import
description: Import classic (legacy, non-Inferno) OnPing control parameters from a Dhall file via POST /cp/import. addOrUpdate keyed by outputPID — MUTATING, requires --yes. Restore a classic-cp-export backup. NOT for Inferno CPs (cpInferno/*).
allowed-tools: Bash(uv run *)
---

# Classic Control Parameter Import

Import classic (legacy, **non-Inferno**) control parameters into OnPing from a Dhall file — the write-back inverse of `classic-cp-export`. Mirrors the OnPing web UI's import action on `/v3/control-parameter`: a single `POST /cp/import` with the Dhall CP file as the request body (`Content-Type: text/plain;charset=UTF-8`).

> **Classic, not Inferno.** This skill operates on the **classic** control-parameter engine (`/cp/*`) — the same engine as `classic-cp-export`, `classic-cp-list`, and `classic-cp-delete`. It is **not** the Inferno CP system (`cpInferno/*`) used by `cp-list` / `cp-import-json`.

> **Import is a MUTATION — addOrUpdate keyed by `outputPID`.** An entry whose `outputPID` matches an existing classic CP **overwrites** that CP (script, inputs, schedule, stepSize, enabled); a new `outputPID` creates one. The skill will not touch OnPing unless you pass `--yes`; the default and `--dry-run` only preview the affected outputPIDs.

> **Cross-lumberjack outputPID reuse.** Output PIDs can be reused across lumberjacks (e.g. `400001` is written by a CP on serial 1001 *and* a different CP on serial 1002). Because import keys on outputPID, an import can overwrite a CP on a **different lumberjack** than the file came from. Confirm what each outputPID currently resolves to with `classic-cp-by-pid` / `classic-cp-list`, and **back up first** with `classic-cp-export`.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **classic-cp-export** — Export classic CPs to Dhall (produces the file this imports — the round-trip)
- **classic-cp-delete** — Delete classic CPs (import restores; delete removes)
- **classic-cp-by-pid** / **classic-cp-list** — Confirm which CP/lumberjack an outputPID currently resolves to before overwriting
- **classic-cp-dhall** — Import/export/disable classic CPs (same `/cp/*` engine; `import` is also a subcommand there)
- **cpid-migration** — Overall migration runbook (import the disabled variant / restore a backup)
- **cp-list** / **cp-import-json** — Inferno CP system (**different** engine — not what this imports)

## When to Use

- **Restore** a `classic-cp-export` backup after a mistaken change or delete.
- **Re-enable / edit** classic CPs: export → edit the Dhall (e.g. flip `enabled`, adjust `stepSize`/`schedule`) → import back.
- **Migration**: import a disabled variant to turn off the old engine before deploying Inferno replacements.

## Usage

Requires a valid access token and a Dhall CP file (from `classic-cp-export` or hand-edited).

**Preview (default — makes no network call):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/classic-cp-import/scripts/import_classic_cp.py "$ACCESS_TOKEN" --input cps.dhall
```

**Apply (actually imports — overwrites matching outputPIDs):**

```bash
uv run ~/.claude/skills/classic-cp-import/scripts/import_classic_cp.py "$ACCESS_TOKEN" --input cps.dhall --yes
```

**From stdin:**

```bash
cat cps.dhall | uv run ~/.claude/skills/classic-cp-import/scripts/import_classic_cp.py "$ACCESS_TOKEN" --yes
```

**Recommended round-trip — back up, then import an edit:**

```bash
# 1. Back up the CPs you're about to change (by their current CPIDs)
uv run ~/.claude/skills/classic-cp-export/scripts/export_classic_cp.py \
  "$ACCESS_TOKEN" --cpids 10001 10002 --output before.dhall
# 2. Edit before.dhall as needed, then preview and import
uv run ~/.claude/skills/classic-cp-import/scripts/import_classic_cp.py "$ACCESS_TOKEN" --input before.dhall            # preview
uv run ~/.claude/skills/classic-cp-import/scripts/import_classic_cp.py "$ACCESS_TOKEN" --input before.dhall --yes      # apply
```

## Flags

- `--input PATH` — Dhall CP file to import (default: read from stdin).
- `--yes` — Perform the import. **Required** for any network call.
- `--dry-run` — Explicit preview; same as passing no flag (lists affected outputPIDs, makes no request).
- `--json` — Emit JSON instead of text.

## Output

- **Preview:** the `outputPID`s that would be created/overwritten, a count, and the addOrUpdate/overwrite + cross-lumberjack-reuse warning; no request is sent; exit 0.
- **Apply:** the server's JSON result (a per-CP `(ControlParameter, UpdateResponse)` array), or a failure diagnostic. Exit 0 only on success; non-zero on failure.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/cp/import` | POST | `text/plain;charset=UTF-8` | Dhall `List` of `{ outputPID, inputPIDs, script, stepSize, schedule, enabled, token }` | JSON array of `(ControlParameter, UpdateResponse)` on success |

The body is the Dhall exactly as `classic-cp-export` emits it. To disable CPs before importing, use `classic-cp-dhall disable-all` to produce a disabled variant, then import it.

## Authentication

`/cp/import` accepts **Bearer token auth** from `onping-login` (verified). Session cookies (as in browser network requests) also work, but bearer tokens are preferred for scripted use.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit) and imports nothing.
- **Script type-check failure / non-200** — `/cp/import` type-checks each script; a malformed script (or other non-200 / error envelope) is surfaced verbatim, exit non-zero, nothing imported.
- **Duplicate outputPIDs in the file** — the endpoint rejects a file where two entries share an `outputPID`; the skill detects this in preview and refuses to send on `--yes`.
