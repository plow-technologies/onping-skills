---
name: lj-deploy
description: List, install, update, and monitor packages on Lumberjack edge devices via the OnPing mass deploy system. Use during CPID migration to ensure required Inferno packages are installed.
allowed-tools: Bash(uv run *)
---

# Lumberjack Deploy

> **⚠️ WARNING: this skill changes live data.**
> `update` and `delete` replace the complete package set on a Lumberjack edge device; any installed package left out of the set is uninstalled. Undo by running `lj-deploy update` with the previous store paths, so record them first with `lj-deploy installed`. Only `update` and `delete` write, and they preview by default and change nothing until you pass `--yes`.

List available packages, query installed packages, install or update packages, and monitor installation status on Lumberjack edge devices.

## Related Skills

- **onping-login** — Authenticate and get an access token
- **lj-profile** — Look up Lumberjack ID and architecture by location ID
- **cpid-migration** — Overall migration runbook (this skill is used in Phase 4)

## Commands

### packages — List available packages

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  packages "$ACCESS_TOKEN"
```

Filter by name substring:

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  packages "$ACCESS_TOKEN" --filter control-parameters
```

Returns JSON array of packages with store paths, names, versions, architecture, and layer.

### installed — List installed packages on a Lumberjack

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  installed "$ACCESS_TOKEN" 1001
```

Multiple serials:

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  installed "$ACCESS_TOKEN" 1001 1002 1003
```

Returns the full package set for each serial, including package names, versions, and store paths.

### update — Install or update packages on a Lumberjack

**MUTATING** — dry-run by default; requires `--yes` to actually POST.

`update` and `delete` both work by **set-replace**: they read the current installed set, compute the complete desired set, and POST it to `/lumberjack/deploy/package/install` (the same endpoint the OnPing v3 UI uses). They do NOT send per-package `edit` ops — those fail when a package's installed store-path hash differs from the deploy-server registry hash.

For each new store path, `update` matches it to an installed package by **name + architecture** (parsed from the store-path suffix) and swaps it in; if no such package is installed, it is appended as an add. All other installed packages are kept with their installed paths verbatim.

Dry-run (default) — prints the KEEP count, ADD/UPDATE old→new pairs, the full resulting `packages` array, and the `previously-installed-hash`, and makes no POST:

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  update "$ACCESS_TOKEN" 1001 "/nix/store/path1" "/nix/store/path2"
```

Confirm and apply with `--yes`:

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  update "$ACCESS_TOKEN" 1001 "/nix/store/path1" "/nix/store/path2" --yes
```

Idempotent: a path already installed verbatim is left in place unchanged.

Pipeline login and update (dry-run):

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
    update "$ACCESS_TOKEN" 1001 "/nix/store/path1" "/nix/store/path2"
```

### delete — Delete packages from a Lumberjack

**MUTATING** — dry-run by default; requires `--yes` to actually POST.

`delete` computes the desired set as the installed set MINUS each requested path, then POSTs the remainder via set-replace. Each requested path MUST match an installed store path **exactly** — if it does not, the command aborts and lists the installed paths (it never POSTs a partial or accidental full-set resend). Use `installed` first to copy the exact store path to remove.

Dry-run (default) — prints the KEEP count, the REMOVE list, the resulting `packages` array, and the `previously-installed-hash`, and makes no POST:

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  delete "$ACCESS_TOKEN" 1001 "/nix/store/path-to-remove"
```

Confirm and apply with `--yes`:

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  delete "$ACCESS_TOKEN" 1001 "/nix/store/path-to-remove" --yes
```

Set-replace is destructive-by-omission: anything not in the resulting `packages` array is uninstalled. The dry-run diff exists to let you confirm exactly what is being removed before passing `--yes`.

### status — Check installation status

```bash
uv run ~/.claude/skills/lj-deploy/scripts/lj_deploy.py \
  status "$ACCESS_TOKEN" 1001
```

Returns installation progress, success, or failure:
- `Installing` — in progress (shows done/total count)
- `InstallSucceeded` — all packages installed
- `InstallFailed` — installation failed
- `PackagesFailed` — some packages failed (lists which ones)
- `null` — no pending installation

## Typical Workflow (CPID Migration Phase 4)

```
1. Login (onping-login) -> access token
2. List installed packages (installed) -> check what's already on the LJ
3. List available packages (packages --filter <name>) -> find store paths for required packages
4. Update packages (update) -> install/update the required packages
5. Monitor status (status) -> wait for installation to complete
6. Verify (installed) -> confirm all required packages are present
```

### Required Packages for Inferno CP Engine

| Package | Purpose |
|---------|---------|
| `onping-pubsub` | MQTT pub/sub messaging |
| `control-parameters-engine` | Inferno CP runtime |
| `virtual-parameters-calc-inferno` | Inferno virtual parameter calculation |
| `inferno-vc-server` | Inferno version control server |
| `tachdb` | Time-series database |

## API Reference

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/lumberjack/deploy/packages` | GET | — | `[Package]` |
| `/lumberjack/deploy/packages/installed` | POST | `[LJSerial]` | `[{lumberjack-serial, packages, previously-installed-hash}]` |
| `/lumberjack/deploy/package/install` | POST | `{packages, lumberjack-serial, previously-installed-hash}` | queued/OK |
| `/lumberjack/deploy/package/status` | GET | `?serial=N` | `Maybe PackageSetInstallStatus` |

`delete` and `update` use `/lumberjack/deploy/package/install` (set-replace). The old per-package `/lumberjack/deploy/package/edit` route is **no longer used** by this skill — it failed with `MultiPackageEditPackageError` when the installed store-path hash differed from the registry hash. The `previously-installed-hash` for the POST is the `contents` value of the `status` response (the live optimistic-lock hash) — NOT the `installed` response's own `previously-installed-hash` field, which is stale for this purpose. Sending the wrong hash yields a safe `PackageInstallInstalledMismatch` rejection (no partial write).

## Key Pitfalls

1. **Architecture mismatch** — packages are architecture-specific (x86_64, aarch64, armv7l). Use `lj-profile` to find the LJ architecture, then filter `packages` output to match.
2. **Set-replace is destructive-by-omission** — `update`/`delete` POST the COMPLETE desired set; any installed path not in that set is uninstalled. The script builds the set by copy-minus/swap over the live `installed` response (never hand-assembled) and always shows a dry-run diff. Always review the REMOVE list before passing `--yes`.
3. **Kept packages use INSTALLED paths, not registry paths** — the installed store-path hash differs from the deploy-server registry hash for the same package+version+arch. The script keeps installed paths verbatim; only an added/updated package uses a registry path from the `packages` listing. Do not substitute a registry path for a package you intend to keep.
4. **Delete requires an exact installed store path** — a `delete` path must match an installed store path exactly, or the command aborts and lists the installed paths. Copy the path from `installed`. (Old versions no longer in the registry CAN now be removed — set-replace does not consult the registry for kept/removed packages, so the former "delete fails for old versions" failure is gone.)
5. **Async installation** — a successful `/package/install` POST means the request was queued, not that packages are installed. Poll `status` every 10 seconds until `InstallSucceeded` (typically 10–30 seconds). The first poll may return `null` while the LJ is being notified.
6. **Store paths are version-specific** — each package version has a unique Nix store path. To update to a newer version, use the store path from the `packages` listing.
