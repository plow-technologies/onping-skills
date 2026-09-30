---
name: cpid-migration
description: 5-phase runbook for migrating old-style control parameters to Inferno CP on OnPing Lumberjacks. Covers information gathering, migration planning, disabling old CPs, deploying packages, and JSON import creation.
---

# CPID Migration

Migrate old-style control parameters to the Inferno CP system on OnPing Lumberjacks. Follow the five phases in order — each produces a deliverable that feeds the next.

## Phases

| Phase | Doc | Goal |
|-------|-----|------|
| 1 | [01-information-gathering.md](docs/01-information-gathering.md) | Discover pad topology — wells, locations, PIDs, CP groupings |
| 2 | [02-migration-planning.md](docs/02-migration-planning.md) | Map each old script to a verified Inferno script with correct output format |
| 3 | [03-disable-old-cps.md](docs/03-disable-old-cps.md) | Disable old classic CPs before importing Inferno replacements |
| 4 | [04-deploy-packages.md](docs/04-deploy-packages.md) | Install required Inferno packages on the Lumberjack |
| 5 | [05-json-import-creation.md](docs/05-json-import-creation.md) | Build, validate, and import the JSON payload; verify post-import |

## Related Skills

- **onping-login** — Authenticate and get an access token (all phases)
- **onping-search** — Search OnPing entities by keyword (Phase 1)
- **onping-sites** — List sites for a company ID (Phase 1)
- **onping-locations** — List locations for site ID(s) (Phase 1)
- **onping-parameters** — List parameters for location ID(s) (Phase 1)
- **lj-profile** — Find Lumberjack profile by location ID (Phase 1)
- **cp-list** — List existing Inferno CPs on a Lumberjack (Phase 2)
- **cp-script-fetch** — Fetch Inferno script source by script ID (Phase 2)
- **classic-cp-dhall** — Disable/import/export classic CPs in Dhall format (Phase 3)
- **lj-deploy** — List, install, update, and monitor packages on Lumberjacks (Phase 4)
- **cp-import-json** — Normalize, validate, and expand CP JSON payloads (Phase 5)
- **inferno-cp-import** — Push the CP JSON array into OnPing (`POST /cpInferno/import`, addOrUpdate by cpId, requires `--yes`) (Phase 5)

## Script Discovery

The primary way to find Inferno script hashes is by querying already-migrated Lumberjacks with your OnPing token:

1. **Find a reference LJ** — any Lumberjack on the same account that has already been migrated to Inferno CPs.
2. **List its CPs** — `cp-list $ACCESS_TOKEN $REFERENCE_LJ_ID` returns all CPs with their script hashes, inputs, outputs, and triggers.
3. **Inspect script source** — `cp-script-fetch $ACCESS_TOKEN $SCRIPT_HASH` returns the Inferno source code. Read it to confirm behavioral equivalence with the old script you're migrating.
4. **Determine output format** — the script's return expression tells you whether `"outputs"` should be a bare PID (scalar return) or `{"field": PID}` (record return). Always verify this from the source.

This workflow replaces guessing from a static catalog. Any migrated LJ is a live source of verified script hashes.

### Common Scripts (quick reference)

These are frequently encountered across migrations. They were originally discovered via the workflow above.

| Old Pattern | Inferno Hash | Inferno Name | Output Format |
|-------------|-------------|--------------|---------------|
| `output := latestInput(1)` | `EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE=` | Identity | Scalar |
| `output := 2.0` | `HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH=` | Totalflow Save and Reset = 2.0 | Scalar |
| `(A - B)\`0` | `DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=` | subtractTwoParameters | Scalar |
| Epoch CST/CDT | `IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII=` | totalflowEpochTimeWriter(CST) | Record: `{"output": PID}` |

Do not rely solely on this table. Always verify hashes via `cp-script-fetch` before using them, and search reference LJs for scripts not listed here.

## Key Pitfalls

1. **Pad-mates**: A Lumberjack serves a pad, not a single well. Multiple wells share one IP but live under separate OnPing sites. You must discover all pad-mate sites to resolve all PIDs.
2. **Output format mismatch**: Scripts returning records (e.g., epoch writer) require `"outputs": {"field": PID}`, not bare `PID`. Mismatch causes silent write failure with no error message.
3. **Output PID exclusivity**: Each output parameter ID can only belong to one control parameter on a Lumberjack.
