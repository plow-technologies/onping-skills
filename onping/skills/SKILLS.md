# OnPing Skills

These skills provide access to the OnPing SCADA platform API and the Inferno scripting language documentation.

## Data Hierarchy

OnPing organizes data in a hierarchy: **Company → Sites → Locations → Parameters**. The skills below follow this chain, each requiring an access token from `onping-login`.

## Skills

### onping-login

Exchanges a stored refresh token for an access token via OAuth2. The refresh token is read from the `ONPING_REFRESH_TOKEN` env var, a plaintext `refresh_token` file, or a GPG-encrypted `refresh_token.gpg` file. The access token is required by all other OnPing API skills.

- **Script:** `onping-login/scripts/login.py`
- **Input:** None (reads refresh token automatically)
- **Output:** Access token string (JWT)

### onping-sites

Fetches the list of sites belonging to a company.

- **Script:** `onping-sites/scripts/fetch_sites.py`
- **Input:** `ACCESS_TOKEN COMPANY_ID`
- **Output:** JSON array of site objects (`name`, `refId`, `cid`, `pull`, `delete`)

### onping-locations

Fetches locations belonging to one or more sites.

- **Script:** `onping-locations/scripts/fetch_locations.py`
- **Input:** `ACCESS_TOKEN SITE_ID [SITE_ID ...]`
- **Output:** JSON array of location objects (`name`, `refId`, `site`, `company`, `url`, `slaveId`, `delete`)

### onping-parameters

Fetches parameters belonging to one or more locations. This is the final step in the hierarchy and returns live tag data including current values, descriptions, and writeability.

- **Script:** `onping-parameters/scripts/fetch_parameters.py`
- **Input:** `ACCESS_TOKEN LOCATION_ID [LOCATION_ID ...]`
- **Options:**
  - `--vp` — Include virtual parameters
  - `--vp-calc` — Include virtual parameters with calculated values
  - `--exclude-pid` — Exclude PID parameters
- **Output:** JSON array of parameter objects with `tagInfo` and `tagLocation`

### onping-pid-locate

Resolves a bare **PID** to its location, site, company, driver source, unit, writeability, and current value via `POST /json/listers/v3/parameters`. **Read-only.** This is the PID-first lookup the rest of the catalog lacks — `onping-parameters` needs a location *before* it can list parameters, and `onping-driver-resolve` needs a location refId, so this is usually the step that comes first when you start from an alarm, an audit record, or a control parameter's input/output PID. Also reads **virtual** parameters with `--vp`.

- **Script:** `onping-pid-locate/scripts/locate_pid.py`
- **Input:** `ACCESS_TOKEN PID [PID ...]` (batched; one request for PIDs, two for VPIDs)
- **Options:**
  - `--vp` — **Treat the given ids as VPIDs.** Sends tagged `VPID` keys, since a bare integer means PID and cannot address a virtual parameter, and fetches values from the location-scoped route (one extra request)
  - `--names` — Resolve site and company refs to names (2 extra calls)
  - `--json` — Emit JSON keyed by PID
  - `--output PATH` — Write to a file
- **Output:** Per-PID location refId + name, slaveId, url, site, company, source descriptor, unit, description, writeability, lastUpdate, and current value with its `OnPingResult` tag
- **Exit codes:** `0` resolved · `1` genuinely not found · `3` could not be addressed by key type · `4` resolved but value not computable. The split exists because a bare non-zero beside `NOT FOUND` reads as confirmation a parameter does not exist.
- **Read the SKILL.md before using.** Three route behaviors otherwise produce a confident wrong answer: a **missing PID is silent** — nonexistent, deleted, and not-visible-to-you are indistinguishable (`[99999999]` returns `[]`), so the skill reports every requested id with an explicit found state; **response order is not request order** (`[500001, 99999999, 500002]` came back `[500002, 500001]`), so results must be keyed by `parameterId` rather than zipped; and **a bare integer means `KeyPID`**, so a VPID must be sent as a tagged key and its value fetched from the location-scoped route — getting this wrong once reported four live wells as a dead control loop for 56 days.

### onping-search

Searches across all OnPing entities (sites, locations, parameters, etc.) by keyword. Useful for finding resources when you don't know exact IDs.

- **Script:** `onping-search/scripts/search.py`
- **Input:** `ACCESS_TOKEN QUERY`
- **Options:**
  - `--size N` — Number of results (default: 10)
  - `--from N` — Result offset for pagination (default: 0)
- **Output:** JSON search results

### Alarms

#### alarm-list

List alarm configurations from OnPing, optionally filtered by site, location, or company. Returns full alarm details including call order config, timing, and monitored parameter info.

- **Script:** `alarm-list/scripts/list_alarms.py`
- **Input:** `ACCESS_TOKEN [--site MONGO_KEY] [--location MONGO_KEY] [--company MONGO_KEY]`
- **Output:** JSON array of alarm objects (unwrapped from `Right` Either values)

#### alarm-call-order

List alarm call orders from OnPing, grouping alarms by their call order assignment. Shows which alarms belong to which notification group and who the recipients are.

- **Script:** `alarm-call-order/scripts/list_call_orders.py`
- **Input:** `ACCESS_TOKEN [--site MONGO_KEY] [--location MONGO_KEY] [--company MONGO_KEY]`
- **Output:** JSON object with `callOrders` (grouped by call order ID with `orderName`, `userNames`, and `alarms`) and `totalAlarms` count

### Control Parameters

#### cp-list

List control parameters for one or more Lumberjack IDs. Returns control parameter configuration including trigger mode, inputs, outputs, and script ID. Note: each output parameter ID is exclusive to a single control parameter.

- **Script:** `cp-list/scripts/list_control_parameters.py`
- **Input:** `ACCESS_TOKEN LUMBERJACK_ID [LUMBERJACK_ID ...]`
- **Output:** Raw JSON from `cpInferno/list` (single ID) or JSON object keyed by Lumberjack ID (multiple IDs)

#### cp-script-fetch

Fetch Inferno script payload for a control parameter script ID.

- **Script:** `cp-script-fetch/scripts/fetch_control_script.py`
- **Input:** `ACCESS_TOKEN SCRIPT_ID` (script ID is a base64-encoded string)
- **Output:** Raw JSON from `/script/id/{SCRIPT_ID}` with script source/history metadata

#### cp-import-json

Format and validate control-parameter JSON import payloads. Supports deterministic normalization (friendly JSON), expansion (explicit defaults), validation, and optional fetch+normalize by Lumberjack ID.

- **Script:** `cp-import-json/scripts/cp_import_json.py`
- **Input:** JSON via `--input` or stdin, or `ACCESS_TOKEN LUMBERJACK_ID [LUMBERJACK_ID ...]` for `fetch-normalize`
- **Subcommands:** `normalize`, `expand`, `validate`, `fetch-normalize`
- **Output:** Transformed JSON or machine-readable validation report (`ok`, `errors`, `warnings`, `stats`)
- **Note:** shapes/validates only — it does **not** write to OnPing. Use `inferno-cp-import` to push the resulting array.

#### inferno-cp-import

Import **Inferno** control parameters from a JSON array file via `POST /cpInferno/import` (the `cpInferno/*` engine — the write path for `cp-list` / `cp-import-json`, **not** the classic `/cp/import` used by `classic-cp-import`). Mirrors the v3 UI import on `/v3/inferno/control-parameters`: a JSON array of CP objects as the body (`Content-Type: text/plain;charset=UTF-8`). **Mutating — addOrUpdate keyed by `cpId`**: an entry whose `cpId` matches an existing Inferno CP **overwrites** it. No network call happens without `--yes`; the default and `--dry-run` only preview the affected cpIds grouped by `ljSerial` (the `{ljSerial}-{uuid}` prefix). Confirm current state with `cp-list` and capture the prior definition before overwriting.

- **Script:** `inferno-cp-import/scripts/import_inferno_cp.py`
- **Input:** `ACCESS_TOKEN`, JSON CP-array via `--input PATH` or stdin
- **Options:**
  - `--yes` — Perform the import (required for any network call)
  - `--dry-run` — Explicit preview (same as no flag; no request; wins over `--yes`)
  - `--json` — Emit JSON instead of text
- **Output:** Preview of affected cpIds by ljSerial (default), or the server's JSON result with `--yes` (exit non-zero on failure)

#### classic-cp-dhall

Import, export, and modify classic (legacy, non-Inferno) control parameters in Dhall format. Use during CPID migration to disable old CPs before importing Inferno replacements.

- **Script:** `classic-cp-dhall/scripts/classic_cp_dhall.py`
- **Input:** Varies by subcommand
- **Subcommands:**
  - `disable-all --input file.dhall --output file-off.dhall` — Create disabled copy (local only)
  - `import ACCESS_TOKEN --input file.dhall` — Import Dhall into OnPing (`POST /cp/import`)
  - `export ACCESS_TOKEN --cpids CPID... [--output file.dhall]` — Export CPs from OnPing (`POST /cp/export`)
- **Output:** JSON summary (disable-all), JSON import response (import), Dhall text (export)

#### classic-cp-delete

Delete **classic** (legacy, non-Inferno) control parameters by CPID via `POST /cp/delete` (the same `/cp/*` engine as `classic-cp-dhall`, **not** the Inferno CP system used by `cp-list` / `cp-import-json`). Mirrors the web UI delete action: bare CPID integer as the JSON body, one request per CPID. **Deletion is irreversible** — no network call happens without `--yes`; the default and `--dry-run` only preview. Back up first with `classic-cp-export`. If you only have outputPIDs (e.g. from a classic-CP Dhall file), resolve them to CPIDs with `classic-cp-by-pid`; to discover a Lumberjack's classic CPIDs, use `classic-cp-list`.

- **Script:** `classic-cp-delete/scripts/delete_classic_cp.py`
- **Input:** `ACCESS_TOKEN CPID [CPID ...]`
- **Options:**
  - `--yes` — Perform the deletion (required for any network call)
  - `--dry-run` — Explicit preview (same as no flag; no request)
  - `--json` — Emit JSON instead of a table
- **Output:** Preview table of CPIDs that would be deleted (default), or per-CPID `deleted`/`FAILED` results with `--yes` (exit non-zero if any failed)

#### classic-cp-list

List the **classic** (legacy, non-Inferno) control parameters on a Lumberjack via `POST /cp/list/by-lj-ident-key` (the `/cp/*` engine, **not** the Inferno `cp-list` / `cpInferno/*`). Read-only. Note the request contract differs from `cp-list`: the body is a **tagged identity key** (`{"tag":"IdentityKeySerialNum","contents":<serial>}`), not a bare Lumberjack ID — and the "serial" this endpoint wants may differ from the numeric Lumberjack ID used by `cp-list`/`lj-profile`. Each record carries both CPID and outputPID, so this is the discovery entry point that feeds `classic-cp-delete` (CPIDs) and complements `classic-cp-by-pid` (outputPID↔CPID).

- **Script:** `classic-cp-list/scripts/list_classic_cps.py`
- **Input:** `ACCESS_TOKEN SERIAL [SERIAL ...]`
- **Options:**
  - `--json` — Full per-CP records (object keyed by serial for a batch)
  - `--cpids-only` — Just the CPIDs, space-separated (pipe into `classic-cp-delete`)
  - `--enabled-only` — Filter to enabled CPs
- **Output:** Table per serial (cpid, outputPID, enabled, schedule, script preview) with a count; empty list is a clean exit 0

#### classic-cp-by-pid

Resolve a **classic** control parameter's **outputPID → CPID** via `POST /cp/by-pid` (the `/cp/*` engine, **not** Inferno). Read-only. Classic-CP Dhall exports (from `classic-cp-dhall export`) are keyed by `outputPID`, but `classic-cp-delete` needs the **CPID** — these are two distinct id spaces. This skill bridges them: give it the outputPIDs from a Dhall file and it returns the CPIDs to delete.

- **Script:** `classic-cp-by-pid/scripts/lookup_cp_by_pid.py`
- **Input:** `ACCESS_TOKEN OUTPUT_PID [OUTPUT_PID ...]`
- **Options:**
  - `--json` — Object mapping each outputPID to `{cpid, enabled, ...}` or a not-found marker
  - `--cpids-only` — Just the resolved CPIDs, space-separated (pipe into `classic-cp-delete`)
- **Output:** Table (outputPID, cpid, enabled, script preview); an outputPID with no classic CP is reported `not found` (cpid null), still exit 0

#### classic-cp-export

Export/back up **classic** control parameters to a Dhall file via `POST /cp/export` (the `/cp/*` engine, **not** Inferno). Read-only (no `--yes` gate). The **request is keyed by CPID**, but the returned **Dhall is keyed by `outputPID`** — resolve between them with `classic-cp-by-pid`. This is the recommended backup step before `classic-cp-delete`.

- **Script:** `classic-cp-export/scripts/export_classic_cp.py`
- **Input:** `ACCESS_TOKEN --cpids CPID [CPID ...]`
- **Options:**
  - `--output PATH` — Write the Dhall to this file (also printed to stdout; status line to stderr)
- **Output:** Dhall CP file (a `List` of records keyed by outputPID); the file is written only after a confirmed 200, so a failure never clobbers an existing backup
- **Round-trip:** the Dhall this emits is imported back by `classic-cp-import`.

#### classic-cp-import

Import **classic** (legacy, non-Inferno) control parameters from a Dhall file via `POST /cp/import` (the `/cp/*` engine, **not** the Inferno `cp-import-json` / `cpInferno/*`). The write-back inverse of `classic-cp-export` and the restore counterpart to `classic-cp-delete`. **Mutating — addOrUpdate keyed by `outputPID`**: an entry whose outputPID matches an existing classic CP **overwrites** it. No network call happens without `--yes`; the default and `--dry-run` only preview the affected outputPIDs. Output PIDs can be reused across lumberjacks, so an import may overwrite a CP on a different lumberjack — confirm with `classic-cp-by-pid` / `classic-cp-list` and back up with `classic-cp-export` first.

- **Script:** `classic-cp-import/scripts/import_classic_cp.py`
- **Input:** `ACCESS_TOKEN --input PATH` (or Dhall on stdin)
- **Options:**
  - `--yes` — Perform the import (required for any network call)
  - `--dry-run` — Explicit preview (same as no flag; lists affected outputPIDs, no request)
  - `--json` — Emit JSON instead of text
- **Output:** Preview of affected outputPIDs (default), or the server's `[ControlParameter, UpdateSucceeded]` array with `--yes` (exit non-zero on failure)

### HMI

Skills for backing up, restoring, cloning, and bulk-editing OnPing **HMI dashboards** via the `/hmi/*` routes, backed by the shared `_hmi_routes` module (route table + bearer-auth HTTP helpers with the same auth-redirect / HTML-fallthrough hardening as the driver families). All accept an access token from `onping-login`.

**Round-trip:** `onping-hmi-list` finds a UUID → `onping-hmi-export` backs it up to Dhall → `onping-hmi-import` restores or clones it. Data-only variants (`onping-hmi-export-data` / `onping-hmi-import-data`) move just the OnPing-parameter bindings, not the layout.

**Safety model:** the three read-only skills (`list`, `export`, `export-data`) have no `--yes` gate. The three mutating skills (`import`, `import-data`, `delete`) default to a preview and require `--yes` to write; `--dry-run` wins if both are passed. There is **no `/hmi/copy` route** — `onping-hmi-import --new` clones by parsing the Dhall to JSON, swapping `dashId` for a fresh UUID, and upserting. `delete` is a **soft** delete (sets `dashDeleted=true`). `/hmi/list` is scoped to HMIs on dashboard panels, so a freshly-upserted (e.g. `--new`) HMI is retrieved by its UUID, not listed.

#### onping-hmi-list

List the HMIs available to the user via `GET /hmi/list`. Read-only; the UUID discovery entry point for the other HMI skills.

- **Script:** `onping-hmi-list/scripts/list_hmis.py`
- **Input:** `ACCESS_TOKEN`
- **Options:** `--json` (raw array), `--uuids-only` (space-separated UUIDs, pipe into export/delete), `--panel-only`
- **Output:** Table of `UUID | NAME | PANEL | DASHBOARD` with a count on stderr; empty list exits 0

#### onping-hmi-export

Export/back up a **full** HMI dashboard (layout, components, settings, alerts) to Dhall via `GET /hmi/export/{uuid}`. Read-only; requires **Write** permission on the HMI. Written only after a confirmed 200 so a failure never clobbers a backup.

- **Script:** `onping-hmi-export/scripts/export_hmi.py`
- **Input:** `ACCESS_TOKEN UUID`
- **Options:** `--output PATH` (also prints to stdout; status line to stderr)
- **Output:** Dhall `HmiDashboard`; round-trips back through `onping-hmi-import`

#### onping-hmi-export-data

Export only an HMI's **data-binding mappings** (`[DataImport]`) to Dhall via `GET /hmi/export-data/{uuid}` — the OnPing parameters it reads, not the layout. Read-only; requires **Write**.

- **Script:** `onping-hmi-export-data/scripts/export_hmi_data.py`
- **Input:** `ACCESS_TOKEN UUID`
- **Options:** `--output PATH`
- **Output:** Dhall `[DataImport]`; round-trips back through `onping-hmi-import-data`

#### onping-hmi-import

Import a **full** HMI dashboard from an `onping-hmi-export` Dhall file. Because there is no `/hmi/copy` route, it does `POST /hmi/parse` (Dhall → JSON, read-only validation) then `POST /hmi/upsert` (raw JSON `HmiDashboard`). **Mutating** — overwrites the HMI whose `dashId` is in the file by default; `--new` generates a fresh `dashId` to create a copy (source untouched). No upsert without `--yes`; the default/`--dry-run` still make the one read-only `/hmi/parse` call to validate and preview the target `dashId`.

- **Script:** `onping-hmi-import/scripts/import_hmi.py`
- **Input:** `ACCESS_TOKEN`, HMI Dhall via `--input PATH` or stdin
- **Options:** `--new` (clone under a fresh `dashId`), `--yes` (required to write), `--dry-run` (preview; wins over `--yes`), `--json`
- **Output:** Preview of source/target `dashId` + overwrite-vs-create (default), or the created/updated `HmiDashboard` JSON with `--yes` (exit non-zero on failure)

#### onping-hmi-import-data

Import **data-binding mappings** into an existing HMI from a Dhall `[DataImport]` file via `POST /hmi/import-data/{uuid}` — re-points which OnPing parameters the target HMI reads, without changing layout. **Mutating**; no request without `--yes`; the default/`--dry-run` preview only (no network call).

- **Script:** `onping-hmi-import-data/scripts/import_hmi_data.py`
- **Input:** `ACCESS_TOKEN UUID`, Dhall via `--input PATH` or stdin
- **Options:** `--yes`, `--dry-run` (wins over `--yes`), `--json`
- **Output:** Preview of the target UUID + binding count (default), or the updated `HmiDashboard` JSON with `--yes`

#### onping-hmi-delete

Delete an HMI dashboard via `DELETE /hmi/delete/{uuid}`. **Soft** delete (sets `dashDeleted=true`; still GET-able). Requires **Delete** permission. **Mutating**; no delete without `--yes`; the default/`--dry-run` probe the HMI via `GET /hmi/{uuid}` to preview. Back up first with `onping-hmi-export`.

- **Script:** `onping-hmi-delete/scripts/delete_hmi.py`
- **Input:** `ACCESS_TOKEN UUID`
- **Options:** `--yes`, `--dry-run` (wins over `--yes`), `--json`
- **Output:** Preview of the target (default), or a soft-delete confirmation with `--yes` (exit non-zero on failure)

### Line Graph Widgets

Skills for reading, backing up, minting, restoring, cloning, and pid-remapping OnPing **line-graph widgets** (trend/chart panels embedded inside `/v3/dashboards/{id}`) via the `/content/widgets/line-graph/*` routes, backed by the shared `_line_graph_routes` module (route table + bearer-auth HTTP helpers with the same auth-redirect / HTML-fallthrough hardening as the driver / HMI families). All accept an access token from `onping-login`. Reference for the Dhall schema (record keys, `DisplayNameConfig` union boilerplate, colors, design patterns): [`onping-charts/skills/onping-line-graph/SKILL.md`](../../onping-charts/skills/onping-line-graph/SKILL.md).

**Round-trips:**
- Full-widget: `onping-line-graph-create` mints an id → `onping-line-graph-export` backs it up to Dhall → `onping-line-graph-import` restores or clones it (via `--new` for atomic mint + populate).
- Data-only: `onping-line-graph-export-data` dumps the pid bindings as a bare `[Field]` list → hand-edit `to` fields → `onping-line-graph-import-data` remaps pids without touching layout.

**Safety model:** the two read-only skills (`get`, `export`, `export-data`) have no `--yes` gate. The three mutating skills (`create`, `import`, `import-data`) default to a preview and require `--yes` to write; `--dry-run` wins if both are passed. `import` accepts Dhall passthrough or friendly `.json` / `.yaml` (both compile to the same Dhall on the wire — verified byte-identical server-side representations). `import --new` is a two-step (`POST /config` mints, `POST /import/#new-id` populates); on half-success the orphan id is printed with a clear cleanup note.

**⚠️ Two schema gotchas** — documented in every mutating SKILL.md:
1. `/import` consumes a Dhall RECORD (`ExportedLineGraphWidget`); `/import-data-only` consumes a Dhall LIST (`[Field]`). Feeding one to the other yields 400 `{"error": "Invalid Dhall.Decoder …"}`. Skills refuse locally at shape check.
2. `/import` server-side permission-checks every pid/vpid referenced in `yAxes`/`eventParameters`; a denied pid returns 400 `"Permission error for [<keys>]"` and the widget is not touched. `--dry-run` on `-import` prints the exact pid list the server will check.

**⚠️ No delete route.** `/content/widgets/line-graph/*` has 7 routes; DELETE is not one of them. A widget can only be removed as a side-effect of deleting its parent dashboard (`Handler/Delete/DeleteDashboard.hs`). A wrong `--new` or half-successful import leaves an orphan behind — clean up by removing the parent dashboard or leaving it.

**Widget id family:** Mongo-style `o…` ids (e.g. `o00000000000000000000002d`), assigned server-side by `POST /content/widgets/line-graph/config`. Discover a specific id via the containing dashboard's HmiConfig or the `/v3/dashboards/{id}` URL bar.

#### onping-line-graph-get

Read a line-graph widget as JSON via `GET /content/widgets/line-graph/widget/{id}`. Read-only; the fast inspection path. Wire-level `pid` is a bare integer (Dhall's `{type, value}` record is flattened on JSON serialization).

- **Script:** `onping-line-graph-get/scripts/get_line_graph.py`
- **Input:** `ACCESS_TOKEN WIDGET_ID`
- **Options:** `--output PATH`, `--pretty` (2-space indent, sorted keys)
- **Output:** JSON `LineGraphWidget`

#### onping-line-graph-export

Export a full line-graph widget to Dhall via `GET /content/widgets/line-graph/export/{id}` — a round-trip-friendly backup usable as `onping-line-graph-import` input.

- **Script:** `onping-line-graph-export/scripts/export_line_graph.py`
- **Input:** `ACCESS_TOKEN WIDGET_ID`
- **Options:** `--output PATH`
- **Output:** Dhall `ExportedLineGraphWidget`

#### onping-line-graph-export-data

Export a widget's pid bindings only as a Dhall `[Field]` list via `GET /content/widgets/line-graph/export-data-only/{id}` — a compact remap input for `onping-line-graph-import-data`. Distinct shape from `-export` (do not feed to `/import`).

- **Script:** `onping-line-graph-export-data/scripts/export_line_graph_data.py`
- **Input:** `ACCESS_TOKEN WIDGET_ID`
- **Options:** `--output PATH`
- **Output:** Dhall `[Field]`

#### onping-line-graph-create

Mint a fresh empty line-graph widget via `POST /content/widgets/line-graph/config`. Returns the new Mongo `o…` id. **Mutating**; no mint without `--yes`. The resulting widget is orphaned (not attached to a dashboard) — pair with `onping-line-graph-import` (or use `-import --new` directly) to populate.

- **Script:** `onping-line-graph-create/scripts/create_line_graph.py`
- **Input:** `ACCESS_TOKEN`
- **Options:** `--yes`, `--dry-run` (wins over `--yes`)
- **Output:** Preview of server defaults (default), or the new `LineGraphWidgetId` with `--yes`

#### onping-line-graph-import

Import a full line-graph widget from `.dhall` (passthrough) / `.json` / `.yaml` (friendly formats compiled to Dhall) via `POST /content/widgets/line-graph/import/{id}`. **Mutating** — overwrites the target widget in place; `--new` mints a fresh id via `POST /config` first and populates it (source untouched). `--dry-run` runs entirely locally (no `/parse` endpoint exists on line-graph widgets, unlike HMI) — validates the record shape and surfaces the pid list the server will permission-check.

- **Script:** `onping-line-graph-import/scripts/import_line_graph.py`
- **Input:** `ACCESS_TOKEN`, chart via `--input PATH` or stdin; `--id <widget-id>` OR `--new`
- **Options:** `--id`, `--new`, `--input`, `--input-format {dhall,json,yaml}`, `--yes` (required to write), `--dry-run` (wins over `--yes`), `--json`
- **Output:** Preview + pid list (default); the new id on `--new --yes`, or a status line on overwrite `--yes`. Exit 2 on shape errors in preview, exit 1 on server errors under `--yes`

#### onping-line-graph-import-data

Rewrite pid bindings on a line-graph widget via `POST /content/widgets/line-graph/import-data-only/{id}` — accepts a Dhall `[Field]` list (typically an edited `-export-data` output). **Mutating**; only pids on `yAxes`/`eventParameters` are updated, every other field is preserved. Unknown `from` keys are no-ops server-side.

- **Script:** `onping-line-graph-import-data/scripts/import_line_graph_data.py`
- **Input:** `ACCESS_TOKEN --id WIDGET_ID`, Dhall via `--input PATH` or stdin
- **Options:** `--yes`, `--dry-run` (wins over `--yes`), `--json`
- **Output:** Preview from→to mapping table (default), or a status line with `--yes`

### Custom Table Widgets

Skills for backing up, restoring, and recovering OnPing **custom-table widgets** (the spreadsheet-style panels embedded in `/v3/dashboards/{id}`) via the `/content/ctable/*` routes, backed by the shared `_ctable_routes` module (route table + bearer-auth HTTP helpers with the same auth-redirect / HTML-fallthrough hardening as the driver / HMI / line-graph families). The two HTTP skills accept an access token from `onping-login`; the two audit skills need **SSH access to the audit host and a VPN**, not a token.

**Round-trips:**
- Current state: `onping-ctable-export` backs a widget up to JSON → hand-edit → `onping-ctable-import` writes it back at the same ObjectId.
- Prior state: `onping-ctable-audit-history` finds the last good save → `onping-ctable-audit-export` decodes that version into a postable payload → `onping-ctable-import --yes` restores it.

**Safety model:** the three read-only skills (`export`, `audit-history`, `audit-export`) have no `--yes` gate; the two database skills issue SELECT statements only. `import` is the single mutating skill: it defaults to a preview, requires `--yes` to write, and `--dry-run` wins if both are passed. `audit-export` emits a **bare widget** unless `--as-envelope` is passed, so its output cannot be piped into a write by accident.

**⚠️ `import` is a whole-document replace with no merge step.** Posting a 12-cell widget to a 9,568-cell table leaves 12 cells and discards the rest. Run `onping-ctable-export` first — every SKILL.md in the family says so.

**⚠️ HTTP 200 does not mean the write happened.** `postCustomTableJsonR` answers a permission refusal with the bare JSON string `"insufficient permissions"` **and a 200 status**, so a client that tests the status code reports a restore that never occurred. `check_write_response` parses the body; only an echoed `{ctable, cid}` object counts as success.

**⚠️ `cTableId` is a query parameter, never a path segment.** The export route's path segment is a *download filename*, which is easy to misread. An id in the path returns `400 "No table id found"` — a message that reads like a missing widget and is actually a missing query parameter. A missing widget instead returns `null` with HTTP 200, so a naive client writes the four bytes `null` into a file and calls it a backup.

**⚠️ The audit trail is unreachable over HTTP for this model.** `CustomTableWidget` derives `NoIndex` and `auditGet` has no custom-table branch, so `POST /log/audit2/query` returns nothing at all — not an error. `onping-audit-pull --list-types` returns 30 types and not one is a custom table. Postgres over SSH is the only path, which is why the two audit skills take a host argument.

**Widget id family:** Mongo-style `o…` ids (e.g. `o000000000000000000000049`). The HTTP routes want the `o` prefix; the audit tables store the bare 24-hex in `original_id`. Every skill accepts either form and reports which interpretation it used — querying the wrong form returns **zero rows rather than an error**, which reads exactly like "no history exists".

**8 MiB body cap**, belonging to `POST /content/ctable/json` alone; every other OnPing route carries a different figure. `export` reports the payload as a percent of it and warns past 75%, because a widget that grows beyond the cap can no longer be restored through the API.

#### _ctable_routes (internal helper — do not invoke)

Shared transport and decoding for the `onping-ctable-*` skills.

- **Modules:** `_ctable_routes/routes.py` (route table, 8 MiB cap, widget key lists, `normalize_ctable_id`), `_ctable_routes/ctable_http.py` (bearer auth, auth-failure guard, `check_write_response`), `_ctable_routes/decode.py` (audit-row decoder and the four encoding guards)

#### _audit_db (internal helper — do not invoke)

Shared audit-postgres access for `onping-ctable-audit-history`, `onping-ctable-audit-export`, and `onping-audit-recover`. Credentials resolve **at run time** — `resolve_pg()` reads the postgres block from the deployed `onping-audit-server` config over SSH, so no password, username, or database name lives in this repository and a rotation needs no change here.

- **Modules:** `_audit_db/audit_db.py` (credential resolution, SSH transport, base64-safe query verbs, `add_common_args`), `_audit_db/ids.py` (conversion between the three forms of a mongo id)
- **Two topology facts it encodes:** the audit host is a **required argument** with no default (the wiki runbook this replaced hardcoded a now-NXDOMAIN name and a non-production IP), and **postgres binds to the database host's own address, not localhost** — a `localhost` connection is refused from the database host itself. The audit server and the database are different machines, and only the database host has `psql`.
- **Transfers are base64-encoded server-side.** `psql -tA` line-wraps and `COPY` tab-escapes; both were observed corrupting a 655 KB `cells` column. A result that does not re-parse is a hard failure, never a truncated return.

#### onping-ctable-export

Export a custom-table widget as JSON via `GET /content/ctable/json?cTableId=…` — title, headers, every cell, type, zoom, and the parent dashboard id. Read-only; the backup step before any import. Written **only** after a confirmed non-null object, so a failure never clobbers an existing backup.

- **Script:** `onping-ctable-export/scripts/export_ctable.py`
- **Input:** `ACCESS_TOKEN CTABLE_ID`
- **Options:** `--output PATH`, `--indent N` (omit for the compact form that round-trips byte-identically)
- **Output:** JSON `CustomTableWidget`; stderr summary of rows, columns, cells, dashboard id, bytes, and percent of the 8 MiB cap. A row-index gap is reported (indices are positional, so a gap renders as a blank row)
- **Exits:** 2 on a malformed id (no request issued), 1 on a `null` body, an expired token, or a non-200. `GET /does/content/ctable/json/exist` answers the existence question more cheaply

#### onping-ctable-audit-history

List every save of a custom-table widget from `custom_table_widget_audit` — row id, timestamp, author, action, and the byte lengths of the `cells` and `headers` columns. **Read-only, SELECT only.** Reaches history `POST /log/audit2/query` cannot see at all.

- **Script:** `onping-ctable-audit-history/scripts/ctable_audit_history.py`
- **Input:** `AUDIT_HOST CTABLE_ID`
- **Options:** `--limit N` (default 25), `--all`, `--tsv`, `--quiet-resolve`
- **Output:** `audit_id | edited_on | edited_by | action | cells_len | hdrs`, with the total count when truncated so a partial list is never mistaken for the whole history
- **Read `cells_len` first.** An edit moves it a little; a *replacement* moves it a lot. Versions whose length changes by 2× or more against the next-older row are flagged — the signature that identified the real incident (655,787 → 2,462,311, a 12-column liquid table replaced by a 23-column gas table under the same ObjectId). **The flag is advisory and never changes the exit code**, since a legitimate bulk edit can trip it
- **`length()`, not `array_length()`** — `headers` is `character varying`, not an array

#### onping-ctable-audit-export

Pull one `custom_table_widget_audit` row and decode it into the shape `POST /content/ctable/json` accepts. **Read-only, SELECT only.** Emits a bare widget by default so it cannot be posted by accident.

- **Script:** `onping-ctable-audit-export/scripts/ctable_audit_export.py`
- **Input:** `AUDIT_HOST AUDIT_ROW_ID` (the row id from `onping-ctable-audit-history`)
- **Options:** `--as-envelope CTABLE_ID` (wrap as `{ctable, cid}` for import; **off by default**), `--compare-live PATH` (assert key-set parity against an `onping-ctable-export` file), `--output PATH`, `--indent N`, `--quiet-resolve`
- **The four encodings, each with an assertion**, because every one was found by getting it wrong against real data:
  1. **The `s` prefix has exactly two homes** — `headers` and each cell's `desc`, and nothing else. `title` and `type` are stored raw. Stripping a character from `type` turns `customTable` into `ustomTable`, which failed on the first real run; the decoded `type` is now asserted to be null or exactly `customTable`
  2. **`dashboard` is `MongoIdUtf8NoO`** — hex of the ASCII id with the leading `o` removed. Raw hex names an unresolvable parent, and a widget whose parent will not resolve is unwritable through the API
  3. **Six `cellData` fields cannot round-trip** — `cellDataShowcompanyid`, `cellDataShowcompany`, `cellDataShowsiteid`, `cellDataShowsite`, `cellDataShowlocid`, `cellDataShowsourceid` emit as null. These are display toggles; the loss is in the schema, not in the skill. Indices, PIDs, VPIDs, status, description, and conditional formatting all survive
  4. **Sorting is forced to null** — a stored value re-sorts the table and renumbers every cell row index. The handler persists `Nothing` anyway, so null is both safe and faithful
- **Use `--compare-live` as the decoder's regression guard.** A missing cell key is silently dropped data rather than an error at post time. Field-verified 2026-08-26: row `600001` decoded to exact key parity with the live widget

#### onping-ctable-import

Write a `CustomTableWidget` back at an exact ObjectId via `POST /content/ctable/json` — a full-document mongo repsert (`DB.save` carrying an `_id`) and the only path that lets the caller choose the id. **MUTATING — requires `--yes`.** Also **audited**, recording `Create`/`Update` with your username, which the wiki's `mongo … custom.js` path is not.

- **Script:** `onping-ctable-import/scripts/import_ctable.py`
- **Input:** `ACCESS_TOKEN CTABLE_ID WIDGET_JSON` (a bare widget or a `{ctable, cid}` envelope — either is accepted)
- **Options:** `--yes` (required to write), `--dry-run` (**wins over `--yes`**), `--force` (permit a parent-dashboard change), `--verify-live`
- **Why this route and no other:** a custom table is referenced **only** by its mongo `_id` — the panel stores `cTableId`, the widget stores the reverse pointer, and neither side carries a name or slug. `POST /content/ctable/config` mints a server-generated id, and the XLSX import at `/content/ctable/import` rewrites only headers and cells while dropping title, zoom, and sorting
- **Four local refusals, each a way this route quietly ruins a widget:** a **null `customTableWidgetDashboard`** (permission is read from the dashboard the widget names, so a widget naming none becomes **permanently unwritable through the API** — one bad post is enough); a **differing dashboard** without `--force` (retargeting silently moves who can edit it); a **non-null `customTableSortingInformation`**; and an **oversize body**, measured locally rather than after uploading 8 MiB. Also checked: the four `.:`-parsed keys must be present, and every `cellDataRow`/`cellDataCol` must be a non-negative integer (a row gap warns, not refuses)
- **Verification is not optional.** After a write the skill re-reads the widget and compares all 7 scalar fields individually plus every cell by `(row, col, pid, vpid, desc)`; any difference exits non-zero, because a silent partial write is worse than a reported failure. `--verify-live` additionally calls `/api/customtabledata/get` and reports how many parameters resolved to current values — the difference between "the PIDs are present" and "the PIDs are reporting"
- Field-verified 2026-08-26: 2,544 cells posted and read back identical, 1,906 of 1,906 parameters resolved live, and the audit row the write produced carried the same `length(cells)` as the source row — independent proof the round trip is lossless

### Lumberjack

#### lj-deploy

List, install, update, and monitor packages on Lumberjack edge devices via the OnPing mass deploy system. Use during CPID migration to ensure required Inferno packages are installed.

- **Script:** `lj-deploy/scripts/lj_deploy.py`
- **Input:** Varies by subcommand
- **Subcommands:**
  - `packages ACCESS_TOKEN [--filter NAME]` — List available packages
  - `installed ACCESS_TOKEN SERIAL [SERIAL ...]` — List installed packages on LJ(s)
  - `update ACCESS_TOKEN SERIAL STORE_PATH [STORE_PATH ...]` — Install/update packages
  - `delete ACCESS_TOKEN SERIAL STORE_PATH [STORE_PATH ...]` — Delete packages
  - `status ACCESS_TOKEN SERIAL` — Check installation status
- **Output:** JSON (package lists, install response, or status)

#### lj-profile

Look up Lumberjack profiles by OnPing location ID. Matches the location's IP address against Lumberjack profile fields to find the associated profile (which contains the Lumberjack ID needed by `cp-list`).

- **Script:** `lj-profile/scripts/lj_profile.py`
- **Input:** `ACCESS_TOKEN LOCATION_ID [LOCATION_ID ...]`
- **Output:** Matched profile JSON (single ID) or JSON object keyed by location ID (multiple IDs)

### Lumberjack Restore (`lumberjack-restore/`)

Skills for listing and restoring lumberjack backups from S3 via the lumberjack-restore-server running on edge devices. These skills talk directly to the device (no OnPing auth required), but use `lj-profile` or `onping-locations` to discover the device IP.

#### lj-restore-list

List lumberjack folders that have backups available on a device.

- **Script:** `lj-restore-list/scripts/list_lumberjacks.py`
- **Input:** `IP [--port PORT]`
- **Output:** JSON array of folder names (e.g. `["lumberjack-1001/", "lumberJack-1002/"]`)

#### lj-restore-backups

List available backup files for a specific lumberjack ID on a device.

- **Script:** `lj-restore-backups/scripts/list_backups.py`
- **Input:** `IP LJ_ID [--port PORT]`
- **Output:** JSON array of backup filenames

#### lj-restore-run

Trigger a restore operation for a specific backup file. **Destructive:** stops services and overwrites state on the device.

- **Script:** `lj-restore-run/scripts/restore.py`
- **Input:** `IP FOLDER FILENAME [--port PORT]`
- **Output:** Server response text

### Virtual Parameters

#### vp-scripts

List all virtual parameter scripts in OnPing. This is the discovery entry point for browsing VP scripts.

- **Script:** `vp-scripts/scripts/list_scripts.py`
- **Input:** `ACCESS_TOKEN`
- **Output:** JSON array of all VP script objects

#### vp-show

Show configuration details for a virtual parameter by ID, including name, inputs, and script reference.

- **Script:** `vp-show/scripts/show_vp.py`
- **Input:** `ACCESS_TOKEN VP_ID`
- **Output:** JSON object with VP configuration (name, inputs, script reference, etc.)

#### vp-script-fetch

Fetch the actual Inferno script code for a virtual parameter by its script ID.

- **Script:** `vp-script-fetch/scripts/fetch_script.py`
- **Input:** `ACCESS_TOKEN SCRIPT_ID` (script ID is a base64-encoded string)
- **Output:** JSON object containing the Inferno script content

### Deployment Artifacts

The `ml-*` skills share the `_inferno_ml_routes` module (the `/inferno/ml/*` API layer: bearer-auth HTTP with 502/503/504 retry, model + model-version CRUD, and the inference-parameter helpers). All accept an access token from `onping-login`; set `ONPING_BASE_URL` for non-production.

#### ml-parameter-export

Export one or more OnPing inference (ml-) parameters as portable JSON via `POST /inferno/ml/inference/export`. Read-only despite being a POST — no `--yes`. Output is flat and import-shaped, and is the **only** route that returns `itype` (the `{device, cap}` EC2 instance sizing). Two gotchas documented in SKILL.md: the route **silently omits** ids it cannot serve (hence `--strict` by default, which fails and writes nothing rather than let a partial export pass as complete), and the flat export shape is NOT interchangeable with `ml-parameter-update get`'s nested runtime envelope.

- **Script:** `ml-parameter-export/scripts/ml_parameter_export.py`
- **Input:** `ACCESS_TOKEN UUID [UUID ...]` or `--stdin-ids`; flags `--output`, `--pretty`, `--unwrap-single`, `--strict` (default) / `--no-strict`
- **Output:** JSON array of `ExportedInferenceParam` records (stdout or `--output`)

#### ml-model-upload

Create OnPing ML model records, upload TorchScript .pt versions with metadata, and list existing models. Use before ml-parameter import to get models into OnPing. Note: the model UUID is NOT the script hash -- script hashes are assigned when models are assigned to Inferno scripts in the OnPing UI.

- **Scripts:**
  - `ml-model-upload/scripts/ml_model_list.py` -- List models and versions
  - `ml-model-upload/scripts/ml_model_create.py` -- Create a model record
  - `ml-model-upload/scripts/ml_model_version_upload.py` -- Upload a TorchScript version
- **Input:** `ACCESS_TOKEN` + subcommand-specific flags (see SKILL.md)
- **Output:** Model UUID (create), Version UUID (upload), or JSON model list

#### ml-parameter-update

Update a deployed OnPing inference (ml-) parameter: swap script hash, rewire input/output PID bindings, change resolution. Read-modify-write against `PUT /inferno/ml/inference/update`; dry-run by default, `--apply` to commit. Reach for this when the Inferno script changes or PIDs need to move on a live deployment.

- **Script:** `ml-parameter-update/scripts/ml_parameter_update.py`
- **Subcommands:** `list`, `get`, `update`
- **Input:** `ACCESS_TOKEN` + subcommand-specific flags (see SKILL.md)
- **Output:** Table of inference params (list), JSON envelope (get), or diff + optional PUT result (update)
- **See also:** `ml-parameter-export` for a portable snapshot. `get` returns the nested runtime envelope (`active`, `param.terminated`) and omits `itype`; export returns a flat import-shaped record including `itype`.

#### parameter-import

Prepare the combined ML parameter xlsx template for creating OnPing output parameters (PIDs and VPIDs) that ml-parameters will write to. Covers cycle detector (15 PIDs), SAC actor (2 VPIDs), and cycle simulator (9 PIDs) outputs.

- **Template:** `parameter-import/templates/CombinedMLParameterTemplate.xlsx`
- **Input:** None (manual xlsx fill and upload)
- **Output:** 26 OnPing output parameters created on the ML Params location

#### event-table-import

Prepare Dhall event table configs for OnPing reward dashboard import. Event tables display per-cycle reward metrics and SAC recommendations. Use after output parameters are created via `parameter-import`.

- **Template:** `event-table-import/templates/ExampleEventTableAsTemplate.dhall`
- **Input:** None (manual Dhall adaptation and upload)
- **Output:** Event table config artifact ready for OnPing dashboard import

### Reports

#### onping-report

Generate a CSV report from OnPing historical data via the `/tachdb/report` endpoint. Posts a report request with Bearer auth and returns a pre-signed S3 download URL.

- **Script:** `onping-report/scripts/generate_report.py`
- **Input:** `ACCESS_TOKEN START_DATE END_DATE PID [PID ...]`
- **Options:**
  - `--step N` — Step size in seconds (default: 60)
  - `--resolution N` — Resolution exponent (default: 8)
  - `--title TEXT` — Report title (default: "CSV Report")
  - `--vpid` — Treat PIDs as virtual parameter IDs
- **Output:** Pre-signed CSV download URL (printed to stdout)

### Audit

#### onping-audit-pull

Pull the OnPing audit trail via `POST /log/audit2/query` — who changed a setpoint, alarm, site, or
dashboard, and when. **Read-only.** One route covers all three audit backends (OnPing audit server,
RTU Manager write audits, the OnPing authentication server). Paginates for you, since page size is
hardcoded to 10 server-side.

- **Script:** `onping-audit-pull/scripts/audit_pull.py`
- **Input:** `ACCESS_TOKEN --type NAME [--type NAME ...]`
- **Options:**
  - `--since ISO` / `--until ISO` — Bound `edited-on` (timezone required)
  - `--terms STR` — Relevance search terms, passed through verbatim
  - `--max-pages N` — Page cap (default: 50); `--all` lifts it
  - `--empty-page-limit N` — Give up after N consecutive empty pages (default: 10)
  - `--csv` / `--pretty` / `--output PATH` / `--list-types`
- **Output:** JSON `{retrieved, server_reported_count, count_saturated, truncated, stop_reason, empty_pages, shortfall, items[]}`, or CSV with `--csv`
- **Read the SKILL.md before using.** Three behaviors will otherwise produce a confident wrong
  answer: an **empty page is not the end of the data** (`usertag` starts with five empty pages, then
  70 pages of records), `meta_count` **saturates at 10000** so it is a ceiling rather than a total,
  and search terms **rank rather than filter** — adding a non-matching term dropped a record (35 → 34).

#### onping-audit-recover

Recover prior state for **any** audited OnPing model by querying its `<model>_audit` table in postgres directly. **Read-only, SELECT only.** Needs SSH to the audit host and a VPN, not a token; shares `_audit_db` with the custom-table audit skills.

- **Script:** `onping-audit-recover/scripts/audit_recover.py`
- **Input:** `AUDIT_HOST` + one operation
- **Options:** `--list-tables` (enumerate audit tables with row counts), `--table NAME`, `--original-id ID`, `--dump-row AUDIT_ID`, `--limit N` (default 25), `--all`, `--output PATH`, `--indent N`, `--quiet-resolve`
- **Why it exists — a generic writer paired with an enumerated reader:** `auditInsert` folds over every audited model, so every save lands in `<model>_audit` as a full snapshot. But `auditGet` dispatches over a hand-maintained `AuditType` case list, and many models derive `NoIndex` so they never reach Elasticsearch either. For those models `POST /log/audit2/query` returns **nothing at all** — not an error, just an empty result that reads like "no history exists". Custom tables prompted this skill and are not the only case: `MenuPanelAudit`, `ContentObjAudit`, `ContentArrayAudit`, and `ParameterHistoryAudit` are in the same position
- **Prefer `onping-audit-pull` where it works** — it is a supported route, permission-scoped server-side, and needs no SSH. Reach for this skill when that one returns nothing for a record you know changed
- **⚠️ It deliberately decodes nothing.** Columns come out **as stored**, because which encoding applies is per model — a literal `s` text prefix, hex-of-ASCII (`MongoIdUtf8NoO`), Haskell `Show`/`Read`, or plain JSON. A generic decoder across those would **silently corrupt values** rather than fail. Decoding is the caller's job; `onping-ctable-audit-export` is the worked example of doing it per model
- **Deletions are recoverable.** The delete path reads the document *before* removing it, so a row whose `audit_action` is `Delete` carries the record's final pre-delete content, and the version list marks the action so you can find it
- **Exits:** 2 when no operation is requested (listing the valid combinations) or on a malformed id, 1 on an unknown table (with the nearest-match suggestion), no rows, a table with no `original_id`, or SSH refusal — **naming the host tried, with no fallback to any other address**

### Parameter Value Writes

#### onping-pid-write

Write a typed value to a PID. **MUTATING — requires `--yes`.** This is the only skill in the catalog that writes a **live value to physical equipment**; every other mutating OnPing skill changes configuration. Defaults to `POST /source/param/write-onping-result`, which resolves the location and driver source **server-side** from the PID.

- **Script:** `onping-pid-write/scripts/write_pid.py`
- **Input:** `ACCESS_TOKEN PID` + exactly one value flag
- **Value flags (mutually exclusive, one required):**
  - `--value F` — `OnPingDouble` (**write-masked**)
  - `--int N` — `OnPingInt` (**write-masked**)
  - `--text S` — `OnPingText` (not masked)
  - `--bool true|false` — `OnPingBool` (not masked)
- **Options:**
  - `--via-hmi` — Use `POST /hmi/devices/writeV2` instead; needed **only** for TotalFlow string writes
  - `--verify` — Poll until the value lands, then report `match` / `differs` / `unverified`
  - `--verify-timeout S` (default 15) / `--verify-interval S` (default 1)
  - `--names` / `--json`
  - `--yes` — **required to write**; without it, a dry run prints the resolved location *name*
- **Output:** The resolved target, current vs. new value, whether masking applies, the route, and the write result
- **Read the SKILL.md before using.** Four behaviors otherwise produce a confident wrong answer: **writes are asynchronous** (201 in 0.44s, value readable ~2.9s later), so a naive immediate read-back reports the *old* value and calls a good write `differs`; **numeric writes pass through a per-PID write mask** that can change the value and silently falls back to unmasked on error; **`writeability` is not an interlock** — no driver reads it from the request; and **the `--via-hmi` route returns `500` for client-caused failures including permission denials**, so status alone cannot classify errors. Note the default route returns **`201`**, not `200`.
- **Why not the browser's route:** `writeV2` accepts a full `TagInfo` and **trusts** the `locationId` and `localParameterId` inside it — nothing re-derives them from the PID — so a wrong source descriptor dispatches the write down the **wrong protocol driver** and a wrong location writes **elsewhere**, both with a success status. The default route makes both impossible. Even with `--via-hmi`, this skill builds the envelope from a live lookup rather than user-supplied fields.

### Imports

#### onping-mass-write

Build a validated OnPing mass-write CSV from user-supplied timestamp+value points. Offline only — produces the file the OnPing UI mass-import dialog expects, but does **not** upload. Strict validation: numeric PID, ISO-8601 timestamps, float values, no duplicate timestamps.

- **Script:** `onping-mass-write/scripts/build_csv.py`
- **Input:** `PID` (positional) + points as a no-header `timestamp,value` CSV via stdin or `--input <path>`
- **Options:**
  - `--label TEXT` — Human label placed in row 1 column B
  - `--output PATH` — Write CSV to this path (default: `./mass-write-<PID>-<UTC-timestamp>.csv`)
  - `--stdout` — Write CSV body to stdout instead of a file (mutually exclusive with `--output`)
- **Output:** CSV file (default) with the file path printed to stdout, or CSV body on stdout with `--stdout`
- **Cloud vs. Edge:** uploading the resulting CSV via the OnPing UI writes to the **cloud server only** — the data is NOT propagated to local Lumberjack edge servers, so edge-side reads will not see it.

#### onping-import-mqtt-json

Upload/round-trip an mqtt-json parameter spreadsheet to `POST /mqtt/json/param/import` (a multipart form: `File` = the XLSX, `Location` = the location refId int). The write counterpart to `onping-export-mqtt-json`. This is a **bulk UPDATE, not authoring**: the server reconciles the location's entire parameter set from the sheet and rejects the import unless every existing PID is present (`existingPids ⊆ importedPids`), so the workflow is **export → edit → re-import**. A blank `PID` cell creates a parameter; a populated one updates it (preserving stored value). **Mutating** — no POST without `--yes`; the default and `--dry-run` validate the file, fetch the live location to reproduce the PID-coverage check locally, and preview only. The SKILL.md is also the authoritative **mqtt-json parameter-format reference**: the 8 columns, value types, time formats, writeability, and the supported JQ selector subset (incl. `select(...)` semantics).

- **Script:** `onping-import-mqtt-json/scripts/import_params.py`
- **Inputs:** `access_token`, `location_id` (int), `spreadsheet` (path)
- **Options:**
  - `--dry-run` — validate + coverage check + preview, never POST (wins over `--yes`)
  - `--yes` — perform the upload (required for the mutating POST)
- **Note:** the `Type` column is parsed but ignored on import (an existing parameter's stored value type is preserved).
- **Not the integrator.** This is the driver's own parameter sheet, keyed by location refId. The rule-based layer that *generates* these parameters from MQTT traffic is a separate family keyed by `LJSerial` — see [MQTT JSON Integrator](#mqtt-json-integrator).

#### onping-import-singlewell-manual

Upload/round-trip a singlewell-manual parameter spreadsheet to `POST /v2/singlewellmanual/import/params` (a multipart form: `f1` = the XLSX, `f2` = the location refId int). The write counterpart to `onping-export-singlewell-manual`. Unlike mqtt-json, this endpoint **creates AND updates**: a blank `Pid` cell creates a new parameter (server-assigned Pid), a populated one updates it. It **cannot delete** — the server requires every existing Pid to still be present (blank-Pid rows are excluded from the check), so the workflow is **export → edit/append → re-import**. **Mutating** — no POST without `--yes`; the default and `--dry-run` validate the file, fetch the live location to reproduce the Pid-coverage and duplicate-`Parameter ID` checks locally, and preview only. The SKILL.md is also the authoritative **singlewell-manual parameter-format reference**: the 5 columns and the six value-type tags (`DoubleTag`, `NaNTag`, `Ascii24Tag`, `Utf8_24Tag`, `Utf8_40Tag`, `Utf8_184Tag`) with their byte caps.

- **Script:** `onping-import-singlewell-manual/scripts/import_params.py`
- **Inputs:** `access_token`, `location_id` (int), `spreadsheet` (path)
- **Options:**
  - `--dry-run` — validate + coverage check + preview, never POST (wins over `--yes`)
  - `--yes` — perform the upload (required for the mutating POST)
- **Note:** unlike mqtt-json, the `Type` column IS honored on import (it drives how the `Value` cell is parsed). New-row Pids are server-assigned — re-export to see them.
- **Field-name gotcha:** multipart field names are Yesod auto-names `f1` (file) / `f2` (location int), not the labels "File"/"Location".

### MQTT JSON Integrator

The **integrator** is the rule-based automation layer that sits *above* the mqtt-json driver. Instead of configuring each parameter by hand, you write rules; the integrator matches them against live MQTT topic/message pairs, generates location and PID definitions, and pushes them into the driver:

```
MQTT data → Unprocessed → [rules] → Uncreated → Created → mqtt-json driver
```

Two things separate this family from the mqtt-json **driver** skills (`onping-add-mqtt-json`, `onping-update-mqtt-json`, `onping-export-mqtt-json`, `onping-import-mqtt-json`), which operate one layer down on objects that already exist:

- **Integrator routes key on `LJSerial`**, not on a location refId. Every stateful route is scoped to one Lumberjack.
- **`mqtt-json-integrator-server` must be installed on that LJ** (use `lj-deploy` to confirm, `lj-profile` to map a location id to a serial).

All routes are under `/mqtt/json/integrator/*` (`onping/config/routes`), handled by `onping/Handler/MqttJsonIntegrator/`. Shared helper: `_mqtt_integrator_routes/` (`routes.py`, `integrator_http.py`, `rules_sheet.py`), whose `routes.py` docstring is the authoritative reference for the gotchas below and for the JSON wire shapes — verified against the checked-in golden files at `mqtt-json-integrator-types/golden/`, not inferred.

**Five traps this family exists to handle:**

1. **`POST .../artifacts` CREATES REAL OBJECTS; `POST .../artifacts/import` creates nothing.** One path segment apart, wildly different. The first runs a five-stage pipeline through the mqtt-json driver; the second only repserts the integrator's own record. See `-create` vs `-artifacts-import`.
2. **The create route returns HTTP 200 on total failure.** Errors live in `createLocationErrors` / `createPidErrors` arrays, so a `resp.ok` check reports success when nothing was created.
3. **Rules import REPLACES ALL RULES** and renumbers every rule id from row order. Anything missing from the sheet is deleted.
4. **Multipart field name is `f1`, not `File`** — the handlers' `fileAFormReq "File"` gives a label, and Yesod names fields positionally. Same trap as the logtable and singlewell-manual imports.
5. **Rule-execution results are invisible on the execute route** (it returns an empty envelope) — they appear only in the `ExecuteRulesReport`.

Deliberately out of scope: the five `/mqtt/json/integrator/router/#LJSerial/address*` routes, which register the integrator server's host:port in the driver-switcher index — deployment plumbing closer to `lj-deploy`.

#### Read-only

| Skill | Route(s) | Notes |
|---|---|---|
| **onping-mqtt-integrator-rule-parse** | `POST .../rule/parse`, `POST .../jq/rule/parse` | Validate rule expressions. Stateless and **not** serial-scoped — no LJ needed. Body is a bare JSON string. A parse failure arrives as **HTTP 200** with a `FailedToParseRules` tag, so the skill exits non-zero instead. `--jq-only` for PID Time/Value columns; `--full` for the sed+JQ grammar. SKILL.md is the rule-grammar reference. |
| **onping-mqtt-integrator-rules-export** | `GET .../rules/export/{filename}` (XLSX), `GET .../generation/rules` (JSON) | Step one of any rule edit, since import is destructive. Only the **JSON** carries rule identifiers; the sheet omits them. `--summary` shows how the import will group rows into location blocks and warns on non-contiguous ones. |
| **onping-mqtt-integrator-artifacts-export** | `GET .../artifacts/export/{filename}` (XLSX), `GET .../artifacts` (JSON) | The integrator's record of what it created — one-way, never re-verified, values frozen at rule-execution time. **XLSX round-trip is lossy** (timestamps dropped, unknown values → `0.0`); use `--json` to back up. |
| **onping-mqtt-integrator-unprocessed** | `GET .../unprocessed/data`, `GET .../unprocessed/data/export`, `POST .../unprocessed/json/objects/delete` | The raw queue plus the uncreated candidates. Entries are unique per **(topic, message) pair**, not per topic. A capped queue **ignores** new messages rather than evicting — the usual reason a healthy broker looks silent. `--show N` prints real payloads to write JQ against. `--clear --yes` wipes the queue. |
| **onping-mqtt-integrator-reports** | `GET`/`DELETE .../execute/rules/report`, `POST .../generation/rules/execute` | The only place execution errors and match counts surface. Counts report **NEW** objects only, so `0/0` means "nothing new", not necessarily "nothing matched". `--execute --yes` runs the rules (blocking, serialized server-side, creates nothing) and prints the resulting report. |

#### Mutating (all `--yes`-gated; `--dry-run` wins if both are passed)

| Skill | Route | Notes |
|---|---|---|
| **onping-mqtt-integrator-config** | `GET`/`POST .../mqtt/config` | Broker, topic, auto-execute flag, unprocessed-queue cap. Read-modify-write, because the handler consumes a whole `MqttConfig` and a partial body drops fields. **Refuses to change Company/Site/Group**, which decide where generated objects land. |
| **onping-mqtt-integrator-rules-import** | `POST .../rules/import` | **Destructive**: replaces the entire rule set and renumbers all ids. Fetches the live rules first and reports what would be added, kept, and `DROPPED` by name. Refuses an empty sheet. `--execute` runs the new rules afterward. |
| **onping-mqtt-integrator-artifacts-import** | `POST .../artifacts/import` | **Creates nothing.** A keyed repsert of the record — absent rows are *not* deleted. Its real function is **suppression**: the create pipeline skips anything already recorded. Column 3 (`Location ID Ref`) is trusted verbatim and never verified. |
| **onping-mqtt-integrator-create** | `POST .../artifacts` | **The one that creates real objects**, with no undo. Requires `--location-url` (the LJ's `lumberjackUrl`, from `lj-profile`) and `--port` (default **2000**, matching the UI's hardcoded value). Exits non-zero on any entry in the error arrays. Warns when a selected PID's location is absent, since those are dropped silently. `--list` browses candidates safely. |
| **onping-mqtt-integrator-blacklist** | `GET`/`POST .../blacklist` | Blocks specific locations/PIDs from ever being created, filtered server-side so even `--all` skips them. **Blocks creation but does not delete** anything already created. Incremental add/remove ops, not a whole list. |
| **onping-mqtt-integrator-delete** | `POST .../uncreated/delete`, `.../stored/delete`, `.../unprocessed/json/objects/delete` | One skill, `--target {uncreated,stored,unprocessed}`. All integrator-local. `uncreated` is nearly harmless (the next run regenerates — blacklist instead to make it stick); **`stored` is dangerous**: the real objects keep existing while orphaned, and forgetting the record *un-suppresses* creation so a later run can make duplicates. A full wipe needs `--all` as well as `--yes`. |

**Identifying a PID takes three values.** `PidUniqueIdentifier` is a two-field record — the location key plus a source id of `(topic, valueSelector)` — not a scalar. The `--pid` flags take them joined by `::`, and every skill's `--list` prints copy-pasteable selectors.

**Two 12-column sheets, easily confused.** Both the rules and artifacts sheets put location data in columns 1-3 and PID data in 4-12, but the meanings differ and column 11 (`PID Read Only`) is a **boolean** in the rules sheet versus `ReadOnly`/`Writeable` in the artifacts sheet. Both import skills detect a wrong-flavor sheet from its header row and name the right skill. A row with columns 4-12 all empty is location-only; filling only some is rejected.

### inferno-lookup

Reference documentation for the Inferno scripting language used in OnPing. Covers three parameter script types:

- **Virtual Parameters** — Compute derived values from multiple parameters at view/alarm time
- **Control Parameters** — Run scripts on periodic schedules using Lumberjack edge devices
- **ML Parameters** — Scripts that reference Inferno ML models for inference

Documentation files:

- `inferno-lookup/docs/inferno-virtual-control.md` — Language reference (types, syntax, modules for Base, Array, Option, Text, Time)
- `inferno-lookup/docs/inferno-ml.md` — ML-specific extensions (Tensor operations, model loading, Bedrock LLM prompting, structured JSON output via Schema/JSON modules)
- `inferno-lookup/docs/inferno-control-vs-virtual.md` — Runtime model differences for control vs virtual parameters (triggers, outputs, and execution model)

### Driver Updates

**Mutating** skills that update a single driver location's configuration on OnPing — primarily **poll time** — via authenticated **read-modify-write**: fetch the current full config, change only the requested allowlisted field(s), and POST the whole record back. One skill per driver, backed by the shared `_driver_update_routes` module.

**Safety model:**
- A real write happens only with `--yes`. With neither `--yes` nor `--dry-run`, the skill prints the before/after diff and exits without mutating. `--dry-run` fetches and shows the diff but never POSTs.
- **Lumberjack-binding and identity fields are never changed.** Drivers run on Lumberjacks; the lumberjack address pair (`lumberjackUrl`/`lumberjackPort` or the per-driver equivalent) or `*LJSerial`, plus identity keys (`id`/`refId` and equivalents), are routing/identity keys. Editing them would desync routing or retarget the wrong device. Each skill refuses to modify its locked fields and asserts they are unchanged before POSTing. Moving a location to a different lumberjack is a separate operation, out of scope here.
- Editable downstream device fields (PLC/device/gateway address) are preserved as fetched and are not touched.

**Finding the driver for a bare refId:** these skills are per-driver, and you pick the one matching the location's driver. Use **`onping-driver-resolve`** — given one or more refIds it returns each location's driver slug in a single call (`POST /singlewellextras/lister`, reading the stored protocol). It covers 20 of 21 drivers. Two cases come back as `unknown`: **sparkplug-bridge** (keyed by Lumberjack serial, not stored in `single_well_extras`) and locations not owned by the token's user — for those, fall back to probing the candidate driver's fetch via `--dry-run` (the correct `onping-update-<driver>` returns the config; the wrong one errors), e.g. confirm sparkplug via `onping-update-sparkplug-bridge … --serial <LJSerial> --dry-run`. Once you know the driver, run the matching `onping-update-<driver>` with `--dry-run` then `--yes`.

**Non-polling drivers** (`singlewell-manual`, `mqtt-json`, `sparkplug-bridge`) have no poll-time field and reject `--poll-time`. **Serial-keyed drivers** (`elynx`, `sitepro`, `tank-logix`, `toku`, `sparkplug-bridge`) require `--serial <LJSerial>` to fetch the config.

- **onping-update-bristol** — update bristol location via `/bristol/location/update` (read-modify-write)
- **onping-update-roc-tlp** — update roc-tlp location via `/roc/tlp/location/update` (read-modify-write)
- **onping-update-modbus-flexible** — update modbus-flexible location via `/modbus/flexible/location/update` (read-modify-write)
- **onping-update-control-logix** — update control-logix location via `/control/logix/location/update` (read-modify-write)
- **onping-update-total-flow** — update total-flow location via `/total/flow/location/update` (read-modify-write)
- **onping-update-micrologix** — update micrologix location via `/micrologix/location/update` (read-modify-write)
- **onping-update-singlewell-manual** — update singlewell-manual location via `/singlewellmanual/location/update` (read-modify-write) — **non-polling** (no `--poll-time`)
- **onping-update-mqtt-json** — update mqtt-json location via `/mqtt/json/location/update` (read-modify-write) — **non-polling** (no `--poll-time`). For the rule-based automation layer above this driver, see [MQTT JSON Integrator](#mqtt-json-integrator).
- **onping-update-opc-ua** — update opc-ua location via `/opc/ua/location/update` (read-modify-write)
- **onping-update-wellpilot** — update wellpilot location via `/wellpilot/location/update` (read-modify-write)
- **onping-update-unico** — update unico location via `/unico/location/update` (read-modify-write)
- **onping-update-lufkin** — update lufkin location via `/lufkin/location/update` (read-modify-write)
- **onping-update-osi-integration** — update osi-integration location via `/osi/integration/location/update` (read-modify-write)
- **onping-update-hazard-pro** — update hazard-pro location via `/hazard/pro/location/update` (read-modify-write)
- **onping-update-lumberjack-remote** — update lumberjack-remote location via `/lumberjack/remote/update` (read-modify-write)
- **onping-update-elynx** — update elynx location via `/elynx/integration/location/update` (read-modify-write) — needs `--serial`
- **onping-update-sitepro** — update sitepro location via `/sitepro/location/update` (read-modify-write) — needs `--serial`
- **onping-update-tank-logix** — update tank-logix location via `/tank-logix/location/update` (read-modify-write) — needs `--serial`
- **onping-update-toku** — update toku location via `/toku/location/update` (read-modify-write) — needs `--serial`
- **onping-update-dnp3** — update dnp3 location via `/dnp3/location/update` (read-modify-write)
- **onping-update-sparkplug-bridge** — update sparkplug-bridge location via `/sparkplug/bridge/update` (read-modify-write) — **non-polling** (no `--poll-time`) — needs `--serial`

Each skill is invoked the same way (preview, then apply):

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
uv run ~/.claude/skills/onping-update-<driver>/scripts/update_location.py "$ACCESS_TOKEN" REF_ID --poll-time 5 --dry-run
uv run ~/.claude/skills/onping-update-<driver>/scripts/update_location.py "$ACCESS_TOKEN" REF_ID --poll-time 5 --yes
```

### Driver Add Schemas

Read-only skills that print the JSON request/response shape for each OnPing device driver's `/location/add` (or `/bridge/add`) POST endpoint. Schemas are hand-curated from the Haskell handler + type sources; each entry records the source `handler` file:line for traceability. **None of these skills make a network call** — they print schema only. Hitting the real `/add` endpoint creates a record on the OnPing server and is intentionally out of scope here.

All entries share the same shape: `driver`, `endpoint`, `handler`, `request_type`, `request_schema`, `response_type`, `response_schema`.

- **onping-add-bristol** — Bristol driver `/bristol/location/add` schema
- **onping-add-roc-tlp** — RocTlp driver `/roc/tlp/location/add` schema
- **onping-add-modbus-flexible** — ModbusFlexible driver `/modbus/flexible/location/add` schema
- **onping-add-control-logix** — ControlLogix driver `/control/logix/location/add` schema
- **onping-add-total-flow** — TotalFlow driver `/total/flow/location/add` schema
- **onping-add-micrologix** — Micrologix driver `/micrologix/location/add` schema (same handler also handles update when `locationId` is set)
- **onping-add-singlewell-manual** — SingleWell Manual driver `/singlewellmanual/location/add` schema
- **onping-add-mqtt-json** — MQTT/JSON driver `/mqtt/json/location/add` schema. To create these locations automatically from MQTT pattern rules instead, see [MQTT JSON Integrator](#mqtt-json-integrator).
- **onping-add-opc-ua** — OPC/UA driver `/opc/ua/location/add` schema
- **onping-add-wellpilot** — WellPilot driver `/wellpilot/location/add` schema
- **onping-add-unico** — Unico driver `/unico/location/add` schema
- **onping-add-lufkin** — Lufkin driver `/lufkin/location/add` schema
- **onping-add-osi-integration** — OSI Integration driver `/osi/integration/location/add` schema
- **onping-add-hazard-pro** — Hazard Pro driver `/hazard/pro/location/add` schema
- **onping-add-lumberjack-remote** — Lumberjack Remote driver `/lumberjack/remote/add` schema (outlier path: no `/location/`)
- **onping-add-elynx** — Elynx integration driver `/elynx/integration/location/add` schema
- **onping-add-sitepro** — Sitepro driver `/sitepro/location/add` schema
- **onping-add-tank-logix** — TankLogix driver `/tank-logix/location/add` schema
- **onping-add-toku** — Toku driver `/toku/location/add` schema
- **onping-add-dnp3** — DNP3 driver `/dnp3/location/add` schema
- **onping-add-sparkplug-bridge** — Sparkplug bridge `/sparkplug/bridge/add` schema (outlier: bridge, not a location)

Each skill is invoked the same way:

```bash
uv run ~/.claude/skills/onping-add-<driver>/scripts/show_add_schema.py
```

### Driver Tag Exports

Per-driver skills that download the OnPing tag-export XLSX for each driver that has an export route. Each skill performs an authenticated GET against the driver's `*/export/*` endpoint (using a bearer token from `onping-login`), streams the response body to a local `.xlsx`, and prints the saved path. Backed by a shared routes table and download helper. The helper now refuses to write HTML-bodied 2xx responses — token-expired fallthrough (OnPing's `303 → /auth/login`) exits 1 with a stderr diagnostic instead of saving a `.xlsx` full of login-page HTML.

Drivers without an export route — bristol, unico, lufkin, osi-integration, hazard-pro, elynx, sitepro, tank-logix, toku — are not represented here.

Common usage pattern (replace `<driver>` and IDs as needed):

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py) && \
  uv run ~/.claude/skills/onping-export-<driver>/scripts/export_tags.py \
    "$ACCESS_TOKEN" LOCATION_ID tags.xlsx
```

- **onping-export-micrologix** — `/micrologix/export/params/{location_id}/{filename}`
- **onping-export-roc-tlp** — `/roc/tlp/export/params/{location_id}/{filename}`
- **onping-export-modbus-flexible** — `/modbus/flexible/export/params/{location_id}/{filename}`
- **onping-export-control-logix** — `/control/logix/params/export/{location_id}/{filename}` (note: path order differs from siblings)
- **onping-export-total-flow** — `/total/flow/export/params/{location_id}/{filename}`
- **onping-export-singlewell-manual** — `/v2/singlewellmanual/export/params/{location_id}/{filename}` (default v2; pass `--v1` for legacy route)
- **onping-export-mqtt-json** — `/mqtt/json/param/export/{location_id}/{filename}` (pass `--all` for the developer-only `/mqtt/json/param/export/all` JSON dump). Note the integrator has its own, unrelated exports keyed by `LJSerial` — see [MQTT JSON Integrator](#mqtt-json-integrator).
- **onping-export-opc-ua** — `/opc/ua/param/export/{location_id}/{filename}`
- **onping-export-wellpilot** — `/wellpilot/param/export/{location_id}/{filename}` (pass `--cards` to export pump cards instead of tags)
- **onping-export-sparkplug-bridge** — `/sparkplug/bridge/export/{lumberjack_serial}/{filename}` (outlier: keyed by `LJSerial`, not `LocationIdRef`)
- **onping-export-lumberjack-remote** — `/lumberjack/remote/export-v2/params/{location_id}/{filename}` (default v2; pass `--v1` for legacy route)
- **onping-export-dnp3** — `/dnp3/export/params/{location_id}/{filename}`

The `{filename}` path argument is forwarded to OnPing (some handlers use it in `Content-Disposition`, others ignore it). Local file naming is controlled by the script's `--output PATH` flag, with default `./<driver>-<id>-<UTC-timestamp>.xlsx`.

Several handlers (micrologix, roc-tlp, modbus-flexible, control-logix, total-flow, singlewell-manual, lumberjack-remote) declare `Content-Type: text/csv` but the body is real XLSX — the downloader treats the body as opaque bytes, so the local file is a valid `.xlsx` regardless.

### Workflows

#### cpid-migration

5-phase runbook for migrating old-style control parameters to the Inferno CP system on OnPing Lumberjacks. Each phase produces a deliverable that feeds the next. Do not skip phases.

- **Phase 1 — Information Gathering:** Discover pad topology (wells, locations, PIDs, CP groupings)
- **Phase 2 — Migration Planning:** Map each old script to a verified Inferno script with correct output format
- **Phase 3 — Disable Old CPs:** Turn off old classic CPs before importing Inferno replacements
- **Phase 4 — Deploy Packages:** Install required Inferno packages on the Lumberjack
- **Phase 5 — JSON Import Creation:** Build, validate, and import the JSON payload; verify post-import

Documentation files:

- `cpid-migration/docs/01-information-gathering.md` — Phase 1 runbook
- `cpid-migration/docs/02-migration-planning.md` — Phase 2 runbook
- `cpid-migration/docs/03-disable-old-cps.md` — Phase 3 runbook
- `cpid-migration/docs/04-deploy-packages.md` — Phase 4 runbook
- `cpid-migration/docs/05-json-import-creation.md` — Phase 5 runbook

Uses skills: `onping-login`, `onping-search`, `onping-sites`, `onping-locations`, `onping-parameters`, `lj-profile`, `cp-list`, `cp-script-fetch`, `classic-cp-dhall`, `classic-cp-list`, `classic-cp-export`, `classic-cp-import`, `classic-cp-by-pid`, `classic-cp-delete`, `lj-deploy`, `cp-import-json`

### Documentation Site

Six skills for the OnPing customer-facing documentation site — a **Payload CMS**
instance at `https://onping.plowtech.net/onping-doc`, separate from the OnPing SCADA
API above. These skills do **not** use a token from `onping-login`. They carry their
own API key, resolved by `_docs_routes` from `ONPING_DOCS_API_KEY`, a plaintext
`onping-docs` file, or `onping-docs.gpg`.

**The service has two surfaces and two Authorization forms, and they are not
interchangeable:**

| Route | Header | Note |
| --- | --- | --- |
| `POST /api/mcp` | `Authorization: Bearer <key>` | JSON-RPC over SSE. The only write path for docs and categories |
| `GET /api/<collection>` | `payload-mcp-api-keys API-Key <key>` | Read. The docs collections are world-readable, so the key is sent defensively |
| `POST /api/media` | `payload-mcp-api-keys API-Key <key>` | The one REST write that works — image upload returns `201` |

Read `_docs_routes/SKILL.md` before writing new code against this service. It
records every trap, including the two that mislead outright: **a `User-Agent`
beginning `python-requests` gets a `404 NotFound`**, and **a failed tool call arrives
as HTTP `200` with a JSON-RPC `result` whose text merely starts with `Error:`**.

#### _docs_routes (internal helper — do not invoke)

Shared transport: key resolution, both header builders, the mandatory
`Accept: application/json, text/event-stream`, SSE de-framing, the explicit
User-Agent, and the error-in-a-successful-result detection.

- **Modules:** `_docs_routes/routes.py`, `_docs_routes/docs_http.py`

#### onping-doc-list

Discover documents via `findDocs` and `getDocsByCategory`. Read-only. Resolves a
category slug to an id, because the server's slug branch answers `params: NaN`.
Hides null-titled empty drafts and trash-marked documents on request.

- **Script:** `onping-doc-list/scripts/list_docs.py`
- **Key flags:** `--where`, `--category`, `--trash`, `--no-trash`, `--include-empty`

#### onping-doc-get

Read one document by id or slug, summarizing its Lexical `content` node types rather
than dumping the tree. Use `--json` to back a document up before overwriting it.

- **Script:** `onping-doc-get/scripts/get_doc.py`

#### onping-doc-create

Create a page via `createDocs`. MUTATING, `--yes`. Requires `title`, `slug`,
`category`, `order`, checked locally first. A created page has **no body** — follow
with `onping-doc-write`.

- **Script:** `onping-doc-create/scripts/create_doc.py`

#### onping-doc-write

Publish markdown via `updateDocWithMarkdown` — the only tool accepting markdown, and
the only way to change a body since no `updateDocs` tool exists. MUTATING, `--yes`.
Carries the `explainer` skill's 14 language constraints, the three canonical personas
(Users / Builders / Platformers), and the five-section published shape. Blocks on a
missing audience, an `Open Questions` heading, or an unjustified sixth section; the
prose findings are advisory and never block. Also carries `--trash`.

- **Script:** `onping-doc-write/scripts/write_doc.py`

#### onping-doc-delete

Delete via `deleteDocs`. MUTATING. A `--where` bulk delete needs `--yes` **and** a
`--confirm-count` matching the resolved count. **Currently blocked server-side** —
see the trash note below.

- **Script:** `onping-doc-delete/scripts/delete_doc.py`

#### onping-doc-category

All four `*Categories` tools. A category is a sidebar tab, so `order` controls live
navigation and deleting one orphans its documents. `--list` is read-only; mutations
need `--yes`.

- **Script:** `onping-doc-category/scripts/category.py`

#### Trash convention (a stopgap, not a feature)

**Nothing can delete a document on this server.** The MCP plugin acts as the API
key's related user, who holds role `admin`, and `Docs.ts` permits an admin to delete
only when `data.deletedAt` is truthy — a value no field defines and no trash setting
sets. The delete control is hidden in the admin UI for **every** admin; only an
`owner`-role account can delete. This is a known server-side bug.

A trash *category* is unreachable too, because `updateDocWithMarkdown` cannot set
`category`. So a discarded document is **marked**: slug prefixed `trash-`, title
prefixed `TRASH`. Set it with `onping-doc-write --trash`, find them with
`onping-doc-list --trash`.

**CAUTION: the slug marker uses a hyphen, never a slash.** A `/` in a slug makes the
nested-docs plugin expect a parent document, and the next write to that document
fails with `The following field is invalid: Breadcrumbs 1 > Doc`.

#### Tables do not render (yet)

The docs editor is built from `...defaultFeatures`, which contains no table feature,
so a markdown table publishes as literal `|` characters, raw HTML is escaped, and a
hand-written Lexical `table` node is stripped. This is a known server-side bug; the
fix is one import of `EXPERIMENTAL_TableFeature`. **Re-check before authoring a field
reference** — `onping-doc-write/SKILL.md` carries the check and the fallback ladder.
