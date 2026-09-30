# Phase 1: Information Gathering

Discover the target pad's topology — every well, location, PID, and control parameter grouping on the shared Lumberjack. This phase produces a pad topology document that Phase 2 consumes.

## Steps

### 1. Authenticate

Use `onping-login` to exchange the refresh token for an access token.

```
ACCESS_TOKEN=$(onping-login)
```

All subsequent skills require this token as the first argument.

### 2. Search for the target well

Use `onping-search` with the well name. This returns company ID, site ID(s), and location ID(s).

```
onping-search $ACCESS_TOKEN "Well Name Here"
```

Record the **company ID** (CID) and **primary site ID** from the results.

### 3. Enumerate sites and locations

Fetch all sites under the company, then all locations under the target site(s).

```
onping-sites   $ACCESS_TOKEN $COMPANY_ID
onping-locations $ACCESS_TOKEN $SITE_ID
```

Build a location table with columns: Location Name, Location ID, IP Address, Slave ID.

### 4. Identify pad-mates

**This is the most important step.** A Lumberjack serves a *pad*, not a single well. Multiple wells on the same pad share one IP address but live under separate OnPing sites.

**How to find pad-mates:**

1. Note the IP address from your target well's locations (the `url` field).
2. Check `onping-search` results — alarm and HMI results often mention neighboring wells.
3. Fetch locations for neighboring sites from `onping-sites` and compare IP addresses.
4. Repeat until you've found every site with locations at the same IP.

> **Pitfall:** PIDs in the dhall file often belong to pad-mate wells on *different* OnPing sites. You cannot resolve all PIDs from the primary site alone. A dhall file may be named after one well but contain CPs for multiple wells across several sites, all sharing the same LJ IP. Always compare IP addresses across all sites under the company to find every pad-mate.

### 5. Find the Lumberjack ID

Use `lj-profile` with any location ID from the pad. The skill matches the location's IP against Lumberjack profile records.

```
lj-profile $ACCESS_TOKEN $LOCATION_ID
```

Record the Lumberjack ID from the `lumberjackId` field in the response.

### 6. Extract PIDs from the old dhall export

Collect every `outputPID` and every entry in `inputPIDs` lists from the dhall file. De-duplicate the combined set.

### 7. Resolve PIDs to descriptions

Fetch parameters for each location discovered in steps 3-4:

```
onping-parameters $ACCESS_TOKEN $LOCATION_ID_1 $LOCATION_ID_2 ...
```

Match each extracted PID against the `tagInfo.parameterId` field in the results. If PIDs remain unresolved after fetching the target site's locations, fetch parameters from pad-mate sites (step 4) until all PIDs are accounted for.

**Location types to watch for:**

| Location Pattern | Purpose | Typical PIDs |
| --- | --- | --- |
| `[Well Name]` | Main SCADA registers (pressures, levels, meters) | Standard ranges |
| `SCADA Data` | Setpoints and configuration | Standard ranges |
| `[Well Name] Remote` | Gas chromatograph analysis values | 871xxx range |
| `Calculated Parameters` | Virtual/calculated outputs | Standard ranges |
| `[Well Name] Plunger` | Plunger lift controller | Standard ranges |

> **Pitfall:** "Remote" locations hold gas chromatograph PIDs (871xxx range). These are the *inputs* for passthrough CPs. The remote meter number (e.g., "29", "293", "296") appears as a prefix in parameter descriptions.

### 8. Group CPs by script pattern and build topology doc

Categorize every CP from the dhall file by script pattern:

| Pattern | Identifying Trait | Typical stepSize | Typical Trigger |
| --- | --- | --- | --- |
| Passthrough | `output := latestInput(1);` | 2048 | OnInputChange |
| Constant | `output := <number>;` | 2048 | OnInputChange |
| Subtract (gas calc) | `(gWH - injection)\`0` with `isUnit` guard | 264 | OnInputChange |
| Epoch writer | `timeToInt(now + ...)` with DST logic | 2048 | OnCronSchedule |
| Custom | Anything else | Varies | Varies |

For each group, record: count, wells affected, script text, stepSize, trigger mode.

## Deliverable

A pad topology document containing:

- Well identification (company, site IDs, LJ ID)
- Location table per well (name, ID, IP, slave ID)
- Complete PID index (output PID, type, well, description)
- CP summary grouped by script pattern with counts
- Detailed per-group tables (output PID, input PID(s), description)

Previous migration directories in the same repo contain examples of this deliverable (e.g., `site-spec.org` files).
