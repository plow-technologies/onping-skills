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
- `calculateRetryStrategy`: `{"tag": "NoRetries"}`, the server default (control-parameters-types `ControlParameters/Types.hs`, `defaultRetryStrategy = NoRetries`); the older spelling `default` is also recognised
- `writeRetryStrategy`: `{"tag": "NoRetries"}`, as above
- `trigger`: `OnInputChangeAny`, on a create and an update alike. The server's friendly ToJSON omits it and the import reads a missing trigger back as `OnInputChangeAny` (onping-frontend-types `ControlParametersInferno.hs`), so this matches `/cpInferno/export/json`

`expand` fills a missing retry strategy with `{"tag": "NoRetries"}` (a fresh copy per CP).

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
- Parsed as the server parses it (`parseJSONFriendlyCPIDString`, `ControlParametersInferno.hs`): split on `-`, at least six parts, the last five must be a UUID (8-4-4-4-12 hex, either case) and the rest an integer engine host. Anything else is not a friendly CPID.
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

## cp-list Element Tags (`/cpInferno/list`)

Each element of a `cp-list` array is tagged (onping 2026.10.14.0, #16220):

| `tag` | `contents` | `normalize` / `fetch-normalize` | `validate` |
| --- | --- | --- | --- |
| `ReadableControlParameterInferno` | `{cpId, cpData}` | **unwrapped** to its `{cpId, cpData}` (friendly `cpId`, normalised `cpData`) | checked as a CP |
| `OrphanedControlParameterInferno` | `[{cpId, cpData}, [missing PID, ...]]` | **omitted** and listed on stderr (with any live output PIDs it still claims); unwrapped and kept with `--include-orphans` | `orphaned_cp` at the element path, with the missing PIDs (warning; error under `--strict`); its `cpData` is still checked |
| `ProhibitedReadControlParameterInferno` | CPID | dropped, listed on stderr | `not_readable` with the CPID (warning; error under `--strict`) |
| `FailedToReadControlParameterInfernoPermissions` | CPID | dropped, listed on stderr | `not_readable` with the CPID (warning; error under `--strict`) |
| any other tag, in a list array | anything | dropped, listed on stderr with the tag | `unknown_tag` (warning; error under `--strict`) |

An orphan means an output PID was deleted; it still holds its other outputs. Re-importing it as-is points at PIDs that do not exist, so the default normalised document leaves it out (BREAKING since skills 0.9.0: before, orphans were normalised like readable CPs). Repoint it through `/cpInferno/update` or delete it through `/cpInferno/delete` (neither is wrapped by a skill).

The `{cpId, cpData}` entry is a shape `/cpInferno/import` reads: `NewOrExistingControlParameterInferno2` takes an optional friendly `cpId` string and reads the CP fields from a nested `cpData` when there is one, or from the top level otherwise. `inferno-cp-import` accepts both. Only the wrapper is removed, and the result goes through one normalize pass, so nothing is normalised twice. A Readable or Orphaned element with no `cpData` object or no `cpId` is malformed: it is dropped and listed on stderr, `normalize` exits 1, and `validate` reports `malformed_element` (once; a malformed orphan is not also reported as `orphaned_cp`). A dropped element is removed, never left as `null`: left out of its array, or its key removed when it is a value under the root object. When the root itself is a dropped element, `normalize` outputs `[]`, says so on stderr, and exits 1. An unknown `{tag, contents}` wrapper counts as a list element only in the root array, an array under the root object (multi-Lumberjack output), or an array that also holds known elements; a tagged `outputs` or `trigger` inside a CP is a CP field.

An omitted orphan still claims its live output PIDs on the server. `normalize` lists them and warns when a kept CP writes one of them, because output exclusivity still applies until the orphan is repointed or deleted. (`validate` on the raw cp-list output checks the orphan's outputs with the others.)

Under `--strict`, `orphaned_cp`, `not_readable`, `unknown_tag` and `malformed_element` keep their own code; other warnings become `strict_warning`.

## Expansion (`expand`)

`expand` restores omitted defaults and converts friendly forms back to explicit JSON forms.

## Validation (`validate`)

Validation checks include:

- Required fields (`inputs`, `outputs`, `script`, `name`, `description`)
- Type checks for common CP fields
- Trigger format recognition
- CPID friendly-string parse warnings
- Output PID exclusivity warnings across CP entries
- `orphaned_cp` for each `OrphanedControlParameterInferno` element, with the missing PIDs
- `not_readable` for each `ProhibitedReadControlParameterInferno` / `FailedToReadControlParameterInfernoPermissions` element, with the CPID
