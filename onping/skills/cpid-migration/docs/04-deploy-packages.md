# Phase 4: Deploy Required Packages

Install or update the packages required for the Inferno control parameters engine on the Lumberjack. Run this phase **after** Phase 3 (disabling old classic CPs) and **before** Phase 5 (importing new Inferno CPs).

## Prerequisites

Before starting this phase, the operator must verify in the OnPing UI that the classic CPs were successfully disabled in Phase 3. Do not proceed until this is confirmed.

## Required Packages

| Package | Purpose |
|---------|---------|
| `onping-pubsub` | MQTT pub/sub messaging |
| `control-parameters-engine` | Inferno CP runtime |
| `virtual-parameters-calc-inferno` | Inferno virtual parameter calculation |
| `inferno-vc-server` | Inferno version control server |
| `tachdb` | Time-series database |

## Steps

### 1. Authenticate

```
ACCESS_TOKEN=$(onping-login)
```

### 2. Verify classic CPs are disabled (operator check)

**Ask the operator to verify** in the OnPing UI that the classic CPs imported in Phase 3 are disabled. This is a manual check — do not proceed until the operator confirms.

### 3. List currently installed packages

```
lj-deploy installed $ACCESS_TOKEN $LJ_SERIAL
```

Check which of the 5 required packages are already installed and at what version. Record the LJ architecture from the installed package metadata (e.g., `armv7l-linux`, `aarch64-linux`, `x86_64-linux`).

### 4. (Optional) Delete the old classic control parameters package

The old `single-well-control-parameters` package is no longer needed — it was the runtime for the classic CP engine disabled in Phase 3.

First, find its exact store path from the `installed` output (step 3). Then attempt to delete it:

```
lj-deploy delete $ACCESS_TOKEN $LJ_SERIAL "/nix/store/<single-well-control-parameters-store-path>"
```

The response should be `{"tag": "MultiPackageEditOK"}`. Monitor with `lj-deploy status` and wait for completion before proceeding.

> **Known limitation:** If the package version is old enough to no longer be in the deploy server's available packages registry, the delete will fail with `BuildPackageMissingPackageByIdentifier`. This is not blocking — the old package is harmless with its CPs disabled in Phase 3. Skip the delete and proceed to step 5.

### 5. Find store paths for missing or outdated packages

For each package that is missing or needs updating, find the correct Nix store path:

```
lj-deploy packages $ACCESS_TOKEN --filter <package-name>
```

Select the store path matching the Lumberjack's architecture. Each architecture has a different store path.

### 6. Update packages

Use the `Update` operation (idempotent — safe whether or not the package is already installed):

```
lj-deploy update $ACCESS_TOKEN $LJ_SERIAL "/nix/store/path1" "/nix/store/path2" ...
```

Pass all store paths in a single command. The response should be `{"tag": "MultiPackageEditOK"}`.

### 7. Monitor installation status

```
lj-deploy status $ACCESS_TOKEN $LJ_SERIAL
```

Possible responses:
- `{"tag": "Installing", "contents": ["hash", done, total]}` — in progress
- `{"tag": "InstallSucceeded", "contents": "hash"}` — complete
- `{"tag": "InstallFailed", "contents": "hash"}` — failed (investigate)
- `{"tag": "PackagesFailed", "contents": ["hash", [...]]}` — partial failure (lists failed packages)
- `null` — no pending installation

**Important:** `MultiPackageEditOK` means the request was *queued*, not that packages are installed. The first `status` poll may return `null` while the LJ is being notified via MQTT. Poll every 10 seconds until `InstallSucceeded` (typically completes within 10–30 seconds).

### 8. Verify installation

Re-run the installed packages check:

```
lj-deploy installed $ACCESS_TOKEN $LJ_SERIAL
```

Confirm all 5 required packages appear in the installed package set.

## Deliverable

No file artifact — verification is that all 5 required packages are present on the Lumberjack.

## Key Pitfalls

1. **Operator verification required** — do not proceed past step 2 without the operator confirming that classic CPs are disabled in the OnPing UI.
2. **Architecture mismatch** — packages are architecture-specific. Use `lj-profile` to confirm the LJ architecture, then select matching store paths from the `packages` output.
3. **Use Update, not Install** — the `Install` operation fails if the package is already installed. `Update` is idempotent.
4. **Delete requires exact store path** — the `Delete` operation needs the exact store path from `installed`, not from `packages`.
5. **Old package deletion may fail** — if `single-well-control-parameters` is an old version no longer in the deploy server registry, `Delete` returns `BuildPackageMissingPackageByIdentifier`. Safe to skip — the old package is harmless with CPs disabled.
6. **Async installation** — `MultiPackageEditOK` means queued, not installed. Poll `lj-deploy status` every 10 seconds until `InstallSucceeded` (typically 10–30 seconds). First poll may return `null`.
7. **Package versions** — always use the latest store paths from `lj-deploy packages`. Store paths encode the version.
