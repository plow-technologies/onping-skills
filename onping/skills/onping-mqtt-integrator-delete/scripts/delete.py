# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Delete mqtt-json-integrator uncreated candidates, created records, or the queue.

Routes: POST /mqtt/json/integrator/{serial}/uncreated/delete
        POST /mqtt/json/integrator/{serial}/stored/delete
        POST /mqtt/json/integrator/{serial}/unprocessed/json/objects/delete

THREE TARGETS, THREE VERY DIFFERENT CONSEQUENCES. All three are integrator-local —
none of them deletes anything in OnPing or the mqtt-json driver — but what that
means differs sharply:

  --target uncreated   Drops generated candidates. Harmless and REVERSIBLE: the
                       next rule execution regenerates them from the same
                       unprocessed data. To stop them coming back, blacklist them
                       instead (onping-mqtt-integrator-blacklist).
                       Deleting a location CASCADES to its PIDs.

  --target stored      Makes the integrator FORGET that it created something. The
                       real OnPing location and driver parameters KEEP EXISTING,
                       now orphaned and unreferenced. Worse, forgetting
                       UN-SUPPRESSES creation: the create pipeline skips only what
                       it has a record of, so the next run can create DUPLICATES
                       of the objects you just forgot. This is the dangerous one.

  --target unprocessed Clears all raw topic/message pairs. Unconditional — the
                       route takes no body and no selection. Not reversible; there
                       is no import route for this data. Needed to resume
                       ingestion once the queue hits its cap.

BODY SHAPES (verified against mqtt-json-integrator-types/golden/):
    {"tag": "DeleteUncreatedAll"}                       -- nullary: no contents key
    {"tag": "DeleteUncreatedByChoice",
     "contents": {"deleteUncreatedLocations": [...], "deleteUncreatedPids": [...]}}
  and likewise DeleteStoredAll / DeleteStoredByChoice. The unprocessed route takes
  no body at all.

MUTATES OnPing only with --yes. Deleting everything additionally requires --all,
so a bare --target stored --yes cannot wipe the record by accident.

Source of truth (re-verify if these drift):
  - Handlers: onping/Handler/MqttJsonIntegrator/Service.hs (uncreated),
              :259 (stored), :270 (unprocessed)
  - Types:    mqtt-json-integrator-types/.../Types.hs
  - Lifecycle: mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _mqtt_integrator_routes.integrator_http import (
    _fail,
    get_json,
    post_empty,
    post_json,
    report_write,
)
from _mqtt_integrator_routes.routes import endpoint

TARGETS = ("uncreated", "stored", "unprocessed")


def pid_identifier(triple: tuple[str, str, str]) -> dict:
    location, topic, selector = triple
    return {
        "pidLocationUniqueIdentifier": {"unLocationUniqueIdentifier": location},
        "pidMqttJsonSourceId": {
            "mqttJsonSourceTopic": topic,
            "valueSelector": selector,
        },
    }


def triple_of(uid: dict) -> tuple[str, str, str]:
    src = uid.get("pidMqttJsonSourceId") or {}
    return (
        str((uid.get("pidLocationUniqueIdentifier") or {}).get(
            "unLocationUniqueIdentifier"
        ) or ""),
        str(src.get("mqttJsonSourceTopic") or ""),
        str(src.get("valueSelector") or ""),
    )


def parse_triple(raw: str) -> tuple[str, str, str]:
    parts = raw.split("::")
    if len(parts) != 3:
        _fail(
            f"--pid {raw!r} must be LOCKEY::TOPIC::SELECTOR (three parts joined by "
            f"'::'); got {len(parts)}. Run --list to see exact values."
        )
    return tuple(parts)  # type: ignore[return-value]


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Delete mqtt-json-integrator uncreated candidates, created records, "
            "or the unprocessed queue. Integrator-local only — never deletes "
            "OnPing or driver objects. Mutates with --yes."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument(
        "--target",
        required=True,
        choices=TARGETS,
        help="uncreated = generated candidates (regenerate on next run); "
        "stored = the created-object RECORD (leaves real objects orphaned and "
        "un-suppresses creation); unprocessed = raw topic/message pairs",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="list what the target currently holds, with exact selectors, then exit",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="delete everything in the target. REQUIRED for a full wipe — a "
        "selection-less --yes is refused.",
    )
    p.add_argument(
        "--location",
        action="append",
        default=[],
        metavar="KEY",
        help="delete one location by unique identifier; repeatable. For "
        "--target uncreated this cascades to the location's PIDs.",
    )
    p.add_argument(
        "--pid",
        action="append",
        default=[],
        metavar="LOCKEY::TOPIC::SELECTOR",
        help="delete one PID; repeatable",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be deleted and stop (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually perform the delete")
    args = p.parse_args()

    # Parse PID selectors BEFORE any network call so a malformed triple fails
    # immediately rather than after a round-trip.
    sel_pids = [parse_triple(r) for r in args.pid]

    if args.all and (args.location or args.pid):
        _fail("--all cannot be combined with --location/--pid.")

    # ── unprocessed: no selection is possible ───────────────────────────────
    if args.target == "unprocessed":
        if args.location or args.pid:
            _fail(
                "--target unprocessed takes no --location/--pid: the route accepts "
                "no body and no selection, it clears everything. Use --all."
            )
        data = get_json(
            args.access_token, endpoint("get_unprocessed"), serial=args.serial
        )
        pairs = data.get("unprocessedJsonObjects") or []

        if args.list:
            print(
                f"{len(pairs)} unprocessed topic/message pair(s) on LJ "
                f"{args.serial}. No per-item selection is possible; the route "
                f"clears all of them.\n"
                f"Use onping-mqtt-integrator-unprocessed --topics/--show to inspect."
            )
            return

        if not args.all:
            _fail(
                "--target unprocessed can only delete everything. Pass --all to "
                "confirm you mean that."
            )

        print(
            f"Would clear ALL {len(pairs)} unprocessed topic/message pair(s) on LJ "
            f"{args.serial}.\n"
            f"  Rules, candidates and records are unaffected.\n"
            f"  NOT reversible — there is no import route for this data.\n"
            f"  Ingestion resumes if the queue had hit its configured cap."
        )
        if args.dry_run or not args.yes:
            why = "--dry-run" if args.dry_run else "no --yes"
            print(
                f"\nNothing deleted ({why}). Re-run with --all --yes.\n"
                f"Back up first: onping-mqtt-integrator-unprocessed <token> "
                f"{args.serial} --export pairs.json"
            )
            return
        resp = post_empty(
            args.access_token, endpoint("delete_unprocessed"), serial=args.serial
        )
        report_write(resp, what=f"unprocessed clear for LJ {args.serial}")
        print(f"\nCleared {len(pairs)} pair(s) on LJ {args.serial}.")
        return

    # ── uncreated / stored: selectable ──────────────────────────────────────
    if args.target == "uncreated":
        data = get_json(
            args.access_token, endpoint("get_unprocessed"), serial=args.serial
        )
        locs = data.get("uncreatedLocations") or []
        pids = data.get("uncreatedPids") or []
        loc_keys = [
            str((l.get("uncreatedLocationUniqueIdentifier") or {}).get(
                "unLocationUniqueIdentifier"
            ) or "")
            for l in locs
        ]
        pid_triples = [
            triple_of(pid.get("uncreatedPidUniqueIdentifier") or {}) for pid in pids
        ]
        route_key = "delete_uncreated"
        all_tag, choice_tag = "DeleteUncreatedAll", "DeleteUncreatedByChoice"
        loc_field, pid_field = "deleteUncreatedLocations", "deleteUncreatedPids"
        noun = "uncreated candidate"
    else:
        data = get_json(
            args.access_token, endpoint("get_artifacts"), serial=args.serial
        )
        locs = data.get("storedLocations") or []
        pids = data.get("storedPids") or []
        loc_keys = [
            str((l.get("storedLocationUniqueIdentifier") or {}).get(
                "unLocationUniqueIdentifier"
            ) or "")
            for l in locs
        ]
        pid_triples = [
            triple_of(pid.get("storedPidUniqueIdentifier") or {}) for pid in pids
        ]
        route_key = "delete_stored"
        all_tag, choice_tag = "DeleteStoredAll", "DeleteStoredByChoice"
        loc_field, pid_field = "deleteStoredLocations", "deleteStoredPids"
        noun = "created-object record"

    if args.list:
        print(
            f"{len(loc_keys)} {noun} location(s) and {len(pid_triples)} PID(s) on "
            f"LJ {args.serial}\n"
        )
        for l, key in zip(locs, loc_keys):
            extra = (
                f"  refId={l.get('storedLocationIdRef')}"
                if args.target == "stored"
                else ""
            )
            name = l.get("storedLocationName") or l.get("uncreatedLocationName")
            print(f"  --location {key!r}\n      name={name!r}{extra}")
        for pid, t in zip(pids, pid_triples):
            desc = pid.get("storedPidDescription") or pid.get(
                "uncreatedPidDescription"
            )
            print(f"  --pid {'::'.join(t)!r}\n      desc={desc!r}")
        return

    sel_locs = list(args.location)

    if not args.all and not (sel_locs or sel_pids):
        _fail(
            f"Nothing selected. Pass --all to delete every {noun}, or "
            f"--location/--pid (see --list)."
        )
    else:
        unknown = [k for k in sel_locs if k not in set(loc_keys)]
        if unknown:
            _fail(f"Not present in the {noun} set: {unknown}. Run --list.")
        unknown_p = [t for t in sel_pids if t not in set(pid_triples)]
        if unknown_p:
            _fail(
                f"Not present in the {noun} set: "
                f"{['::'.join(t) for t in unknown_p]}. Run --list."
            )

    if args.all:
        body = {"tag": all_tag}  # nullary constructor: no contents key
        n_locs, n_pids = len(loc_keys), len(pid_triples)
    else:
        body = {
            "tag": choice_tag,
            "contents": {
                loc_field: [{"unLocationUniqueIdentifier": k} for k in sel_locs],
                pid_field: [pid_identifier(t) for t in sel_pids],
            },
        }
        n_locs, n_pids = len(sel_locs), len(sel_pids)

    print(
        f"Would delete {n_locs} location(s) and {n_pids} PID(s) from the {noun} "
        f"set on LJ {args.serial}.\n"
    )
    if not args.all:
        for k in sel_locs:
            print(f"  - location {k!r}")
        for t in sel_pids:
            print(f"  - pid      {'::'.join(t)}")
        print()

    if args.target == "uncreated":
        print(
            "Consequences:\n"
            "  Nothing in OnPing or the mqtt-json driver is touched.\n"
            "  Deleting a location CASCADES to its PIDs.\n"
            "  REVERSIBLE the wrong way: the next rule execution regenerates these "
            "from the same unprocessed data. To stop them returning, use "
            "onping-mqtt-integrator-blacklist instead."
        )
    else:
        print(
            "Consequences — read before proceeding:\n"
            "  The real OnPing locations and mqtt-json parameters KEEP EXISTING. "
            "This only makes the integrator forget them, leaving them ORPHANED.\n"
            "  Forgetting also UN-SUPPRESSES creation: the create pipeline skips "
            "only what it has a record of, so a later run can create DUPLICATES of "
            "these objects.\n"
            "  Back up losslessly first: onping-mqtt-integrator-artifacts-export "
            f"<token> {args.serial} --json"
        )

    if args.dry_run or not args.yes:
        why = "--dry-run" if args.dry_run else "no --yes"
        print(f"\nNothing deleted ({why}). Re-run with --yes to apply.")
        return

    resp = post_json(
        args.access_token, endpoint(route_key), body, serial=args.serial
    )
    report_write(resp, what=f"{noun} delete for LJ {args.serial}")
    print(f"\nDeleted from the {noun} set on LJ {args.serial}.")

    if args.target == "stored":
        print(
            "Reminder: those objects still exist in OnPing and the driver, and are "
            "now eligible for re-creation. Blacklist them if that is not wanted."
        )


if __name__ == "__main__":
    main()
