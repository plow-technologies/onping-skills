# Phase 2: Migration Planning

Map each old control parameter to a verified Inferno script with the correct output format. This phase produces a per-CP migration table that Phase 3 consumes.

## Steps

### 1. Authenticate

```
ACCESS_TOKEN=$(onping-login)
```

### 2. List existing Inferno CPs on the target Lumberjack

Use `cp-list` to see what's already on the LJ. This catches partial prior migrations and identifies output PID conflicts.

```
cp-list $ACCESS_TOKEN $LUMBERJACK_ID
```

Check `cpData.outputs` across all returned CPs — each output parameter ID is exclusive to a single control parameter (the **Output Exclusivity Rule**).

### 3. Categorize old script patterns

Using the Phase 1 topology document, group old CPs by script type. Common patterns:

| Pattern | Old Script | Inputs | Output Type |
| --- | --- | --- | --- |
| Passthrough | `output := latestInput(1);` | 1 input | Scalar |
| Constant | `output := 2.0;` | 1 input (trigger) | Scalar |
| Subtract | `(gWH - injection)\`0` | 2 inputs (ordered) | Scalar |
| Epoch writer (CST) | `timeToInt(now + offset)` with DST | 1 input (self-ref) | **Record** |
| 24h average | `average(input, hours(24))` | 1 input | Scalar |
| Custom | Varies | Varies | **Inspect script** |

### 4. Find matching Inferno scripts

**Use dynamic discovery as the primary approach.** Any already-migrated Lumberjack on the same account is a live source of verified Inferno script hashes.

**Discovery workflow:**

1. **Identify a reference LJ** — pick another Lumberjack on the same account that has already been migrated to Inferno CPs. If you don't know one, check with the operator or search via `onping-search`.

2. **List its CPs:**
   ```
   cp-list $ACCESS_TOKEN $REFERENCE_LJ_ID
   ```
   This returns every CP on that LJ with its script hash, inputs, outputs, trigger, and resolution.

3. **Match old patterns to reference CPs** — for each old script pattern from step 3, look for a CP on the reference LJ that performs the same computation. Compare the old script text to the reference CP's behavior.

4. **Fetch and verify the Inferno source:**
   ```
   cp-script-fetch $ACCESS_TOKEN $SCRIPT_HASH
   ```
   Read the Inferno source to confirm it does the same thing as the old script. Pay special attention to the return expression (scalar vs record — see step 6).

5. **Record the hash** — add verified hashes to your migration table with the output format determined from the script source.

If no reference LJ is available, check the common scripts table in `SKILL.md` as a starting point. If an old script pattern has no known Inferno equivalent on any LJ, flag it as needing a new script to be authored.

### 5. Verify each Inferno script

For every script hash you plan to use, fetch the source and confirm behavioral equivalence:

```
cp-script-fetch $ACCESS_TOKEN $SCRIPT_HASH
```

Read the Inferno source and compare to the old script. Document:

- What the script computes (e.g., "copies input to output", "subtracts input 2 from input 1, rounds to 0 decimals")
- How it handles missing inputs (e.g., returns `None`)
- Whether it matches the old script's behavior

### 6. Determine output format

> **CRITICAL:** This step prevents the most dangerous bug in CP migration — silent write failure. A mismatch between the script's return type and the `outputs` format causes the CP to run but never write values. There is no error message. (See `cp-import-json` for the epoch time writer case.)

**Decision procedure:**

1. Fetch the script source via `cp-script-fetch`.
2. Find the script's **final return expression**.
3. Choose the output format:

| Script returns | JSON `outputs` format | Example |
| --- | --- | --- |
| Bare scalar (e.g., `latestValue input0`, `2.0`, `subtractedParameter`) | `"outputs": PID` | `"outputs": OUTPUT_PID` |
| Single-field record (e.g., `{output = Time.timeToInt adjustedTime}`) | `"outputs": {"field": PID}` | `"outputs": {"output": OUTPUT_PID}` |
| Multi-field record (e.g., `{a = e1, b = e2}`) | `"outputs": {"a": pidA, "b": pidB}` | `"outputs": {"a": PID_A, "b": PID_B}` |

**Never guess from the CP name or from other CPs using a different script.** Always fetch the source via `cp-script-fetch` and inspect the return expression.

**Worked examples (common scripts):**

- **Identity** script returns `latestValue input0` (bare scalar) -> `"outputs": OUTPUT_PID`
- **Constant 2.0** script returns `2.0` (bare scalar) -> `"outputs": OUTPUT_PID`
- **subtractTwoParameters** script returns `subtractedParameter` (bare scalar via `match`) -> `"outputs": OUTPUT_PID`
- **totalflowEpochTimeWriter(CST)** script returns `{output = Time.timeToInt adjustedTime}` (single-field record) -> `"outputs": {"output": OUTPUT_PID}`

### 7. Check edge cases

For each CP, check whether any non-default configuration is needed:

| Edge Case | What to Check | Default Value |
| --- | --- | --- |
| Non-default resolution | Old `stepSize` != 2048 | `resolution: 2048` |
| Non-default trigger | Old schedule is cron or periodic, not OnInputChange | `trigger: OnInputChangeAny` (omitted) |
| Self-referencing PIDs | Input PID = output PID (common in epoch writers) | N/A — must preserve |
| Output PID exclusivity | Output PID already claimed by an existing CP on the LJ | N/A — must resolve conflict |
| Input ordering | Multi-input scripts where input order matters (e.g., subtract: input 1 - input 2) | N/A — order must match old script |
| OnInputChangeExcept | Old trigger excludes specific PIDs — must use tag/contents encoding in JSON (see Phase 3) | Rare — preserve if present |

### 8. Build per-CP migration table

For each CP, record:

| Field | Description |
| --- | --- |
| Output PID | The parameter written to |
| Input PID(s) | The parameter(s) read from (ordered for multi-input scripts) |
| Description | Human-readable name |
| Old script type | Passthrough, constant, subtract, epoch writer, etc. |
| Inferno hash | The verified script ID |
| Output format | Scalar (`PID`) or record (`{"field": PID}`) |
| Non-default fields | `resolution`, `trigger`, etc. — only if different from defaults |

## Deliverable

A migration plan document containing:

- Script inventory (old pattern -> Inferno hash -> Inferno name, with behavioral equivalence notes)
- Per-CP migration table with all fields from step 8
- Open items (expiring scripts, unresolved conflicts, new scripts needed)

Previous migration directories in the same repo contain examples of this deliverable.
