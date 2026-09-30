# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Create real OnPing locations and mqtt-json parameters from integrator candidates.

Route: POST /mqtt/json/integrator/{serial}/artifacts
Body:  CreateArtifacts JSON

THIS IS THE ONE THAT CREATES THINGS. Despite the route reading like a repsert, it
runs a five-stage pipeline (Service.hs):

  1. integrator step-one   — filters blacklisted items, returns what to create
  2. mqtt-json driver      — addMqttJsonLocation, per new location
  3. mqtt-json driver      — addMqttJsonParameters, per location's PIDs
  4. integrator step-two   — records what was created
  5. returns CreateArtifactsReport

Real OnPing locations and real driver parameters come out the other side. There is
no undo: deleting them afterward means removing the driver location and the OnPing
objects by hand. The sibling route POST .../artifacts/import only writes the
integrator's record and creates nothing — see onping-mqtt-integrator-artifacts-import.

HTTP 200 DOES NOT MEAN SUCCESS. The report carries createLocationErrors and
createPidErrors arrays; a run where every single creation failed still returns
200. This script exits NON-ZERO whenever either array is non-empty, which is the
whole reason to use it instead of curl.

TWO REQUIRED FIELDS THE CALLER MUST SUPPLY:
  createArtifactsLocationUrl   the Lumberjack's own URL (its lumberjackUrl), used
                               as the driver location's address. Fetch it with
                               lj-profile; there is no integrator route for it.
  createArtifactsLocationPort  the mqtt-json driver's listener port. The OnPing
                               frontend HARDCODES 2000
                               (MqttJsonIntegrator_CreatableObjects.res), so
                               that is the default here.

SELECTION. By default nothing is created — you must pass --all or name specific
candidates. Locations are named by their unique identifier; PIDs need the
(location key, topic, value selector) triple, because PidUniqueIdentifier is a
two-field record, not a scalar.

PIDS NEED THEIR LOCATION. A PID whose location is neither already created nor
included in this request is DROPPED SILENTLY — step two can only map PIDs whose
location resolved to a refId. --all avoids this; a hand-picked selection may not.

Source of truth (re-verify if these drift):
  - Handler: onping/Handler/MqttJsonIntegrator/Service.hs
  - Types:   mqtt-json-integrator-types/.../Types.hs (CreateArtifacts),
             :1226 (CreateArtifactsReport)
  - Frontend: src/MqttJsonIntegrator/
              MqttJsonIntegrator_CreatableObjects.res
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _mqtt_integrator_routes.integrator_http import _fail, get_json, post_json
from _mqtt_integrator_routes.routes import (
    CREATE_TIMEOUT_SECONDS,
    DEFAULT_MQTT_JSON_PORT,
    endpoint,
)


def loc_key(entry: dict, field: str) -> str:
    return str((entry.get(field) or {}).get("unLocationUniqueIdentifier") or "")


def pid_triple(pid: dict, field: str) -> tuple[str, str, str]:
    uid = pid.get(field) or {}
    src = uid.get("pidMqttJsonSourceId") or {}
    return (
        str((uid.get("pidLocationUniqueIdentifier") or {}).get(
            "unLocationUniqueIdentifier"
        ) or ""),
        str(src.get("mqttJsonSourceTopic") or ""),
        str(src.get("valueSelector") or ""),
    )


def pid_identifier(triple: tuple[str, str, str]) -> dict:
    """Rebuild a PidUniqueIdentifier from a (location, topic, selector) triple."""
    location, topic, selector = triple
    return {
        "pidLocationUniqueIdentifier": {"unLocationUniqueIdentifier": location},
        "pidMqttJsonSourceId": {
            "mqttJsonSourceTopic": topic,
            "valueSelector": selector,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Create real OnPing locations and mqtt-json parameters from the "
            "integrator's uncreated candidates. MUTATES OnPing with --yes; "
            "there is no undo."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument(
        "--location-url",
        help="the Lumberjack's own URL (its lumberjackUrl), used as the driver "
        "location address. Get it from lj-profile. Required unless --list.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_MQTT_JSON_PORT,
        help=f"mqtt-json driver listener port (default {DEFAULT_MQTT_JSON_PORT}, "
        f"matching what the OnPing UI hardcodes)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="list the uncreated candidates with the exact selectors to pass, "
        "then exit. Makes no changes and needs no --location-url.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="create every uncreated location and PID (blacklisted ones are "
        "filtered server-side)",
    )
    p.add_argument(
        "--location",
        action="append",
        default=[],
        metavar="KEY",
        help="create this location by its unique identifier; repeatable",
    )
    p.add_argument(
        "--pid",
        action="append",
        default=[],
        metavar="LOCKEY::TOPIC::SELECTOR",
        help="create this PID, identified by its location key, topic, and value "
        "selector joined by '::'; repeatable",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show exactly what would be created and stop (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually create the objects")
    p.add_argument("--json", action="store_true", help="emit the raw report JSON")
    args = p.parse_args()

    # Parse PID selectors and check flag conflicts BEFORE any network call, so
    # a malformed triple fails immediately rather than after a round-trip.
    if args.all and (args.location or args.pid):
        _fail("--all cannot be combined with --location/--pid.")
    if not args.list and not args.location_url:
        _fail(
            "--location-url is required: it becomes the driver location's address. "
            "It is the Lumberjack's own lumberjackUrl — get it with lj-profile. "
            "(Use --list to browse candidates without it.)"
        )
    parsed_pids: list[tuple[str, str, str]] = []
    for raw in args.pid:
        parts = raw.split("::")
        if len(parts) != 3:
            _fail(
                f"--pid {raw!r} must be LOCKEY::TOPIC::SELECTOR (three parts "
                f"joined by '::'); got {len(parts)}. Run --list to see the "
                f"exact values."
            )
        parsed_pids.append(tuple(parts))  # type: ignore[arg-type]

    data = get_json(
        args.access_token, endpoint("get_unprocessed"), serial=args.serial
    )
    uncreated_locs = data.get("uncreatedLocations") or []
    uncreated_pids = data.get("uncreatedPids") or []

    all_loc_keys = [
        loc_key(l, "uncreatedLocationUniqueIdentifier") for l in uncreated_locs
    ]
    all_pid_triples = [
        pid_triple(pid, "uncreatedPidUniqueIdentifier") for pid in uncreated_pids
    ]

    # ── --list ──────────────────────────────────────────────────────────────
    if args.list:
        print(
            f"Uncreated candidates on LJ {args.serial}: "
            f"{len(all_loc_keys)} location(s), {len(all_pid_triples)} PID(s)\n"
        )
        if all_loc_keys:
            print("Locations (pass with --location KEY):\n")
            for l in uncreated_locs:
                key = loc_key(l, "uncreatedLocationUniqueIdentifier")
                print(f"  --location {key!r}")
                print(f"      name: {l.get('uncreatedLocationName')!r}")
        if all_pid_triples:
            print("\nPIDs (pass with --pid 'LOCKEY::TOPIC::SELECTOR'):\n")
            for pid, triple in zip(uncreated_pids, all_pid_triples):
                print(f"  --pid {'::'.join(triple)!r}")
                print(f"      desc: {pid.get('uncreatedPidDescription')!r}")
        blacklist = get_json(
            args.access_token, endpoint("get_blacklist"), serial=args.serial
        )
        bl_locs = {
            str((e or {}).get("unLocationUniqueIdentifier") or "")
            for e in (blacklist.get("blacklistLocationUniqueIdentifiers") or [])
        }
        bl_pids = {
            pid_triple({"k": e}, "k")
            for e in (blacklist.get("blacklistPidUniqueIdentifiers") or [])
        }
        hit_locs = [k for k in all_loc_keys if k in bl_locs]
        hit_pids = [t for t in all_pid_triples if t in bl_pids]
        if hit_locs or hit_pids:
            print(
                f"\nOf these, {len(hit_locs)} location(s) and {len(hit_pids)} PID(s) "
                f"are BLACKLISTED and will be filtered out server-side even with "
                f"--all."
            )
        return

    # ── selection ───────────────────────────────────────────────────────────
    if args.all:
        sel_locs = list(all_loc_keys)
        sel_pids = list(all_pid_triples)
    else:
        sel_locs = list(args.location)
        sel_pids = list(parsed_pids)

        unknown_locs = [k for k in sel_locs if k not in set(all_loc_keys)]
        if unknown_locs:
            _fail(
                f"These location key(s) are not in the uncreated set: "
                f"{unknown_locs}. Run --list to see what is available."
            )
        unknown_pids = [t for t in sel_pids if t not in set(all_pid_triples)]
        if unknown_pids:
            _fail(
                f"These PID(s) are not in the uncreated set: "
                f"{['::'.join(t) for t in unknown_pids]}. Run --list."
            )

    if not sel_locs and not sel_pids:
        _fail(
            "Nothing selected. Pass --all, or --location/--pid (see --list). "
            "Refusing to POST an empty request."
        )

    # ── the silently-dropped-PID check ──────────────────────────────────────
    created = get_json(
        args.access_token, endpoint("get_artifacts"), serial=args.serial
    )
    already = {
        loc_key(l, "storedLocationUniqueIdentifier")
        for l in (created.get("storedLocations") or [])
    }
    resolvable = already | set(sel_locs)
    orphaned = [t for t in sel_pids if t[0] not in resolvable]
    if orphaned:
        print(
            f"WARNING: {len(orphaned)} selected PID(s) belong to a location that is "
            f"neither already created nor included in this request. Step two can "
            f"only map PIDs whose location resolved to a refId, so these would be "
            f"DROPPED SILENTLY — no error, no creation:",
            file=sys.stderr,
        )
        for t in orphaned:
            print(f"    {'::'.join(t)}", file=sys.stderr)
        print(
            "  Add their location with --location, or use --all.\n", file=sys.stderr
        )

    body = {
        "createArtifactsLocationUrl": args.location_url,
        "createArtifactsLocationPort": args.port,
        "createArtifactsLocations": [
            {"unLocationUniqueIdentifier": k} for k in sel_locs
        ],
        "createArtifactsPids": [pid_identifier(t) for t in sel_pids],
    }

    print(
        f"Would create on LJ {args.serial} (url={args.location_url}, "
        f"port={args.port}):\n"
        f"  {len(sel_locs)} location(s) in OnPing + the mqtt-json driver\n"
        f"  {len(sel_pids)} parameter(s) in the mqtt-json driver\n"
    )
    for k in sel_locs:
        print(f"  + location {k!r}")
    for t in sel_pids:
        print(f"  + pid      {'::'.join(t)}")
    print(
        "\nBlacklisted entries are filtered server-side, so fewer objects may be "
        "created than listed. Locations already recorded as created are skipped."
    )

    if args.dry_run or not args.yes:
        why = "--dry-run" if args.dry_run else "no --yes"
        print(
            f"\nNothing created ({why}). Re-run with --yes to apply.\n"
            f"THERE IS NO UNDO: removing these afterward means deleting the driver "
            f"location and the OnPing objects by hand."
        )
        return

    print("\nCreating (this calls four services in sequence and may take a while)...")
    resp = post_json(
        args.access_token,
        endpoint("create_artifacts"),
        body,
        serial=args.serial,
        timeout=CREATE_TIMEOUT_SECONDS,
    )

    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} from the create route:\n{resp.text[:1000]}")

    try:
        report = resp.json()
    except ValueError:
        _fail(f"Expected a CreateArtifactsReport, could not parse:\n{resp.text[:800]}")

    if isinstance(report, dict) and "error" in report and len(report) == 1:
        _fail(f"OnPing returned an error: {report['error']}")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))

    loc_errors = report.get("createLocationErrors") or []
    pid_errors = report.get("createPidErrors") or []
    made_locs = report.get("createdLocations") or []
    made_pids = report.get("createdPids") or []

    print(
        f"\nReport (HTTP {resp.status_code} — which does NOT imply success):\n"
        f"  locations created : {len(made_locs)}\n"
        f"  PIDs created      : {len(made_pids)}\n"
        f"  location errors   : {len(loc_errors)}\n"
        f"  PID errors        : {len(pid_errors)}"
    )

    for loc in made_locs:
        print(
            f"    location refId={loc.get('storedLocationIdRef')} "
            f"name={loc.get('storedLocationName')!r}"
        )

    if loc_errors or pid_errors:
        print("\nERRORS:", file=sys.stderr)
        for e in loc_errors:
            print(f"  location: {e}", file=sys.stderr)
        for e in pid_errors:
            print(f"  pid:      {e}", file=sys.stderr)
        print(
            f"\nPartial or total failure. {len(made_locs)} location(s) and "
            f"{len(made_pids)} PID(s) WERE created and are recorded; the failures "
            f"above were not. Re-running retries only what is still uncreated.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"\nCreated successfully. Verify independently — the integrator's record is "
        f"one-way and never re-checked:\n"
        f"  onping-pid-locate <token> <pid>\n"
        f"  onping-export-mqtt-json <token> <location refId>"
    )


if __name__ == "__main__":
    main()
