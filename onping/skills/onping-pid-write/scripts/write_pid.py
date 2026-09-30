# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Write a typed value to an OnPing PID. MUTATING — requires --yes.

Default route is `POST /source/param/write-onping-result`, which takes only
`[pid, value]` and resolves the location and driver source SERVER-SIDE. That is
deliberate, and it is not the route the browser uses.

`POST /hmi/devices/writeV2` (the browser's route, available here as --via-hmi)
accepts a whole TagInfo and TRUSTS the routing fields inside it: nothing
re-derives `locationId` or `localParameterId` from `parameterId`, and
`writeOnpingParameter'` dispatches on `(sourceId, result)` while handing the
caller's `locationId` to whichever driver `sourceId` names. So a stale
`localParameterId` writes down the WRONG PROTOCOL DRIVER and a wrong
`locationId` writes to ANOTHER LOCATION — with a success status either way. The
default route makes both impossible. --via-hmi exists for the one thing it
uniquely does: writeV2 is the only route that writes a STRING to a TotalFlow
parameter (V1 lacks that arm entirely).

Two more things a caller must know, both enforced below:

  - **Numeric writes pass through a per-PID write mask that can change the
    value**, silently falling back to unmasked on mask error. A success status
    means accepted, never "this is what landed". --verify reads the value back.
  - **Writes are asynchronous.** Measured live: a 201 in 0.44s, the new value not
    readable for ~2.9s. So --verify polls until `lastUpdate` advances instead of
    reading once; a single immediate read returns the OLD value and would
    misreport a good write as `differs`.
  - **`writeability` is not a safety interlock.** No driver reads it from the
    request; only mqtt-json checks its own stored value. It is reported, never
    enforced.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Shared with onping-pid-locate so --verify's read-back and --via-hmi's envelope
# agree with what that skill reports.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _pid_routes.pid_http import fail, lookup_one, post_json, resolve_names  # noqa: E402
from _pid_routes.routes import ROUTES, VALUE_TAGS, translate_error  # noqa: E402


# ───────────────────────────── value construction ─────────────────────────────


def _build_value(args) -> tuple[dict, bool]:
    """Return (OnPingResult, masked).

    The type is ALWAYS explicit — never inferred from the shape of the input.
    `--text 0` stays text; inferring would make "0" and "off" behave differently
    for the same intent, and the three paths differ materially (numerics are
    masked; text into a numeric PID fails at fromOnPingResult).
    """
    if args.value is not None:
        spec = VALUE_TAGS["double"]
        return {"tag": spec["tag"], "value": args.value}, spec["masked"]
    if args.int is not None:
        spec = VALUE_TAGS["int"]
        return {"tag": spec["tag"], "value": args.int}, spec["masked"]
    if args.text is not None:
        spec = VALUE_TAGS["text"]
        return {"tag": spec["tag"], "value": args.text}, spec["masked"]
    spec = VALUE_TAGS["bool"]
    return {"tag": spec["tag"], "value": args.bool}, spec["masked"]


def _parse_bool(raw: str) -> bool:
    if raw.lower() in ("true", "1"):
        return True
    if raw.lower() in ("false", "0"):
        return False
    raise argparse.ArgumentTypeError(
        f"--bool takes true or false, got {raw!r}"
    )


# ─────────────────────────────── error reporting ──────────────────────────────


def _extract_hmi_error(payload) -> str:
    """Flatten a tagged HmiError into a readable chain.

    The HMI route wraps EVERY failure — permission denials included — in an
    HmiError re-sent as 500, so status cannot classify these; the tag chain must
    be read (HmiViewer.hs).
    """
    parts: list[str] = []
    node = payload
    while isinstance(node, dict) and "tag" in node:
        parts.append(str(node["tag"]))
        node = node.get("contents")
    if node is not None and not isinstance(node, dict):
        parts.append(str(node))
    return " -> ".join(parts) if parts else json.dumps(payload)


def _report_failure(resp, route_key: str) -> "None":
    """Print a classified failure and exit non-zero.

    Classification comes from the PAYLOAD, never the status code alone.
    """
    try:
        payload = resp.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict) and "error" in payload:
        server_text = str(payload["error"])
    elif isinstance(payload, dict) and "tag" in payload:
        server_text = _extract_hmi_error(payload)
    elif payload is not None:
        server_text = json.dumps(payload)
    else:
        server_text = resp.text[:500]

    print(f"WRITE FAILED (HTTP {resp.status_code})", file=sys.stderr)
    print(f"  server: {server_text}", file=sys.stderr)

    explanation = translate_error(server_text)
    if explanation:
        print(f"  meaning: {explanation}", file=sys.stderr)
    if route_key == "write_hmi" and resp.status_code == 500:
        print(
            "  note: this route returns 500 for client-caused failures too "
            "(including permission denials), so the 500 does not by itself mean "
            "a server fault.",
            file=sys.stderr,
        )
    sys.exit(1)


# ──────────────────────────────── the write ───────────────────────────────────


def _write_source(token: str, pid: int, value: dict):
    """POST /source/param/write-onping-result — body is a bare 2-tuple."""
    return post_json(token, ROUTES["write"]["endpoint"], [pid, value])


def _write_hmi(token: str, entry: dict, value: dict):
    """POST /hmi/devices/writeV2 with an envelope built from the LIVE lookup.

    Every routing field comes from `entry` (the lookup), never from user input —
    that is the whole reason this stays safe despite the route trusting them.
    `reqWriteUsername` is required by the parser but overwritten from the session
    (HmiViewer.hs), so it is always "" and has no flag.
    """
    otc = {
        "locationId": entry["location_id"],
        "companyId": entry["company"],
        "siteId": entry["site"],
        "parameterId": entry["pid"],
        "localParameterId": entry["source"],
        "description": entry.get("description") or "",
        "unit": {"unit": entry.get("unit") or "Pounds"},
        "writeability": entry.get("writeability") or "TagWriteable",
        "lastUpdate": entry.get("last_update") or 0,
        "result": value,
    }
    body = {"reqWriteOtc": otc, "reqWriteUsername": ""}
    return post_json(token, ROUTES["write_hmi"]["endpoint"], body)


# ─────────────────────────────────── main ─────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(
        description="Write a typed value to an OnPing PID (MUTATING — requires --yes).",
        epilog=(
            f"Default route: {ROUTES['write']['endpoint']} "
            f"({ROUTES['write']['handler']}); "
            f"--via-hmi: {ROUTES['write_hmi']['endpoint']} "
            f"({ROUTES['write_hmi']['handler']})"
        ),
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token (from onping-login)")
    p.add_argument("pid", help="the numeric PID to write")

    value_group = p.add_mutually_exclusive_group(required=True)
    value_group.add_argument("--value", type=float, help="write an OnPingDouble (masked)")
    value_group.add_argument("--int", type=int, help="write an OnPingInt (masked)")
    value_group.add_argument("--text", help="write an OnPingText (not masked)")
    value_group.add_argument(
        "--bool", type=_parse_bool, help="write an OnPingBool, true|false (not masked)"
    )

    p.add_argument(
        "--via-hmi",
        action="store_true",
        help="use POST /hmi/devices/writeV2 instead of the default route "
        "(needed only for TotalFlow string writes)",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help="re-read the PID after writing and report sent vs. landed",
    )
    p.add_argument(
        "--verify-timeout",
        type=float,
        default=15.0,
        help="seconds to wait for an asynchronous write to become readable "
        "(default: 15; measured propagation is ~1-3s)",
    )
    p.add_argument(
        "--verify-interval",
        type=float,
        default=1.0,
        help="seconds between read-back polls (default: 1)",
    )
    p.add_argument("--names", action="store_true", help="resolve site/company names for the report")
    p.add_argument("--json", action="store_true", help="emit a JSON report")
    p.add_argument("--yes", action="store_true", help="actually perform the write")
    args = p.parse_args()

    try:
        pid = int(args.pid)
    except ValueError:
        print(f"PID must be an integer, got {args.pid!r}", file=sys.stderr)
        sys.exit(1)

    value, masked = _build_value(args)
    route_key = "write_hmi" if args.via_hmi else "write"
    route = ROUTES[route_key]

    # Always resolve first: the dry run needs the location NAME (a refId is not
    # something a reviewer can sanity-check), and --via-hmi needs the envelope.
    entry = lookup_one(args.access_token, pid)
    if not entry.get("found"):
        # A PID this route cannot resolve might still be a live VIRTUAL
        # parameter, and virtual parameters are computed — not writable through
        # any of these routes. Check before echoing a not-found note that
        # asserts nonexistence: until 2026-08-21 a VPID target failed here
        # claiming it "does not exist, has been deleted, or belongs to a
        # location this token cannot see", all three false for a VP that was
        # updating every few minutes.
        as_vp = lookup_one(args.access_token, pid, as_vpid=True)
        if as_vp.get("found"):
            fail(
                f"{pid} is a VIRTUAL parameter "
                f"({as_vp.get('description') or 'no description'}, location "
                f"{as_vp.get('location_id')}). Virtual parameters are COMPUTED "
                f"from other parameters and cannot be written through these "
                f"routes — write the upstream parameter its script reads "
                f"instead. Nothing about this says the parameter does not "
                f"exist; use onping-pid-locate --vp to read it."
            )
        fail(f"PID {pid}: {entry['note']}")
    if args.names:
        resolve_names(args.access_token, {pid: entry})

    site = entry.get("site_name") or entry.get("site")
    company = entry.get("company_name") or entry.get("company")
    source = entry.get("source") or {}
    source_name = source.get("source") if isinstance(source, dict) else str(source)

    report = {
        "pid": pid,
        "location": {"refId": entry.get("location_id"), "name": entry.get("location_name")},
        "site": site,
        "company": company,
        "source": source,
        "description": entry.get("description"),
        "writeability": entry.get("writeability"),
        "current": {"value": entry.get("value"), "tag": entry.get("value_tag")},
        "new": {"value": value["value"], "tag": value["tag"]},
        "masked": masked,
        "route": route["endpoint"],
        "performed": False,
    }

    # A type change is worth flagging — text into a numeric parameter is what
    # produces WriteErrorDoubleConversion — but it is NOT blocked: a SourceManual
    # text tag legitimately reads OnPingText, and only the driver knows what it
    # accepts.
    current_tag = entry.get("value_tag")
    type_warning = None
    if current_tag and current_tag != value["tag"]:
        type_warning = (
            f"current value is {current_tag} but writing {value['tag']}; if this "
            f"parameter is numeric, expect WriteErrorDoubleConversion"
        )
        report["type_warning"] = type_warning

    def emit(extra_note: str | None = None) -> None:
        if args.json:
            print(json.dumps(report, indent=2))
            return
        print(f"PID {pid}  {entry.get('location_name')}  (location {entry.get('location_id')})")
        print(f"  description : {entry.get('description') or ''}")
        print(f"  site/company: {site} / {company}")
        print(f"  source      : {source_name}")
        print(f"  writeability: {entry.get('writeability')}  (advisory — never enforced from the request)")
        print(f"  current     : {entry.get('value')!r}  [{current_tag}]")
        print(f"  new         : {value['value']!r}  [{value['tag']}]")
        print(
            f"  write mask  : {'APPLIES — the landed value may differ' if masked else 'does not apply to this type'}"
        )
        print(f"  route       : {route['endpoint']}")
        if type_warning:
            print(f"  WARNING     : {type_warning}")
        if extra_note:
            print(f"  {extra_note}")

    if not args.yes:
        emit("DRY RUN — no write issued. Re-run with --yes to perform it.")
        if not args.json:
            print("\nNothing was written.")
        return

    resp = (
        _write_hmi(args.access_token, entry, value)
        if args.via_hmi
        else _write_source(args.access_token, pid, value)
    )

    # Success is 201 on the source route and 200 on the HMI route. Accept any 2xx
    # so a 200-only check cannot report every default-route write as a failure.
    if not (200 <= resp.status_code < 300):
        _report_failure(resp, route_key)

    report["performed"] = True
    report["status"] = resp.status_code

    if not args.verify:
        emit(f"WROTE — HTTP {resp.status_code}. Value accepted; not read back (--verify to check).")
        return

    # ── read-back ──
    # Three distinct outcomes. `differs` is NOT an error: a scaling write mask
    # makes it the expected result. `unverified` must never read as "the write
    # did not happen" — the write was accepted.
    #
    # WRITES DO NOT PROPAGATE SYNCHRONOUSLY. Measured live 2026-08-21: a 201 came
    # back in 0.44s but the new value was not readable for ~2.9s, and `lastUpdate`
    # still held its pre-write value in between. Reading once immediately after
    # the 201 therefore reports the OLD value and misclassifies a perfectly good
    # write as `differs` — the exact plausible-but-wrong result this skill exists
    # to prevent.
    #
    # So poll until `lastUpdate` advances past the pre-write value, which is the
    # signal that the write was recorded. We cannot poll for value equality
    # instead: a masked write legitimately lands a DIFFERENT value, so equality
    # may never arrive and `differs` must stay reachable.
    before_update = entry.get("last_update")
    after = None
    settled = False
    deadline = time.monotonic() + args.verify_timeout

    while True:
        after = lookup_one(args.access_token, pid)
        if not after.get("found"):
            break
        if after.get("last_update") != before_update:
            settled = True
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(args.verify_interval)

    if not after.get("found"):
        report["verify"] = "unverified"
        emit(
            f"WROTE — HTTP {resp.status_code}. The write WAS ACCEPTED, but the "
            f"read-back failed, so the landed value is unknown."
        )
        print(
            "\nverify: unverified — the write was accepted; only the read-back failed.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settled:
        # lastUpdate never moved. The write was accepted, so we must not claim it
        # failed — we only know the new value was not observable in time.
        report["verify"] = "unverified"
        report["landed"] = {"value": after.get("value"), "tag": after.get("value_tag")}
        emit(
            f"WROTE — HTTP {resp.status_code}. The write WAS ACCEPTED, but the "
            f"value did not become readable within {args.verify_timeout:g}s."
        )
        print(
            f"\nverify: unverified — the write was accepted; lastUpdate did not "
            f"advance within {args.verify_timeout:g}s, so the landed value is "
            f"unconfirmed. Writes are asynchronous (~1-3s is normal); retry the "
            f"read with onping-pid-locate, or raise --verify-timeout.",
            file=sys.stderr,
        )
        sys.exit(1)

    landed, landed_tag = after.get("value"), after.get("value_tag")
    report["landed"] = {"value": landed, "tag": landed_tag}
    matched = landed == value["value"] and landed_tag == value["tag"]
    report["verify"] = "match" if matched else "differs"

    if matched:
        emit(f"WROTE — HTTP {resp.status_code}. Read-back matches: {landed!r} [{landed_tag}].")
        return

    emit(f"WROTE — HTTP {resp.status_code}.")
    if not args.json:
        print(f"\nverify: DIFFERS — sent {value['value']!r} [{value['tag']}], "
              f"read back {landed!r} [{landed_tag}]")
        print("  This is not necessarily an error. Three things can explain it:")
        print("    1. the WRITE mask transformed the value on the way in;")
        print("    2. the READ mask transformed it on the way out (a separate config);")
        print("    3. the driver quantized it (e.g. a Double into a 16-bit register).")
    # Exit zero: `differs` is an expected outcome, not a failure.


if __name__ == "__main__":
    main()
