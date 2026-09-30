# Phase 5: JSON Import Creation

Build the import JSON payload from the Phase 2 migration table, validate it, import it, and verify the result. This phase produces the final validated import file and a post-import archive. Run this phase **after** Phase 4 (deploying required packages).

## Steps

### 1. Create the JSON file

Build one JSON entry per CP using the Phase 2 migration table. The JSON format follows the rules in the `cp-import-json` skill's `json-rules.md` reference.

**Required fields per entry:** `inputs`, `outputs`, `script`, `name`, `description`

**Omit fields that match defaults:**

| Field | Default (omit if equal) |
| --- | --- |
| `resolution` | `2048` |
| `enabled` | `true` |
| `trigger` | `OnInputChangeAny` |
| `throttle` | `null` |
| `calculateRetryStrategy` | `default` |
| `writeRetryStrategy` | `default` |

**Templates for common CP types:**

#### Passthrough (scalar output, all defaults)

```json
{
  "inputs": [INPUT_PID],
  "outputs": OUTPUT_PID,
  "script": "EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE=",
  "name": "<Well Short Name> GWH Meter <Description>",
  "description": "Passthrough: INPUT_PID -> OUTPUT_PID"
}
```

**Note:** The script hash here was discovered via `cp-list` on a reference LJ, then verified with `cp-script-fetch`. Always verify hashes before use.

#### Constant (scalar output, all defaults)

```json
{
  "inputs": [TRIGGER_PID],
  "outputs": OUTPUT_PID,
  "script": "HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH=",
  "name": "<Well Short Name> Save and Reset",
  "description": "Constant 2.0: TRIGGER_PID -> OUTPUT_PID"
}
```

#### Subtract (scalar output, non-default resolution)

```json
{
  "inputs": [GWH_PID, INJECTION_PID],
  "outputs": OUTPUT_PID,
  "script": "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=",
  "resolution": 264,
  "name": "<Well Short Name> Gas Calc (GWH - Injection)",
  "description": "Subtract: [GWH_PID, INJECTION_PID] -> OUTPUT_PID"
}
```

**Note:** Input order matters — input 1 is the GWH flowrate, input 2 is the injection flowrate. The script computes `input1 - input2`.

**Note:** `resolution: 264` is included because it differs from the default of 2048. Use the `stepSize` value from the old dhall CP.

#### Epoch writer (record output, cron trigger, self-referencing)

> **WARNING — Record Output:** This script returns `{output = Time.timeToInt adjustedTime}`, a single-field *record*. The `outputs` field **must** be `{"output": PID}`, not a bare PID. Using scalar format causes **silent runtime failure** — the CP runs on schedule but never writes a value. There is no error message.

```json
{
  "inputs": [PID],
  "outputs": {"output": PID},
  "script": "IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII=",
  "trigger": "0 0 1/1 * *",
  "name": "<Well Short Name> Epoch Time Writer CST",
  "description": "Epoch CST: PID -> PID"
}
```

**Note:** `trigger` is a cron expression (hourly) — included because it differs from the default `OnInputChangeAny`.

**Note:** Input PID = output PID (self-referencing). This is intentional — the script reads the current time, not the parameter value.

#### OnInputChangeExcept trigger (tag/contents encoding)

When a CP uses `OnInputChangeExcept` (fires on input change but excludes specific PIDs), the trigger **must** use the tag/contents encoding. The importer rejects plain nested object keys.

```json
{
  "inputs": [INPUT_PID_1, INPUT_PID_2],
  "outputs": OUTPUT_PID,
  "script": "SCRIPT_HASH=",
  "trigger": {
    "contents": {
      "contents": [EXCLUDED_PID],
      "tag": "OnInputChangeExcept"
    },
    "tag": "OnInputChange"
  },
  "name": "<Well Short Name> <Description>",
  "description": "<Type>: [INPUT_PID_1, INPUT_PID_2] -> OUTPUT_PID"
}
```

> **WARNING:** Do **not** use the plain nested form `{"OnInputChange": {"OnInputChangeExcept": [pid]}}` — it will fail with `Could not parse trigger`. The correct form wraps each level in `"tag"` / `"contents"` keys.

### 2. Naming convention

- **`name`**: `"<Well Short Name> <Description>"` — human-readable, identifies the well and what the CP does.
- **`description`**: `"<Type>: <inputs> -> <output>"` — machine-scannable, shows data flow direction.

Examples:

| Type | name | description |
| --- | --- | --- |
| Passthrough | `<Well> GWH Meter Heating Value` | `Passthrough: INPUT_PID -> OUTPUT_PID` |
| Constant | `<Well> Save and Reset` | `Constant 2.0: TRIGGER_PID -> OUTPUT_PID` |
| Subtract | `<Well> Gas Calc (GWH - Injection)` | `Subtract: [GWH_PID, INJ_PID] -> OUTPUT_PID` |
| Epoch writer | `<Well> Epoch Time Writer CST` | `Epoch CST: PID -> PID` |

### 3. Validate

Run the `cp-import-json` validation pipeline in order:

```
cp-import-json normalize  --input $JSON_FILE    # Normalize to friendly format
cp-import-json validate   --input $JSON_FILE    # Check required fields and types
cp-import-json validate   --input $JSON_FILE --strict   # Stricter checks (PID exclusivity, etc.)
```

**Common errors and fixes:**

| Error | Cause | Fix |
| --- | --- | --- |
| Missing required field | `name` or `description` omitted | Add the field |
| Duplicate output PID | Two entries write to the same PID | Remove the duplicate (check Phase 2 table) |
| Unknown trigger format | Malformed cron expression | Fix cron syntax (e.g., `"0 0 1/1 * *"`) |
| `Could not parse trigger` | Object trigger uses plain nested keys instead of tag/contents encoding | Convert to tag/contents format (see below) |
| Resolution as string | `"264"` instead of `264` | Remove quotes — must be integer |

### 4. Cross-check against migration table

Before importing, manually verify:

- [ ] **Entry count** — JSON entries == rows in Phase 2 migration table
- [ ] **Script hashes** — Every `script` value matches the Inferno hash from Phase 2
- [ ] **Output formats** — Scalar scripts use bare PID, record scripts use `{"field": PID}`
- [ ] **Non-default fields** — `resolution`, `trigger` present only where Phase 2 table says so
- [ ] **Input ordering** — Multi-input scripts (subtract) have inputs in the correct order (input 1 first)
- [ ] **Self-referencing PIDs** — Epoch writers have input PID == output PID

### 5. Import into OnPing

Authenticate and execute the import. (The exact import procedure depends on the available import endpoint or skill at the time of migration.)

### 6. Verify with fetch-normalize

After import, fetch the live CP configuration from the Lumberjack and compare:

```
cp-import-json fetch-normalize $ACCESS_TOKEN $LUMBERJACK_ID > post-import.json
```

Diff the normalized import file against the post-import fetch. Every entry in your import should appear in the fetched result. Differences may include:

- CPID fields (assigned by the system on import)
- Field ordering (cosmetic)

Structural mismatches (different script hash, wrong output format, missing entries) indicate an import problem.

### 7. Archive artifacts

Save all migration artifacts together:

| Artifact | Purpose |
| --- | --- |
| Old dhall export | Original CP definitions (before migration) |
| Pad topology document | Phase 1 deliverable |
| Migration plan | Phase 2 deliverable |
| Import JSON | The validated payload that was imported |
| Post-import JSON | Fetched from LJ after import, serves as ground truth |

## Deliverable

- Validated import JSON (the file that was imported)
- Post-import verification JSON (fetched from the Lumberjack after import)

Previous migration directories in the same repo contain examples of validated import JSON files.
