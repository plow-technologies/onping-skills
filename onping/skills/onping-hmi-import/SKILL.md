---
name: onping-hmi-import
description: Import a full OnPing HMI dashboard from an exported Dhall file via POST /hmi/parse then POST /hmi/upsert. MUTATING, requires --yes. Overwrites the HMI whose dashId is in the file, or creates a copy with --new. Restore an onping-hmi-export backup or clone an HMI.
allowed-tools: Bash(uv run *)
---

# OnPing HMI Import

Import a full HMI dashboard into OnPing from a Dhall file produced by
`onping-hmi-export` — the write-back inverse of that export, and the way to
restore, migrate, or clone an HMI.

> **There is no `/hmi/copy` route.** OnPing has no public copy endpoint, so this
> skill reconstructs the two-step the web UI performs: `POST /hmi/parse` converts
> the Dhall to canonical JSON, then `POST /hmi/upsert` writes it. `--new`
> encapsulates cloning: it swaps `dashId` for a fresh UUID so the upsert creates
> a new HMI instead of overwriting.

> **Import is a MUTATION.** By default it **overwrites** the HMI whose `dashId`
> is in the file (same `dashId` = update in place). Nothing is written to OnPing
> unless you pass `--yes`. The default and `--dry-run` validate the Dhall via
> `/hmi/parse` and preview the target, but do not upsert.

> **`--dry-run` makes one read-only call.** Unlike `classic-cp-import` (which
> previews with no network call), this skill's preview calls `/hmi/parse` — a
> read-only, no-side-effect endpoint that type-checks the whole Dhall file and
> returns the authoritative `dashId`. This is what lets the preview show exactly
> which HMI would be overwritten (or the fresh id that would be created).

> **Dhall vs JSON key names.** The Dhall file uses `_dashId`; the JSON from parse
> (and consumed by upsert) uses `dashId`. The skill only ever reads/rewrites the
> JSON `dashId` — you never edit the Dhall by hand to clone.

> **⚠️ `_dashId` is the HMI UUID, NOT the `/v3/dashboards/{id}` URL.** This is the
> #1 cause of "the import ran but nothing changed." The `_dashId` in a Dhall file
> is the **HMI's own UUID** (a `xxxxxxxx-xxxx-...` UUID), which lives *inside* a
> dashboard panel. The id in a browser URL like
> `https://.../v3/dashboards/o00000000000000000000002a` is a **different thing** —
> the OnPing *dashboard container* key (a Mongo-style `o…` id), NOT an HMI UUID and
> NOT accepted by this skill. If you import a file whose `_dashId` points at a
> template (or any HMI other than the one in the URL you meant), the upsert writes
> to *that* HMI and the dashboard you were looking at shows no change. **Always
> confirm the file's `dashId` matches the HMI you intend to write** — see below.

> **To resolve a `/v3/dashboards/{urlId}` → the HMI UUID it contains:** call
> `GET /data/dashboard/list` (large JSON), find the entry whose `key == urlId`,
> and read `value.panels[].…HmiConfig.hmiDashboardUuid`. That UUID is the
> `dashId` you want in the file. (`GET /v3/dashboards/{urlId}` only returns the
> SPA HTML shell — it has no JSON body to parse.) Cross-check with
> `onping-hmi-list`, whose `hmiInfoDashboardName` is the *container* name.

> **Writing a layout into a DIFFERENT HMI than the file names.** There is no
> `--target` flag. To push a layout from file A into HMI B, rewrite `_dashId` in
> the Dhall (or `dashId` in the parsed JSON) to B's UUID before `--yes`, or use
> `--new` to mint a fresh HMI. **Caution:** a layout exported from a *template*
> also carries the template's data bindings (its `locationId`/`parameterId`
> values), so after such an import the widgets read the *template's* parameters,
> not the destination well's — you must re-point them (see `onping-hmi-import-data`,
> noting that an identity `[DataImport]` map does NOT remap template PIDs → well PIDs).

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-hmi-export** — Export a full HMI to Dhall (produces the file this imports — the round-trip)
- **onping-hmi-list** — Find HMI UUIDs to export/back up before importing
- **onping-hmi-import-data** — Import only the data-binding mappings (`[DataImport]`), not the full dashboard
- **onping-hmi-delete** — Soft-delete an HMI (e.g. clean up a `--new` copy)

## When to Use

- **Restore** an HMI from an `onping-hmi-export` backup after a mistaken change.
- **Clone** an HMI to a new dashboard: export → `import --new` (fresh `dashId`, source untouched).
- **Migrate / edit**: export → edit the Dhall → import back (overwrites in place).

## Usage

Requires a valid access token and an HMI Dhall file (from `onping-hmi-export`).

**Preview (default — validates via /hmi/parse, no upsert):**

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-hmi-import/scripts/import_hmi.py "$ACCESS_TOKEN" --input hmi.dhall
```

**Apply — overwrite the HMI whose dashId is in the file:**

```bash
uv run ~/.claude/skills/onping-hmi-import/scripts/import_hmi.py "$ACCESS_TOKEN" --input hmi.dhall --yes
```

**Clone — create a new HMI with a fresh dashId (source left untouched):**

```bash
uv run ~/.claude/skills/onping-hmi-import/scripts/import_hmi.py "$ACCESS_TOKEN" --input hmi.dhall --new --yes
```

**From stdin:**

```bash
cat hmi.dhall | uv run ~/.claude/skills/onping-hmi-import/scripts/import_hmi.py "$ACCESS_TOKEN" --yes
```

**Recommended round-trip — back up before overwriting:**

```bash
# 1. Back up the HMI you're about to change
uv run ~/.claude/skills/onping-hmi-export/scripts/export_hmi.py "$ACCESS_TOKEN" <uuid> --output before.dhall
# 2. Edit before.dhall as needed, then preview and import
uv run ~/.claude/skills/onping-hmi-import/scripts/import_hmi.py "$ACCESS_TOKEN" --input before.dhall          # preview
uv run ~/.claude/skills/onping-hmi-import/scripts/import_hmi.py "$ACCESS_TOKEN" --input before.dhall --yes    # apply
```

## Flags

- `--input PATH` — exported HMI Dhall file to import (default: read from stdin).
- `--new` — generate a fresh `dashId` and **create a copy** instead of overwriting.
- `--yes` — perform the upsert. **Required** for any write to OnPing.
- `--dry-run` — explicit preview; validates via `/hmi/parse` and shows the target, makes no upsert. Wins over `--yes`.
- `--json` — emit JSON instead of text.

## Output

- **Preview:** source `dashId`, target `dashId`, name, component count, and whether it would overwrite or create; validated via `/hmi/parse`; no upsert; exit 0.
- **Apply:** the created/updated `HmiDashboard` JSON from OnPing; exit 0 on success, non-zero on failure.

## API Reference

| Step | Endpoint | Method | Content-Type | Body | Response |
|------|----------|--------|--------------|------|----------|
| parse | `/hmi/parse/{nil-uuid}` | POST | `text/plain;charset=UTF-8` | Dhall `HmiDashboard` | JSON `HmiDashboard` (read-only validation; uuid ignored) |
| upsert | `/hmi/upsert` | POST | `application/json` | raw JSON `HmiDashboard` | JSON `HmiDashboard` (created/updated) |

`/hmi/upsert` consumes a **raw** `HmiDashboard` (not an `HmiUpsertRequest` wrapper); the server adds the caller's username. Same `dashId` overwrites; a different `dashId` creates.

## Authentication

All `/hmi/*` routes accept **Bearer token auth** from `onping-login` (verified). `parse` requires only authentication; `upsert` requires **Write** permission on the target `dashId`.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit) and imports nothing.
- **Malformed Dhall** — `/hmi/parse` returns a non-200 (or `{"error": ...}`); the skill surfaces it and imports nothing.
- **No Write permission on the target** — `/hmi/upsert` returns 403; surfaced verbatim, exit non-zero.
