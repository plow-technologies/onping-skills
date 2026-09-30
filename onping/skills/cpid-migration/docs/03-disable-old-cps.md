# Phase 3: Disable Old Classic CPs

Turn off the old classic control parameter engine before importing Inferno replacements. This prevents both the old and new systems from writing to the same output PIDs simultaneously.

## Steps

### 1. Authenticate

```
ACCESS_TOKEN=$(onping-login)
```

### 2. Create the disabled Dhall file

Use `classic-cp-dhall disable-all` to create a copy of the original Dhall export with every CP set to `enabled = False`:

```
classic-cp-dhall disable-all --input original-cps.dhall --output original-cps-off.dhall
```

This is a local file operation — nothing changes in OnPing yet.

**Verify the output:**
- Confirm the total count matches the original (the command prints a JSON summary)
- Spot-check the output file to ensure all `enabled = True` entries are now `enabled = False`
- Entries that were already `enabled = False` in the original remain unchanged

### 3. Import the disabled Dhall into OnPing

```
classic-cp-dhall import $ACCESS_TOKEN --input original-cps-off.dhall
# or the standalone single-purpose skill (preview, then --yes):
classic-cp-import $ACCESS_TOKEN --input original-cps-off.dhall            # preview affected outputPIDs
classic-cp-import $ACCESS_TOKEN --input original-cps-off.dhall --yes      # apply
```

This calls `POST /cp/import` which **updates** existing classic CPs (matched by output PID). Each CP is set to `enabled = False`, which stops the old classic engine from executing them. (`classic-cp-import` also restores a `classic-cp-export` backup — the export↔import round-trip.)

**On success:** the endpoint returns a JSON array of `(ControlParameter, UpdateResponse)` tuples — one per CP. Verify the response count matches the expected number of CPs.

### 4. Verify old CPs are disabled

Verification options:

- **`classic-cp-list`** — list the Lumberjack's classic CPs directly (`POST /cp/list/by-lj-ident-key`, keyed by serial number) and confirm each shows `enabled = false`. This is the dedicated classic-CP list endpoint (the earlier note that none exists is superseded).
- Check the OnPing UI: navigate to the control parameter page for the Lumberjack and confirm all classic CPs show as disabled
- Re-export the CPs with **`classic-cp-export`** (if you have the CPIDs) and confirm `enabled = False` in the Dhall output

## Deliverable

- `{project}-control-parameters-off.dhall` — the disabled variant, archived alongside the original

## Optional: permanent removal (teardown, not this phase)

Disabling (above) is the correct action for the migration itself — it is reversible and preserves the rollback path. **Removing** the old classic CPs entirely is a separate teardown step, done only **after** the Inferno migration is confirmed stable and you no longer need the rollback.

When you reach that point, use **`classic-cp-delete`** to delete the old classic CPs by CPID (`POST /cp/delete`, the same `/cp/*` engine — **not** the Inferno CP system). Deletion is irreversible, so **export a backup first**:

```
# Back up, then delete (only after Inferno is confirmed stable)
classic-cp-export $ACCESS_TOKEN --cpids <CPID>... --output {project}-classic-cps-backup.dhall
classic-cp-delete $ACCESS_TOKEN <CPID>... --yes
```

## Key Pitfalls

1. **Import is addOrUpdate** — the import endpoint matches by output PID and overwrites the existing CP. The script text, inputs, schedule, and all other fields are preserved; only `enabled` changes.
2. **Do not delete old CPs in this phase** — disabling is reversible; deleting is not. Keep the original Dhall file so you can re-enable if the Inferno migration needs to be rolled back. Permanent removal via `classic-cp-delete` is a later teardown step (see "Optional: permanent removal" above), done only after the migration is confirmed stable and always with a `classic-cp-dhall export` backup.
3. **Order matters** — disable old CPs (this phase) *before* importing Inferno CPs (Phase 4). If both systems are active simultaneously, they may conflict on the same output PIDs.
