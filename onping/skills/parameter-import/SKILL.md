---
name: parameter-import
description: Prepare and document OnPing parameter creation for the canonical 36-parameter inferno ML deployment.
allowed-tools: Read, Bash(cp *)
---

# Output Parameter Import

Prepare the workbook used to create the canonical inferno ML parameter set on the OnPing ML Params location. This step must be completed before ml-parameter import (runbook doc 20).

## Related Skills

- **onping-login** -- Authenticate and get an access token
- **onping-parameters** -- Verify created PIDs exist after upload
- **lj-profile** -- Look up Lumberjack ID for a location
- **cp-list** -- List existing control/ml-parameters on a Lumberjack

## What the Template Contains

The file `templates/CombinedMLParameterTemplate.xlsx` defines the canonical **36-parameter** per-well layout:

### Shared inputs (2 parameters)

| Name | Description | Type |
|---|---|---|
| well_name_in | Well identifier string | Utf8_40Tag |
| operator_notes_in | Free-text operator observations | Utf8_184Tag |

### SAC actor outputs (10 parameters)

| Name | Description | Units |
|---|---|---|
| off_time_out | Recommended off time | minutes |
| afterflow_time_out | Recommended afterflow time | minutes |
| afterflow_critical_rate_out | Critical flow rate for afterflow termination | barrels/hour |
| offtime_differential_out | Casing-tubing pressure differential target | psi |
| sac_off_time_raw_out | Raw SAC off time before any LLM adjustment | minutes |
| sac_afterflow_raw_out | Raw SAC afterflow time before any LLM adjustment | minutes |
| confidence_out | LLM confidence in SAC action | 0-100 |
| llm_reward_out | LLM contextual quality score | -10 to 10 |
| operator_message_out | Human-readable LLM explanation | Utf8_184Tag |
| alert_pumper_out | Flag to alert pumper of anomaly | boolean |

### Cycle simulator outputs (9 parameters)

| Name | Description | Units |
|---|---|---|
| tubing_psi_out | Simulated tubing pressure | psi |
| casing_psi_out | Simulated casing pressure | psi |
| separator_psi_out | Simulated separator pressure | psi |
| flow_rate_out | Simulated flow rate | barrels/hour |
| line_psi_out | Simulated line pressure | psi |
| valve_status_out | Simulated valve state | boolean |
| well_status_out | Simulated well state | enum |
| time_out | Simulation time step | seconds |
| plunger_progress_out | Simulated plunger depth progress | fraction |

### Cycle detector outputs (15 parameters)

| Name | Description | Units |
|---|---|---|
| reward | Overall cycle reward score | dimensionless |
| lifting_time | Duration of lifting phase | seconds |
| afterflow_time | Duration of afterflow phase | seconds |
| total_cycle_time | Full cycle duration | seconds |
| total_production | Production volume for cycle | barrels |
| production_rate_per_hour | Hourly production rate | barrels/hour |
| plunger_arrived | Whether plunger surfaced | boolean |
| avg_tubing_psi | Average tubing pressure during cycle | psi |
| avg_casing_psi | Average casing pressure during cycle | psi |
| avg_flow_rate | Average flow rate during cycle | barrels/hour |
| peak_casing_before_open | Peak casing pressure before valve open | psi |
| production_reward | Production component of reward | dimensionless |
| arrival_reward | Arrival component of reward | dimensionless |
| off_time | Detected off-time for cycle | seconds |
| arrival_times | Plunger arrival timestamps | seconds |

**Total: 36 parameters** (2 shared inputs + 10 SAC outputs + 9 cycle simulator outputs + 15 cycle detector outputs).

## Canonical Workbook

`templates/CombinedMLParameterTemplate.xlsx` should match the canonical 36-row
workbook layout, which per-well workbooks follow:

- `wells_in_progress/<company>/<WELL_NAME>/<WELL>CombinedML_<MM_DD_YYYY>.xlsx`

Use that workbook as the reference shape for column order and parameter types.

## Step-by-Step

```bash
1. Copy the template to a working location:
   cp ~/.claude/skills/parameter-import/templates/CombinedMLParameterTemplate.xlsx <WELL_DIR>/

2. Open the xlsx and fill in the well-specific information:
   - Set location/site references for the target well
   - Assign PID numbers for all 36 parameters
   - Preserve Utf8_40Tag for `well_name_in`
   - Preserve Utf8_184Tag for `operator_notes_in` and `operator_message_out`

3. Upload the completed xlsx to OnPing:
   - Open the OnPing parameter import page
   - Upload the filled xlsx file
   - Confirm all 36 parameters are created

4. Verify creation using onping-parameters:
   ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
     uv run ~/.claude/skills/onping-parameters/scripts/fetch_parameters.py "$ACCESS_TOKEN" <ML_LOCATION_ID>
```

## Output

- 36 parameters created on the ML Params location
- Parameter set aligned with runbook docs 19 and 20
- Workbook ready for downstream ml-parameter import and event-table setup

## Error Handling

- If the xlsx upload fails, check that all required columns are populated and PID numbers are valid integers.
- If fewer than 36 parameters appear after upload, re-check the workbook for missing rows.
- If text-series parameters are missing or typed incorrectly, verify `operator_notes_in` and `operator_message_out` are configured as text fields.
- If PIDs already exist, verify they are not claimed by another ml-parameter using `cp-list` on the Lumberjack.
