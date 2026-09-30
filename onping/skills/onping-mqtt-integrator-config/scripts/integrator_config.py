# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read or update the mqtt-json-integrator MQTT connection config for one LJ.

Routes: GET  /mqtt/json/integrator/{serial}/mqtt/config
        POST /mqtt/json/integrator/{serial}/mqtt/config

The config is the top of the integrator UI: which broker and topic to subscribe
to, which Company/Site/Group generated objects land in, whether rules run
automatically on each message, and an optional cap on the unprocessed queue.

WHOLE-RECORD WRITE. The handler does `requireInsecureJsonBody :: MqttConfig`,
so a partial body would drop every field it omits. This script therefore always
READ-MODIFY-WRITES: it GETs the current record, applies only the flags you
passed, and POSTs the complete record back. It never invents a config from
nothing — if the GET fails, nothing is written.

MUTATES OnPing only with --yes. Without --yes (or with --dry-run) it prints a
before/after diff and exits without POSTing. --dry-run wins if both are passed.

FIELDS (MqttConfig, verified against the golden file
mqtt-json-integrator-types/golden/MqttConfig/MqttConfig.json):
    mqttConfigCompanyIdRef                  int
    mqttConfigSiteIdRef                     int
    mqttConfigGroupId                       string (mongo ObjectId)
    mqttConfigBroker                        string, expected to start with mqtt://
    mqttConfigTopic                         string, MQTT filter ('#' = everything)
    mqttConfigExecuteRulesOnMessageReceive  bool
    mqttConfigUnprocessedJsonObjectsSize    int or null (null = unlimited)

IDENTITY FIELDS ARE NOT EDITABLE HERE. Company, Site and Group decide where every
generated location and PID is filed. Repointing them mid-stream splits one
logical dataset across two places while leaving already-created objects behind,
so this skill refuses to change them; use the OnPing UI if that is really the
intent.

Source of truth (re-verify if these drift):
  - Handlers: onping/Handler/MqttJsonIntegrator/Service.hs (GET), :126 (POST)
  - Type:     mqtt-json-integrator-types/src/Mqtt/Json/Integrator/Types.hs
  - UI notes: mqtt-json-integrator/README.md, "Using the Web Interface"
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

# Fields this skill will change. Everything else is preserved as fetched.
EDITABLE = (
    "mqttConfigBroker",
    "mqttConfigTopic",
    "mqttConfigExecuteRulesOnMessageReceive",
    "mqttConfigUnprocessedJsonObjectsSize",
)

# Fields this skill refuses to change — they decide where generated objects land.
PROTECTED = (
    "mqttConfigCompanyIdRef",
    "mqttConfigSiteIdRef",
    "mqttConfigGroupId",
)

LABELS = {
    "mqttConfigBroker": "Broker",
    "mqttConfigTopic": "Topic",
    "mqttConfigExecuteRulesOnMessageReceive": "Auto-execute rules on message",
    "mqttConfigUnprocessedJsonObjectsSize": "Unprocessed queue cap",
    "mqttConfigCompanyIdRef": "Company refId",
    "mqttConfigSiteIdRef": "Site refId",
    "mqttConfigGroupId": "Group id",
}


def _show(key: str, value) -> str:
    if key == "mqttConfigUnprocessedJsonObjectsSize" and value is None:
        return "null (unlimited)"
    return json.dumps(value)


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Read or update one Lumberjack's mqtt-json-integrator MQTT config "
            "by read-modify-write. Mutates OnPing only with --yes."
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("serial", help="LJSerial of the Lumberjack running the integrator")
    p.add_argument(
        "--broker",
        help="MQTT broker URI; expected to start with mqtt:// and may include a "
        ":port suffix",
    )
    p.add_argument(
        "--topic",
        help="MQTT topic filter to subscribe to ('#' subscribes to everything)",
    )
    auto = p.add_mutually_exclusive_group()
    auto.add_argument(
        "--auto-execute",
        dest="auto_execute",
        action="store_true",
        default=None,
        help="run the generation rules automatically on every received message",
    )
    auto.add_argument(
        "--no-auto-execute",
        dest="auto_execute",
        action="store_false",
        help="require a manual rules execution (see "
        "onping-mqtt-integrator-reports --execute)",
    )
    cap = p.add_mutually_exclusive_group()
    cap.add_argument(
        "--queue-cap",
        type=int,
        help="reject new unprocessed objects once this many are stored",
    )
    cap.add_argument(
        "--no-queue-cap",
        action="store_true",
        help="remove the cap (store unprocessed objects without limit)",
    )
    p.add_argument("--json", action="store_true", help="emit the raw config JSON")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and show the diff, never POST (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually perform the write")
    args = p.parse_args()

    current = get_json(
        args.access_token, endpoint("get_config"), serial=args.serial
    )
    if not isinstance(current, dict):
        _fail(f"Expected an MqttConfig object, got: {json.dumps(current)[:400]}")

    # ── read-only path ──────────────────────────────────────────────────────
    changes: dict[str, object] = {}
    if args.broker is not None:
        changes["mqttConfigBroker"] = args.broker
    if args.topic is not None:
        changes["mqttConfigTopic"] = args.topic
    if args.auto_execute is not None:
        changes["mqttConfigExecuteRulesOnMessageReceive"] = args.auto_execute
    if args.no_queue_cap:
        changes["mqttConfigUnprocessedJsonObjectsSize"] = None
    elif args.queue_cap is not None:
        if args.queue_cap < 1:
            _fail("--queue-cap must be >= 1; use --no-queue-cap for unlimited.")
        changes["mqttConfigUnprocessedJsonObjectsSize"] = args.queue_cap

    if not changes:
        if args.json:
            print(json.dumps(current, indent=2, sort_keys=True))
        else:
            print(f"mqtt-json-integrator config for LJ {args.serial}\n")
            for key in EDITABLE + PROTECTED:
                if key in current:
                    tag = "" if key in EDITABLE else "   (not editable here)"
                    print(f"  {LABELS.get(key, key):<32} {_show(key, current[key])}{tag}")
            extra = set(current) - set(EDITABLE) - set(PROTECTED)
            for key in sorted(extra):
                print(f"  {key:<32} {_show(key, current[key])}   (unrecognized field)")
            print(
                "\nNo changes requested. Pass --broker/--topic/--auto-execute/"
                "--queue-cap to edit."
            )
        return

    # ── warn about no-op edits ──────────────────────────────────────────────
    effective = {k: v for k, v in changes.items() if current.get(k) != v}
    if not effective:
        print(
            "Every requested value already matches the stored config; nothing "
            "to do."
        )
        return

    if str(changes.get("mqttConfigBroker", "")).strip() and not str(
        changes.get("mqttConfigBroker", "")
    ).startswith("mqtt://"):
        print(
            f"WARNING: broker {changes['mqttConfigBroker']!r} does not start with "
            f"mqtt:// — the integrator UI documents that prefix as required.",
            file=sys.stderr,
        )

    updated = dict(current)
    updated.update(effective)

    # Belt-and-braces: prove we never touch an identity field.
    for key in PROTECTED:
        if key in current and updated.get(key) != current.get(key):
            _fail(f"refusing to change protected field {key}")

    print(f"mqtt-json-integrator config changes for LJ {args.serial}:\n")
    for key, value in effective.items():
        print(
            f"  {LABELS.get(key, key)}\n"
            f"      before: {_show(key, current.get(key))}\n"
            f"      after:  {_show(key, value)}"
        )

    if args.dry_run or not args.yes:
        why = "--dry-run" if args.dry_run else "no --yes"
        print(f"\nNot written ({why}). Re-run with --yes to apply.")
        return

    resp = post_json(
        args.access_token, endpoint("post_config"), updated, serial=args.serial
    )
    report_write(resp, what=f"config update for LJ {args.serial}")
    print(f"\nWrote config for LJ {args.serial}.")

    if "mqttConfigBroker" in effective or "mqttConfigTopic" in effective:
        print(
            "Note: changing the broker or topic re-subscribes the live MQTT "
            "connection. Already-stored unprocessed objects are kept."
        )


if __name__ == "__main__":
    main()
