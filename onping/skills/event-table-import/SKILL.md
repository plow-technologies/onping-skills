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
- **onping-event-table-export** -- Export a live table as Dhall, to compare with or start from
- **onping-event-table-get** / **onping-event-table-fetch** -- Check an imported table's bindings, and confirm it renders

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
eventTableEventColumn   -- The eventColumnIndex of the trigger column (+0: the reward column)
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

> **The trigger is chosen by index, not by position.** OnPing makes the column
> whose `eventColumnIndex` equals `eventTableEventColumn` the trigger. The
> template's event column is `mkEventColumn +0`, so `eventTableEventColumn` is
> `+0`. Versions of this template before OnPing skills `0.3.0` set it to `+2`,
> which made column 2 (lifting time) the trigger.

## Import to OnPing

This skill only prepares the Dhall artifact; it does not call OnPing. The import
is usually done through the OnPing web interface.

OnPing also has a scriptable route, `POST /event/table/import`, but no skill
wraps it yet. It takes `multipart/form-data` with Yesod's auto-named fields:
`f1` is the Dhall file, `f2` is the target event-table UUID, and `f3` is the
dashboard id. The route overwrites the file's `eventTableUUID` and
`eventTableDashboardId` with `f2` and `f3`, and replaces the table named in `f2`
without a collision check. Any authenticated user can call it, and it validates
no PIDs (`onping/Handler/EventTable/Service.hs (postEventTableImportR)`).

To check an imported table, use `onping-event-table-get --bindings` and
`onping-event-table-fetch`.

## Error Handling

- If any PID or VPID in the table does not exist, the table renders nothing: OnPing fails the whole fetch with HTTP 500 `failed to lookup TagInfo for key: …`, naming only the first dead key. Verify all PIDs match the output parameters created via `parameter-import`, then confirm the table renders with `onping-event-table-fetch`.
- If the dashboard ID is wrong, the event table will not appear on the expected dashboard.
- `POST /event/table/import` does not check the UUID: it writes into the table named in `f2`, so reusing a UUID overwrites that table.
