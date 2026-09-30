---
name: classic-cp-delete
description: Delete classic (legacy, non-Inferno) OnPing control parameters by CPID via POST /cp/delete. Use during CPID migration or teardown to remove — not just disable — an old classic CP. NOT for Inferno CPs (cpInferno/*).
allowed-tools: Bash(uv run *)
---

# Classic Control Parameter Delete

Delete classic (legacy, **non-Inferno**) control parameters on OnPing by CPID. This mirrors the **delete** action in the OnPing web UI's `/v3/control-parameter?cpid=<CPID>` page — a single `POST /cp/delete` with the bare CPID as the JSON body, one request per CPID.

> **Classic, not Inferno.** This skill operates on the **classic** control-parameter engine (`/cp/*`) — the same engine that `classic-cp-dhall` imports and exports. It is **not** the Inferno CP system (`cpInferno/*`) that `cp-list`, `cp-import-json`, and `cp-script-fetch` use. Do **not** use this skill to delete an Inferno control parameter.

> **Deletion is irreversible.** There is no undo for a removed classic CP. The skill will not touch OnPing unless you pass `--yes`; the default and `--dry-run` only preview. Before deleting during a migration, take a backup with `classic-cp-dhall export`.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **classic-cp-list** — List a Lumberjack's classic CPs (discover the CPIDs to delete)
- **classic-cp-by-pid** — Resolve outputPID → CPID (classic-CP Dhall files are keyed by outputPID; this deleter needs CPID)
- **classic-cp-export** — Back up classic CPs to Dhall before deleting (recommended)
- **classic-cp-import** — Restore a deleted/overwritten classic CP from a Dhall backup
- **classic-cp-dhall** — Import/export/disable classic CPs (same `/cp/*` engine)
- **cpid-migration** — Overall migration runbook (Phase 3 disables/removes old classic CPs)
- **cp-list** / **cp-import-json** — Inferno CP system (**different** engine — not what this deletes)

## When to Use

During a CPID migration or teardown, when you want an old **classic** CP **gone**, not just disabled:

- Disabling (via `classic-cp-dhall disable-all` + `import`) turns the old engine off but leaves the record in place.
- `classic-cp-delete` removes the record entirely.

Get the CPIDs from the web UI (`/v3/control-parameter?cpid=<CPID>`), a `classic-cp-dhall export`, or a migration plan.

## Usage

Requires a valid access token and one or more numeric classic CPIDs.

**Preview (default — makes no network call):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py "$ACCESS_TOKEN" 10001
```

**Apply (actually deletes — irreversible):**

```bash
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py "$ACCESS_TOKEN" 10001 --yes
```

**Batch** (one `POST /cp/delete` per CPID; a failure on one does not stop the rest):

```bash
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py "$ACCESS_TOKEN" 10001 10002 10003 --yes
```

**Recommended migration flow — back up, then delete:**

```bash
# 1. Back up the classic CPs first
uv run ~/.claude/skills/classic-cp-dhall/scripts/classic_cp_dhall.py \
  export "$ACCESS_TOKEN" --cpids 10001 10002 10003 --output classic-cps-backup.dhall
# 2. Delete them
uv run ~/.claude/skills/classic-cp-delete/scripts/delete_classic_cp.py \
  "$ACCESS_TOKEN" 10001 10002 10003 --yes
```

## Flags

- `--yes` — Perform the deletion. **Required** for any network call.
- `--dry-run` — Explicit preview; same as passing no flag (prints intended deletions, makes no request).
- `--json` — Emit JSON instead of a table.

## Output

- **Preview:** a table (or JSON with `--json`) of the CPIDs that *would* be deleted; no request is sent; exit 0.
- **Apply:** a per-CPID result — `deleted` or `FAILED — <error>`. Exit 0 only if every requested delete succeeded; exit non-zero if any failed.

## API Reference

| Endpoint | Method | Content-Type | Body | Response |
|----------|--------|-------------|------|----------|
| `/cp/delete` | POST | `application/json` | bare CPID integer (e.g. `10001`) | 2xx on success; JSON `{"error": ...}` envelope / non-200 on failure |

The body is the **bare CPID integer**, not an object or array — exactly what the UI sends. To delete multiple CPs, the skill loops the call once per CPID.

## Authentication

`/cp/delete` accepts **Bearer token auth** from `onping-login` (verified). Session cookies (as in browser network requests) also work, but bearer tokens are preferred for scripted use.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit) and reports no CPID as deleted.
- **Non-existent / already-deleted CPID** — OnPing returns a non-200 (observed: HTTP 500 with a JSON `error` envelope naming a downstream 404). Reported as a per-CPID `FAILED` with the raw response; other CPIDs still run.
- **A JSON `{"error": ...}` body on a 2xx** — treated as a failure for that CPID, not a success.
