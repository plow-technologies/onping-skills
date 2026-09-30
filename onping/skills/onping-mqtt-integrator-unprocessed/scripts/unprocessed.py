# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Inspect (and optionally clear) the mqtt-json-integrator unprocessed queue.

Routes: GET  /mqtt/json/integrator/{serial}/unprocessed/data
        GET  /mqtt/json/integrator/{serial}/unprocessed/data/export
        POST /mqtt/json/integrator/{serial}/unprocessed/json/objects/delete

This is the front of the pipeline: raw MQTT topic/message pairs the integrator
has collected, plus the locations and PIDs its rules have generated from them but
which have not yet been pushed to OnPing.

    MQTT -> [unprocessed] -> [rules] -> uncreated -> created -> mqtt-json driver
             ^ this skill                ^ this skill too

THREE COLLECTIONS IN ONE RESPONSE (UnprocessedData):
  unprocessedJsonObjects  raw [topic, message] PAIRS — 2-element arrays, stored
                          as a SET, so one copy per exact topic+message
                          combination. A repeated topic with a different payload
                          is a separate entry, and vice versa.
  uncreatedLocations      locations the rules produced, not yet created
  uncreatedPids           PIDs the rules produced, not yet created

WHY THE QUEUE STOPS FILLING. If mqttConfigUnprocessedJsonObjectsSize is set, the
queue does NOT evict — once full it IGNORES new messages and preserves what it
has. Raising the cap (onping-mqtt-integrator-config --queue-cap) or clearing the
queue (--clear here) is the only way to resume ingestion. Silence from a
correctly configured broker usually means this, not a connection problem.

--clear IS DESTRUCTIVE AND UNCONDITIONAL. The route takes no body and no
selection: it drops ALL stored topic/message pairs. It does not touch rules,
uncreated objects, or created objects. There is no import counterpart and no
undo, so --export first if the payloads matter (they are the only record of what
the broker actually sent).

Source of truth (re-verify if these drift):
  - Handlers:  onping/Handler/MqttJsonIntegrator/Service.hs (GET),
               :148 (export), :270 (delete)
  - Type:      mqtt-json-integrator-types/.../Types.hs (UnprocessedData)
  - Lifecycle: mqtt-json-integrator/data-lifetime-and-uniqueness-rules.md,
               "Unprocessed Data"
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
    report_write,
)
from _mqtt_integrator_routes.routes import endpoint


def _topic_of(entry) -> str:
    """unprocessedJsonObjects entries are [topic, message] 2-element arrays."""
    if isinstance(entry, list) and entry:
        return str(entry[0])
    return "?"


def _message_of(entry):
    if isinstance(entry, list) and len(entry) > 1:
        return entry[1]
    return None


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Inspect the mqtt-json-integrator unprocessed queue and the "
            "not-yet-created objects its rules produced. Clearing the queue "
            "requires --clear --yes."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument(
        "--json", action="store_true", help="emit the raw UnprocessedData JSON"
    )
    p.add_argument(
        "--export",
        metavar="PATH",
        help="write the raw topic/message pairs to a JSON file. Uses the "
        "server's own export route, which returns ONLY the pairs (not the "
        "uncreated sets)",
    )
    p.add_argument(
        "--topics",
        action="store_true",
        help="list the distinct topics seen, with a message count each",
    )
    p.add_argument(
        "--show",
        type=int,
        metavar="N",
        help="print the first N topic/message pairs in full",
    )
    p.add_argument(
        "--uncreated",
        action="store_true",
        help="list the uncreated locations and PIDs the rules have generated",
    )
    p.add_argument(
        "--clear",
        action="store_true",
        help="DESTRUCTIVE: delete ALL stored topic/message pairs (no selection "
        "is possible). Requires --yes.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="with --clear, report what would be deleted and stop (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually perform the clear")
    args = p.parse_args()

    data = get_json(
        args.access_token, endpoint("get_unprocessed"), serial=args.serial
    )
    if not isinstance(data, dict):
        _fail(f"Expected an UnprocessedData object, got: {json.dumps(data)[:400]}")

    pairs = data.get("unprocessedJsonObjects") or []
    locations = data.get("uncreatedLocations") or []
    pids = data.get("uncreatedPids") or []

    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"mqtt-json-integrator unprocessed data for LJ {args.serial}\n")
        print(f"  unprocessed topic/message pairs : {len(pairs)}")
        print(f"  uncreated locations             : {len(locations)}")
        print(f"  uncreated PIDs                  : {len(pids)}")
        if not pairs:
            print(
                "\nThe queue is empty. Either no MQTT data has arrived, the "
                "broker/topic in the config is wrong, or the queue was cleared. "
                "Check onping-mqtt-integrator-config."
            )
        if pairs and not locations and not pids:
            print(
                "\nData is arriving but no objects were generated — the rules "
                "matched nothing. Check them with "
                "onping-mqtt-integrator-rules-export --summary and confirm the "
                "rules ran (onping-mqtt-integrator-reports)."
            )

    # ── the server's own export route ───────────────────────────────────────
    if args.export:
        exported = get_json(
            args.access_token, endpoint("export_unprocessed"), serial=args.serial
        )
        out = Path(args.export)
        out.write_text(
            json.dumps(exported, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        count = len(exported) if isinstance(exported, list) else "?"
        print(f"\nWrote {count} topic/message pair(s) to {out}")

    if args.topics:
        by_topic: dict[str, int] = {}
        for entry in pairs:
            t = _topic_of(entry)
            by_topic[t] = by_topic.get(t, 0) + 1
        print(f"\n{len(by_topic)} distinct topic(s):\n")
        for topic, count in sorted(by_topic.items(), key=lambda kv: (-kv[1], kv[0])):
            suffix = f"   ({count} distinct messages)" if count > 1 else ""
            print(f"  {topic}{suffix}")
        print(
            "\nA topic appearing more than once means the queue holds several "
            "DIFFERENT payloads for it — entries are unique per (topic, message) "
            "pair, not per topic."
        )

    if args.show:
        print(f"\nFirst {min(args.show, len(pairs))} pair(s):\n")
        for entry in pairs[: args.show]:
            print(f"  topic: {_topic_of(entry)}")
            print(
                "  message: "
                + json.dumps(_message_of(entry), indent=2, sort_keys=True).replace(
                    "\n", "\n  "
                )
            )
            print()

    if args.uncreated:
        print(f"\n{len(locations)} uncreated location(s):\n")
        for loc in locations:
            key = (loc.get("uncreatedLocationUniqueIdentifier") or {}).get(
                "unLocationUniqueIdentifier", "?"
            )
            print(f"  name={loc.get('uncreatedLocationName')!r}  key={key!r}")
        print(f"\n{len(pids)} uncreated PID(s):\n")
        for pid in pids:
            uid = pid.get("uncreatedPidUniqueIdentifier") or {}
            src = uid.get("pidMqttJsonSourceId") or {}
            loc_key = (uid.get("pidLocationUniqueIdentifier") or {}).get(
                "unLocationUniqueIdentifier", "?"
            )
            print(
                f"  {_truncate(str(pid.get('uncreatedPidDescription')), 44)!r}\n"
                f"      location={loc_key!r}\n"
                f"      topic={src.get('mqttJsonSourceTopic')!r}  "
                f"valueSelector={src.get('valueSelector')!r}"
            )
        if locations or pids:
            print(
                "\nThese are candidates for onping-mqtt-integrator-create, which "
                "creates them for real in OnPing and the mqtt-json driver. "
                "Blacklisted entries are filtered out server-side at create time."
            )

    # ── the destructive path ────────────────────────────────────────────────
    if not args.clear:
        return

    print(
        f"\n--clear would delete ALL {len(pairs)} stored topic/message pair(s) "
        f"for LJ {args.serial}.\n"
        f"It does NOT touch rules ({len(locations)} uncreated locations and "
        f"{len(pids)} uncreated PIDs are unaffected) and there is no undo."
    )

    if args.dry_run or not args.yes:
        why = "--dry-run" if args.dry_run else "no --yes"
        print(f"Not cleared ({why}). Re-run with --clear --yes to apply.")
        if not args.export:
            print(
                "Consider --export PATH first: these payloads are the only "
                "record of what the broker sent, and there is no import route."
            )
        return

    resp = post_empty(
        args.access_token, endpoint("delete_unprocessed"), serial=args.serial
    )
    report_write(resp, what=f"unprocessed clear for LJ {args.serial}")
    print(f"Cleared the unprocessed queue for LJ {args.serial}.")
    print(
        "Ingestion resumes now if the queue had hit "
        "mqttConfigUnprocessedJsonObjectsSize."
    )


if __name__ == "__main__":
    main()
