# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read and edit the mqtt-json-integrator blacklist for one Lumberjack.

Routes: GET  /mqtt/json/integrator/{serial}/blacklist
        POST /mqtt/json/integrator/{serial}/blacklist

The blacklist prevents specific locations and PIDs from ever being created, even
when the rules keep generating them as candidates. Step one of the create
pipeline filters blacklisted entries server-side, so a blacklisted candidate is
skipped no matter how it was selected — including with --all.

BLACKLISTING BLOCKS CREATION; IT DOES NOT DELETE. An object that has already been
created stays created. To remove one you must delete it in OnPing and the
mqtt-json driver by hand; blacklisting only stops it coming back afterward. That
pairing — delete for real, then blacklist — is the durable way to get rid of an
object the rules insist on regenerating.

INCREMENTAL OPS, NOT A WHOLE LIST. The POST takes [UpdateBlacklist], a list of
add/remove operations, so concurrent editors do not clobber each other:
    {"tag": "BlacklistAddLocation",    "contents": {"unLocationUniqueIdentifier": "..."}}
    {"tag": "BlacklistRemoveLocation", "contents": {...}}
    {"tag": "BlacklistAddPid",         "contents": <PidUniqueIdentifier>}
    {"tag": "BlacklistRemovePid",      "contents": <PidUniqueIdentifier>}
Shapes verified against mqtt-json-integrator-types/golden/UpdateBlacklist/.

PIDS TAKE THREE VALUES. PidUniqueIdentifier is a two-field record — the location
key plus a source id of (topic, valueSelector) — not a scalar. Pass them joined
by '::'. --list-candidates prints the exact strings.

ENTRIES NEVER EXPIRE. Nothing cleans the blacklist up; it persists until removed.

MUTATES OnPing only with --yes.

Source of truth (re-verify if these drift):
  - Handlers: onping/Handler/MqttJsonIntegrator/Service.hs (GET), :247 (POST)
  - Types:    mqtt-json-integrator-types/.../Types.hs (Blacklist), :1043
              (UpdateBlacklist)
  - Filter:   the create pipeline's step one (Service.hs comment)
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
    post_json,
    report_write,
)
from _mqtt_integrator_routes.routes import endpoint


def pid_identifier(triple: tuple[str, str, str]) -> dict:
    location, topic, selector = triple
    return {
        "pidLocationUniqueIdentifier": {"unLocationUniqueIdentifier": location},
        "pidMqttJsonSourceId": {
            "mqttJsonSourceTopic": topic,
            "valueSelector": selector,
        },
    }


def triple_of(entry: dict) -> tuple[str, str, str]:
    src = entry.get("pidMqttJsonSourceId") or {}
    return (
        str((entry.get("pidLocationUniqueIdentifier") or {}).get(
            "unLocationUniqueIdentifier"
        ) or ""),
        str(src.get("mqttJsonSourceTopic") or ""),
        str(src.get("valueSelector") or ""),
    )


def parse_triple(raw: str, flag: str) -> tuple[str, str, str]:
    parts = raw.split("::")
    if len(parts) != 3:
        _fail(
            f"{flag} {raw!r} must be LOCKEY::TOPIC::SELECTOR (three parts joined "
            f"by '::'); got {len(parts)}. Run --list-candidates for exact values."
        )
    return tuple(parts)  # type: ignore[return-value]


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Read or edit the mqtt-json-integrator blacklist, which blocks "
            "specific locations and PIDs from ever being created. Mutates only "
            "with --yes."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument("--json", action="store_true", help="emit the raw Blacklist JSON")
    p.add_argument(
        "--list-candidates",
        action="store_true",
        help="list uncreated candidates and created objects with the exact "
        "selectors to blacklist, then exit",
    )
    p.add_argument(
        "--add-location",
        action="append",
        default=[],
        metavar="KEY",
        help="blacklist a location by unique identifier; repeatable",
    )
    p.add_argument(
        "--remove-location",
        action="append",
        default=[],
        metavar="KEY",
        help="un-blacklist a location; repeatable",
    )
    p.add_argument(
        "--add-pid",
        action="append",
        default=[],
        metavar="LOCKEY::TOPIC::SELECTOR",
        help="blacklist a PID; repeatable",
    )
    p.add_argument(
        "--remove-pid",
        action="append",
        default=[],
        metavar="LOCKEY::TOPIC::SELECTOR",
        help="un-blacklist a PID; repeatable",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show the operations that would be sent and stop (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually apply the changes")
    args = p.parse_args()

    # Parse the PID selectors BEFORE any network call, so a malformed triple
    # fails immediately instead of after a round-trip.
    add_locs = list(args.add_location)
    rm_locs = list(args.remove_location)
    add_pids = [parse_triple(r, "--add-pid") for r in args.add_pid]
    rm_pids = [parse_triple(r, "--remove-pid") for r in args.remove_pid]

    conflicts = (set(add_locs) & set(rm_locs)) | {
        "::".join(t) for t in set(add_pids) & set(rm_pids)
    }
    if conflicts:
        _fail(
            f"The same entry is both added and removed in one call: "
            f"{sorted(conflicts)}. The server applies the ops in order, so the "
            f"result would depend on argument order. Split into two calls."
        )

    current = get_json(
        args.access_token, endpoint("get_blacklist"), serial=args.serial
    )
    if not isinstance(current, dict):
        _fail(f"Expected a Blacklist object, got: {json.dumps(current)[:400]}")

    bl_locs = [
        str((e or {}).get("unLocationUniqueIdentifier") or "")
        for e in (current.get("blacklistLocationUniqueIdentifiers") or [])
    ]
    bl_pids = [
        triple_of(e or {})
        for e in (current.get("blacklistPidUniqueIdentifiers") or [])
    ]

    # ── --list-candidates ───────────────────────────────────────────────────
    if args.list_candidates:
        unproc = get_json(
            args.access_token, endpoint("get_unprocessed"), serial=args.serial
        )
        created = get_json(
            args.access_token, endpoint("get_artifacts"), serial=args.serial
        )
        print(f"Blacklist candidates on LJ {args.serial}\n")
        print("UNCREATED locations (blocking these stops future creation):\n")
        for l in unproc.get("uncreatedLocations") or []:
            key = (l.get("uncreatedLocationUniqueIdentifier") or {}).get(
                "unLocationUniqueIdentifier", ""
            )
            mark = "  [already blacklisted]" if key in bl_locs else ""
            print(f"  --add-location {key!r}{mark}")
        print("\nUNCREATED PIDs:\n")
        for pid in unproc.get("uncreatedPids") or []:
            t = triple_of(pid.get("uncreatedPidUniqueIdentifier") or {})
            mark = "  [already blacklisted]" if t in bl_pids else ""
            print(f"  --add-pid {'::'.join(t)!r}{mark}")
            print(f"      desc: {pid.get('uncreatedPidDescription')!r}")
        print(
            "\nALREADY-CREATED locations (blacklisting does NOT delete these — see "
            "the note below):\n"
        )
        for l in created.get("storedLocations") or []:
            key = (l.get("storedLocationUniqueIdentifier") or {}).get(
                "unLocationUniqueIdentifier", ""
            )
            mark = "  [already blacklisted]" if key in bl_locs else ""
            print(
                f"  --add-location {key!r}{mark}\n"
                f"      refId={l.get('storedLocationIdRef')} "
                f"name={l.get('storedLocationName')!r}"
            )
        print(
            "\nBlacklisting an already-created object does NOT remove it. Delete it "
            "in OnPing and the mqtt-json driver first, then blacklist it so the "
            "rules cannot regenerate it."
        )
        return

    # ── read-only path ──────────────────────────────────────────────────────
    if not (add_locs or rm_locs or add_pids or rm_pids):
        if args.json:
            print(json.dumps(current, indent=2, sort_keys=True))
        else:
            print(f"mqtt-json-integrator blacklist for LJ {args.serial}\n")
            print(f"  blacklisted locations : {len(bl_locs)}")
            for k in bl_locs:
                print(f"      {k!r}")
            print(f"  blacklisted PIDs      : {len(bl_pids)}")
            for t in bl_pids:
                print(f"      {'::'.join(t)}")
            if not bl_locs and not bl_pids:
                print(
                    "\nThe blacklist is empty; every candidate the rules generate "
                    "is eligible for creation."
                )
            print(
                "\nUse --list-candidates to see what could be blacklisted, with "
                "copy-pasteable selectors."
            )
        return

    # ── build the operation list ────────────────────────────────────────────
    ops: list[dict] = []
    noops: list[str] = []

    for k in add_locs:
        if k in bl_locs:
            noops.append(f"location {k!r} is already blacklisted")
        ops.append(
            {
                "tag": "BlacklistAddLocation",
                "contents": {"unLocationUniqueIdentifier": k},
            }
        )
    for k in rm_locs:
        if k not in bl_locs:
            noops.append(f"location {k!r} is not currently blacklisted")
        ops.append(
            {
                "tag": "BlacklistRemoveLocation",
                "contents": {"unLocationUniqueIdentifier": k},
            }
        )
    for t in add_pids:
        if t in bl_pids:
            noops.append(f"pid {'::'.join(t)} is already blacklisted")
        ops.append({"tag": "BlacklistAddPid", "contents": pid_identifier(t)})
    for t in rm_pids:
        if t not in bl_pids:
            noops.append(f"pid {'::'.join(t)} is not currently blacklisted")
        ops.append({"tag": "BlacklistRemovePid", "contents": pid_identifier(t)})

    print(f"{len(ops)} blacklist operation(s) for LJ {args.serial}:\n")
    for op in ops:
        tag = op["tag"]
        c = op["contents"]
        if "unLocationUniqueIdentifier" in c:
            print(f"  {tag}  {c['unLocationUniqueIdentifier']!r}")
        else:
            print(f"  {tag}  {'::'.join(triple_of(c))}")

    for n in noops:
        print(f"\n  note: {n} (the operation is harmless but changes nothing)")

    print(
        f"\nAfter this the blacklist would hold roughly "
        f"{len(set(bl_locs) | set(add_locs)) - len(set(rm_locs) & set(bl_locs))} "
        f"location(s) and "
        f"{len(set(bl_pids) | set(add_pids)) - len(set(rm_pids) & set(bl_pids))} "
        f"PID(s)."
    )
    if add_locs or add_pids:
        print(
            "Blacklisting blocks CREATION only — anything already created stays "
            "created."
        )

    if args.dry_run or not args.yes:
        why = "--dry-run" if args.dry_run else "no --yes"
        print(f"\nNot applied ({why}). Re-run with --yes.")
        return

    resp = post_json(
        args.access_token, endpoint("update_blacklist"), ops, serial=args.serial
    )
    report_write(resp, what=f"blacklist update for LJ {args.serial}")

    after = get_json(
        args.access_token, endpoint("get_blacklist"), serial=args.serial
    )
    n_locs = len(after.get("blacklistLocationUniqueIdentifiers") or [])
    n_pids = len(after.get("blacklistPidUniqueIdentifiers") or [])
    print(
        f"\nApplied. The blacklist now holds {n_locs} location(s) and "
        f"{n_pids} PID(s)."
    )


if __name__ == "__main__":
    main()
