---
name: event-table-import
description: Prepare OnPing event table Dhall configs for reward dashboard import. Use after output parameters are created.
allowed-tools: Read
---

# Event Table Import

Prepare Dhall event table configuration artifacts for OnPing dashboard import. Event tables display per-cycle reward metrics and SAC recommendations in a dashboard view.

## Related Skills

- **parameter-import** -- Create the output parameters that event table columns reference
- **onping-parameters** -- Verify PIDs exist before building the event table config
- **cp-list** -- Confirm ml-parameters are deployed and writing to output PIDs

## Template Location

`templates/ExampleEventTableAsTemplate.dhall`

This is an example well event table config, usable as a starting point for new wells.

## Dhall Structure

The template defines two column constructor functions:

### `mkEventColumn` (trigger column)
- Shows `LastUpdateDate` and `LastUpdateTime` (when the event fired)
- Does NOT show the result value
- Used for the reward trigger column (column 0) -- fires when the cycle detector writes a new reward value

### `mkResultColumn` (value column)
- Shows the `Result` (current parameter value)
- Does NOT show date/time
- Used for all metric columns (columns 1--15) -- displays the latest value from each output PID

### Column Layout

| Index | Type | Key Type | PID | Description |
|---|---|---|---|---|
| 0 | Event | PID | reward PID | Trigger: fires on reward update, shows date/time |
| 1 | Result | PID | reward PID | Reward value (same PID as trigger, shows value) |
| 2 | Result | PID | lifting_time PID | Lifting time (seconds) |
| 3 | Result | PID | afterflow_time PID | Afterflow time (seconds) |
| 4 | Result | PID | total_cycle_time PID | Total cycle time (seconds) |
| 5 | Result | PID | total_production PID | Total production (barrels) |
| 6 | Result | PID | production_rate PID | Production rate (barrels/hour) |
| 7 | Result | PID | plunger_arrived PID | Plunger arrived (boolean) |
| 8 | Result | PID | avg_tubing_psi PID | Average tubing pressure (psi) |
| 9 | Result | PID | avg_casing_psi PID | Average casing pressure (psi) |
| 10 | Result | PID | avg_flow_rate PID | Average flow rate (barrels/hour) |
| 11 | Result | PID | peak_casing PID | Peak casing before open (psi) |
| 12 | Result | PID | production_reward PID | Production reward component |
| 13 | Result | PID | arrival_reward PID | Arrival reward component |
| 14 | Result | VPID | off_time VPID | SAC recommended off time |
| 15 | Result | VPID | afterflow VPID | SAC recommended afterflow time |

> **Note**: Column 0 and column 1 reference the same PID (reward). Column 0 is the event trigger (date/time), column 1 is the result display (value).

> **Note**: Columns 14--15 use `VPID` key type (virtual parameter IDs) instead of `PID`. These reference the SAC actor's virtual parameter outputs.

### Top-Level Config Fields

```
eventTableUUID          -- Unique identifier for this event table (generate a new UUID per well)
eventTableDashboardId   -- OnPing dashboard ID where the table will appear
eventTableMaxEvents     -- Maximum rows displayed (FixedMaxEvents +24 = last 24 cycles)
eventTableEventColumn   -- Which column index triggers new event rows (+2 = column 0 by convention)
eventTableSortOrder     -- Desc = newest first
```

## Adapting for a New Well

1. **Read the template**:
   ```
   Read templates/ExampleEventTableAsTemplate.dhall
   ```

2. **Replace PIDs**: Substitute the template PIDs (200001--200013) with the new well's cycle detector output PIDs.

3. **Replace VPIDs**: Substitute VPIDs 200101 and 200102 with the new well's SAC actor virtual parameter IDs.

4. **Generate a new UUID**: Replace the `eventTableUUID` with a fresh UUID for the new well.

5. **Set the dashboard ID**: Replace `eventTableDashboardId` with the target OnPing dashboard's ID.

6. **Adjust max events** (optional): Change `FixedMaxEvents +24` if a different history depth is desired.

7. **Save** the adapted Dhall file to the well directory.

## Import to OnPing

Event table import is a **manual** step performed through the OnPing web interface. This skill only prepares the Dhall artifact.

## Error Handling

- If PIDs are incorrect, the event table will show stale or zero values. Verify all PIDs match the output parameters created via `parameter-import`.
- If the dashboard ID is wrong, the event table will not appear on the expected dashboard.
- If the UUID collides with an existing event table, OnPing may reject the import or overwrite the existing table.
