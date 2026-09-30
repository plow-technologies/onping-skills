---
name: onping-mqtt-integrator-create
description: Create real OnPing locations and mqtt-json driver parameters from the integrator's uncreated candidates via POST /mqtt/json/integrator/{serial}/artifacts. MUTATES OnPing with --yes and there is NO UNDO. HTTP 200 does not mean success — the CreateArtifactsReport carries createLocationErrors/createPidErrors arrays and a run where everything failed still returns 200, so this skill exits non-zero when either is non-empty. Requires --location-url (the LJ's lumberjackUrl, from lj-profile) and a port defaulting to 2000 as the OnPing UI hardcodes. Not to be confused with .../artifacts/import, which creates nothing.
allowed-tools: Bash(uv run *)
---

# OnPing mqtt-integrator create

Turns the integrator's uncreated candidates into real OnPing locations and
mqtt-json driver parameters for one Lumberjack. This is the only skill in the
family that creates anything outside the integrator.

## The name collision, up front

| Route | What it does | Skill |
|---|---|---|
| `POST .../artifacts` | five-stage **create** of real objects | **this skill** |
| `POST .../artifacts/import` | repserts the integrator's own record; creates nothing | `onping-mqtt-integrator-artifacts-import` |

## Layer note

The **integrator** is the rule-based automation layer above the mqtt-json
**driver**. Integrator routes key on **`LJSerial`**; the driver skills key on
location refId. This skill is the seam between the two — it calls the driver's
`addMqttJsonLocation` and `addMqttJsonParameters` on your behalf. See
`_mqtt_integrator_routes/SKILL.md`.

## What actually happens

Five stages, server-side (`Service.hs`):

1. **integrator step-one** — filters blacklisted items, returns what to create
2. **mqtt-json driver** — `addMqttJsonLocation`, once per new location
3. **mqtt-json driver** — `addMqttJsonParameters`, once per location's PIDs
4. **integrator step-two** — records what was created
5. returns a `CreateArtifactsReport`

Real OnPing locations and real driver parameters come out the other end.

## Safety

- **Mutating, with no undo.** Nothing is created without `--yes`. Removing these
  afterward means deleting the driver location and the OnPing objects by hand —
  `onping-mqtt-integrator-delete --target stored` only makes the integrator
  *forget*, leaving the real objects orphaned.
- **Nothing is selected by default.** You must pass `--all` or name candidates
  explicitly. An empty request is refused rather than POSTed.
- `--dry-run` wins over `--yes`.
- `--list` browses candidates and needs no `--location-url`, so it is always safe.

## HTTP 200 does not mean success

The report carries `createLocationErrors` and `createPidErrors`. A run in which
**every single creation failed still returns 200** — the handler collects errors
into arrays rather than failing the request. This skill **exits 1** whenever either
array is non-empty, and prints the error text verbatim. That behavior is the main
reason to use it instead of curl.

Failures are partial, not transactional: locations and PIDs that succeeded are
created *and recorded*. Re-running retries only what is still uncreated.

## Two required inputs

| Field | Where it comes from |
|---|---|
| `--location-url` | the Lumberjack's own `lumberjackUrl` — get it from `lj-profile`. There is no integrator route that supplies it. |
| `--port` | the mqtt-json driver's listener port. Defaults to **2000**, which is what the OnPing UI hardcodes (`MqttJsonIntegrator_CreatableObjects.res`). |

## PIDs need their location in the same request

A PID whose location is neither already created nor included in this request is
**dropped silently** — step two can only map PIDs whose location resolved to a
refId, so there is no error and no creation. `--all` avoids this; a hand-picked
selection can hit it. The skill checks for it and warns before writing.

## Identifying candidates

Locations are named by their unique identifier. PIDs need three values, because
`PidUniqueIdentifier` is a two-field record rather than a scalar: the location
key, the topic, and the value selector. Pass them joined by `::`.

`--list` prints the exact flags to copy, and flags which candidates are
blacklisted (those are filtered server-side even with `--all`).

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
SKILL=~/.claude/skills/onping-mqtt-integrator-create/scripts/create_artifacts.py

# 1. See what is available (safe, no url needed):
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --list

# 2. Find the LJ's url:
uv run ~/.claude/skills/lj-profile/scripts/lj_profile.py ...

# 3. Preview creating everything:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --location-url 192.0.2.25 --all

# 4. Do it:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --location-url 192.0.2.25 --all --yes

# Create one location and one of its PIDs:
uv run "$SKILL" "$ACCESS_TOKEN" 1001 --location-url 192.0.2.25 \
  --location 'facility1-building2-sensor001' \
  --pid 'facility1-building2-sensor001::/sensors/TEMP001/data::.temperature' \
  --yes
```

### Inputs

- `access_token` — OnPing bearer token (from `onping-login`)
- `serial` — `LJSerial` of the Lumberjack running the integrator
- `--location-url URL` — the LJ's `lumberjackUrl` (required unless `--list`)
- `--port N` — driver listener port (default 2000)
- `--list` — show candidates and the exact selectors, then exit
- `--all` — every uncreated location and PID
- `--location KEY` — one location by unique identifier; repeatable
- `--pid 'LOCKEY::TOPIC::SELECTOR'` — one PID; repeatable
- `--json` — also print the raw report
- `--dry-run`, `--yes` — mutation gates

### Exit codes

- `0` — created with no errors
- `1` — any `createLocationErrors` / `createPidErrors` entry, an unknown
  selector, an empty selection, a missing `--location-url`, or a transport error

## Verify afterward

The integrator's record is **one-way and never re-checked** — it cannot confirm
these objects still exist. Verify independently:

```bash
uv run .../onping-pid-locate/scripts/... "$ACCESS_TOKEN" <pid>
uv run .../onping-export-mqtt-json/scripts/export_tags.py "$ACCESS_TOKEN" <refId>
```

## Source of truth

- Handler: `onping/Handler/MqttJsonIntegrator/Service.hs`
- Types: `mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs`
  (`CreateArtifacts`), `:1226` (`CreateArtifactsReport`)
- Frontend: `src/MqttJsonIntegrator/MqttJsonIntegrator_CreatableObjects.res`
- Route table: `_mqtt_integrator_routes/routes.py` (`create_artifacts`)

## Related skills

- `onping-mqtt-integrator-unprocessed --uncreated` — where candidates come from
- `onping-mqtt-integrator-reports` — run the rules to produce candidates
- `onping-mqtt-integrator-blacklist` — stop a candidate from ever being created
- `onping-mqtt-integrator-artifacts-export` — the record of what was created
- `onping-pid-locate`, `onping-export-mqtt-json` — verify the results
- `lj-profile` — find the `lumberjackUrl` for `--location-url`
