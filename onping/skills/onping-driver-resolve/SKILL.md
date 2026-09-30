---
name: onping-driver-resolve
description: Resolve OnPing location refIds to their driver slug (read-only). Use to find which onping-update-<driver> / onping-add-<driver> skill applies to a bare location refId. Calls /singlewellextras/lister; does NOT mutate.
allowed-tools: Bash(uv run *)
---

# OnPing driver-resolve

Turns a bare location **refId** (or a batch of them) into its **driver slug**. Useful before running an `onping-update-<driver>` skill, since those are per-driver but you often start with just a location id.

It issues a single `POST /singlewellextras/lister` call, reads each location's stored `singleWellExtrasProtocol`, and maps it to the kebab-case driver slug (e.g. `ModbusFlexible` → `modbus-flexible`, `OPC_UA` → `opc-ua`, `TokuIntegration` → `toku`). **Read-only** — it makes no mutating call.

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-driver-resolve/scripts/resolve_driver.py \
  "$ACCESS_TOKEN" 20006 20007 20008
# JSON for piping into a batch wrapper:
uv run ~/.claude/skills/onping-driver-resolve/scripts/resolve_driver.py \
  "$ACCESS_TOKEN" 20006 --json
```

Output (table by default; `--json` for `{ "<refId>": {"driver", "protocol"} }`):

```
refId  driver
-----  ------------------------
20006  modbus-flexible
```

## Coverage and edge cases

- Resolves **20 of 21 drivers** in one call. A protocol string with no mapping (legacy `ROC107`, `ModBusRTU`, …) is reported verbatim as `legacy/unmapped`, never guessed into a slug.
- **sparkplug-bridge** is keyed by Lumberjack serial and is **not** stored in `single_well_extras`, so its locations never appear. Such a refId is reported as `unknown` with a hint to confirm via `POST /sparkplug/bridge/query`.
- The endpoint only returns locations in a group the **token user owns**. A not-owned location also comes back as `unknown` (same note). Unknowns do not fail the run (exit 0); only auth/HTTP/parse errors do.
- Auth-redirect / HTML fallthrough is detected (expired token → fail fast), like the other OnPing skills.

## Source of truth

- Endpoint: `POST /singlewellextras/lister` — handler `onping/Handler/Source/Location.hs`. Response: a list of `{key, value}` where `value.singleWellExtrasProtocol` is the discriminator and `value.singleWellExtrasLocationId` pairs it to the refId.
- Protocol→slug map: the `Protocol` ADT (`Onping/Types/Handler/Source/Location.hs`) + the mongo `single_well_extras.protocol` filters in onping-core. Do NOT use `/locations/withextras` for this — its `Protocol` value is lossy (collapses ~13 drivers to `ModBusRTU`).

If the protocol strings drift, re-verify against those sources and update `PROTOCOL_TO_SLUG` in the script.
