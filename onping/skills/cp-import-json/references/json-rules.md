# CP Import JSON Rules

## Required Fields

These fields must always be present (never omitted):

- `inputs`, `outputs`, `script`
- `name`
- `description`

## Field Omission Defaults (`normalize`)

Omit these fields when they match default values:

- `resolution`: `2048`
- `enabled`: `true`
- `throttle`: `null`
- `calculateRetryStrategy`: `default`
- `writeRetryStrategy`: `default`
- `trigger`: `OnInputChangeAny`

## Friendly Output Representation

> **WARNING:** Always fetch the script source via **cp-script-fetch** before writing `outputs`. The format must match the script's return type. A mismatch causes silent runtime failure (CP runs, values never written).

**Decision procedure:**

1. Fetch the script source using **cp-script-fetch** with the script hash from `cpData.script`.
2. Find the script's final return expression.
3. Choose the output format:

| Script returns | Generic form | Friendly form |
| --- | --- | --- |
| Bare scalar (e.g. `x + 1`) | `{"ScalarOutput": pid}` | `pid` |
| Record (e.g. `{output = expr}`) | `{"RecordOutput": {"output": pid}}` | `{"output": pid}` |
| Multi-field record (e.g. `{a = e1, b = e2}`) | `{"RecordOutput": {"a": pidA, "b": pidB}}` | `{"a": pidA, "b": pidB}` |

**Examples:**

- **Passthrough script** (returns bare input value) → `"outputs": 500010`
- **Epoch time writer** (returns `{output = Time.timeToInt adjustedTime}`) → `"outputs": {"output": 500010}`
- **Multi-output script** (returns `{pressure = p, temperature = t}`) → `"outputs": {"pressure": 100, "temperature": 101}`

## CPID Representation

- Friendly format: `"{engineHost}-{perEngineId}"`
- `expand` parsing fallback: if friendly parse fails, keep original value as generic

## Trigger Representation

Friendly output forms:

- `OnInputChangeAny` -> omitted default
- `OnInputChangeOnly [pids]` -> `[pids]`
- `OnInputChangeExcept [pids]` -> keep generic object (tag/contents encoding)
- `OnCronSchedule(schedule, Nothing)` -> `"cron expr"`
- `Periodic seconds` -> numeric minutes

### CRITICAL: `Periodic` is SECONDS on the wire

The generic/wire `Periodic` value is in **seconds**, not minutes. The friendly numeric form
is in **minutes**, and `expand`/`normalize` multiply/divide by 60 across that boundary.
Confusing the two is a 60x scheduling error in either direction, and `validate` will **not**
catch it — both values are legal numbers.

| Friendly numeric | Wire form            | Actual rate    |
| ---------------- | -------------------- | -------------- |
| `1.6666666e-2`   | `{"Periodic": 1}`    | every 1 second |
| `1`              | `{"Periodic": 60}`   | every 1 minute |
| `60`             | `{"Periodic": 3600}` | every 1 HOUR   |

**To get "every minute" in a friendly export, write `"trigger": 1` — not `60`.** Writing
`60` there yields `Periodic 3600` and the CP silently runs hourly.

Conversely, a friendly `1.6666666e-2` is **one second**, not one minute — an exported CP
carrying that number is firing 60x per minute. Real observed failure mode: on one
Lumberjack, six filter-timer CPs were exported with `"trigger": 1.6666666666e-2` and were
hammering the engine at 1 Hz.

Note also that `Periodic 60` and `"* * * * *"` are **not** interchangeable. `Periodic` fires
60s after the engine last ran the CP and drifts; cron is phase-locked to the wall-clock
minute boundary. For CPs that read or report clock fields, prefer cron.

When in doubt, run `expand` and read the `Periodic` seconds value directly rather than
trusting the friendly number.

### Generic object encoding (tag/contents)

When a trigger is an object (not a string or array), it **must** use the **tag/contents encoding**. The importer does not accept plain nested object keys.

Correct (tag/contents):

```json
"trigger": {
  "contents": {
    "contents": [500011],
    "tag": "OnInputChangeExcept"
  },
  "tag": "OnInputChange"
}
```

Wrong (plain nested — will fail with `Could not parse trigger`):

```json
"trigger": {
  "OnInputChange": {
    "OnInputChangeExcept": [500011]
  }
}
```

This applies to any non-default `OnInputChange` variant. The outer object has `"tag": "OnInputChange"` and a `"contents"` object whose `"tag"` is the specific variant (`OnInputChangeExcept` or `OnInputChangeOnly`) and whose `"contents"` is the PID array.

## Expansion (`expand`)

`expand` restores omitted defaults and converts friendly forms back to explicit JSON forms.

## Validation (`validate`)

Validation checks include:

- Required fields (`inputs`, `outputs`, `script`, `name`, `description`)
- Type checks for common CP fields
- Trigger format recognition
- CPID friendly-string parse warnings
- Output PID exclusivity warnings across CP entries
