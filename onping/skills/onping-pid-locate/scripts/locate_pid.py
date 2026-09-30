# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Resolve OnPing PIDs to their location, site, company, source, and value.

Read-only. Calls `POST /json/listers/v3/parameters` once with
`ParameterRequestOnpingKey`, which answers a bare PID directly — the PID-first
lookup the rest of the catalog lacks (`onping-parameters` needs a location before
it can list parameters; `onping-driver-resolve` needs a location refId).

Two behaviors of that route shape this script, both verified live 2026-08-21 and
both capable of producing a confident wrong answer:

1. **Missing PIDs vanish.** `applyMask` keeps only tags whose location is in the
   caller's authorized map and drops the rest with no marker, so a nonexistent
   PID, a deleted one, and one at an unauthorized location are indistinguishable.
   `[99999999]` returns `[]`. This script therefore emits one entry per REQUESTED
   PID with an explicit found state and exits non-zero if any is missing, rather
   than letting a short list read as success.

2. **Response order is not request order.** `[500001, 99999999, 500002]` came
   back `[500002, 500001]`. Results are keyed by the response's own
   `parameterId`, never zipped positionally — a positional zip would report one
   PID's location for another.

3. **A bare integer MEANS PID, so a VPID needs an explicitly tagged key.** Until
   2026-08-21 `--vp` toggled only the option flags and left the ids encoded as
   bare integers, which the server reads as `KeyPID` — so a VPID matched nothing
   and was reported `NOT FOUND` with a note asserting it did not exist. A live
   VPID being called nonexistent was read as "the control loop is dead" for four
   producing wells over 56 days; the loop was 3 hours fresh. `--vp` now says
   "these ids are VPIDs" and changes the key encoding, and a VPID's value is
   fetched from the location-scoped route because the keyed route never computes
   one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Import the shared PID lookup as a sibling module from the skills root. The
# lookup is shared with onping-pid-write so that skill's --verify read-back and
# --via-hmi envelope agree with what this skill reports.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _pid_routes.pid_http import lookup_pids, resolve_names  # noqa: E402
from _pid_routes.routes import ROUTES  # noqa: E402


def _print_table(entries: dict[int, dict], *, show_names: bool) -> None:
    width = max(len("PID"), *(len(str(p)) for p in entries))

    for pid, e in entries.items():
        label = str(pid).ljust(width)
        if not e.get("found"):
            # Two distinct headlines. "NOT ADDRESSABLE" must never read as
            # "does not exist": that conflation is the whole reason this skill
            # once corroborated a 56-day phantom outage.
            if e.get("unaddressable"):
                print(f"{label}  NOT ADDRESSABLE — {e['note']}")
            else:
                print(f"{label}  NOT FOUND — {e['note']}")
            continue

        loc_name = e.get("location_name") or "(unnamed)"
        print(f"{label}  {loc_name}  (location {e.get('location_id')})")

        source = e.get("source") or {}
        source_str = source.get("source", "?") if isinstance(source, dict) else str(source)
        extras = (
            ", ".join(f"{k}={v}" for k, v in source.items() if k != "source")
            if isinstance(source, dict)
            else ""
        )
        if extras:
            source_str = f"{source_str} ({extras})"

        site = e.get("site_name") or e.get("site") if show_names else e.get("site")
        company = (
            e.get("company_name") or e.get("company") if show_names else e.get("company")
        )

        pad = " " * width
        print(f"{pad}  description : {e.get('description') or ''}")
        # A value the route declined to compute is NOT printed as `None [None]`,
        # which would read as "this parameter has no value" — a quieter version
        # of the same wrong answer.
        if e.get("value_uncomputed"):
            print(f"{pad}  value       : UNKNOWN — not computed by any route tried")
            print(f"{pad}                {e.get('note')}")
        else:
            print(f"{pad}  value       : {e.get('value')!r}  [{e.get('value_tag')}]")
        print(f"{pad}  source      : {source_str}")
        print(f"{pad}  site        : {site}")
        print(f"{pad}  company     : {company}")
        print(f"{pad}  unit        : {e.get('unit')}")
        print(f"{pad}  writeability: {e.get('writeability')}  (advisory — see onping-pid-write)")
        print(f"{pad}  slaveId/url : {e.get('location_slave_id')} / {e.get('location_url') or ''}")
        print(f"{pad}  lastUpdate  : {e.get('last_update')}")

        # The plural in `tagLocations` is real only for VPIDs; for a PID the
        # handler wraps exactly one. Surface extras rather than hiding them.
        locations = e.get("locations") or []
        if len(locations) > 1:
            names = ", ".join(str(loc.get("name")) for loc in locations)
            print(f"{pad}  locations   : {len(locations)} — {names}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Resolve OnPing PIDs to their location, site, company, driver "
        "source, and current value (read-only; one lister call for PIDs, two for "
        "VPIDs since the keyed route never computes a VP value).",
        epilog=f"Route: {ROUTES['locate']['endpoint']}  handler: {ROUTES['locate']['handler']}",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token (from onping-login)")
    p.add_argument("pids", nargs="+", help="one or more numeric PIDs (or VPIDs with --vp)")
    p.add_argument(
        "--vp",
        action="store_true",
        help="treat the given ids as VPIDs: sends them as tagged VPID keys "
        "(a bare integer means PID and cannot address a virtual parameter) and "
        "fetches their values from the location-scoped route, which costs one "
        "extra request",
    )
    p.add_argument(
        "--names",
        action="store_true",
        help="resolve site and company refs to names (2 extra calls)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON keyed by PID")
    p.add_argument("--output", help="write to this path instead of stdout")
    args = p.parse_args()

    # Reject non-integer PIDs locally: no request is issued for input we can
    # already tell is wrong.
    pids: list[int] = []
    for raw in args.pids:
        try:
            pids.append(int(raw))
        except ValueError:
            print(f"PID must be an integer, got {raw!r}", file=sys.stderr)
            sys.exit(1)

    # De-duplicate but keep the caller's order — duplicates collapse server-side
    # ([500001, 500001] returns 1 item), and we still emit one entry per PID asked for.
    seen: set[int] = set()
    unique = [p for p in pids if not (p in seen or seen.add(p))]

    # `--vp` is a statement about the ids on the command line, not a response
    # filter: it decides whether each id is encoded as a tagged VPID or PID key.
    if args.vp:
        entries = lookup_pids(args.access_token, [], vpids=unique)
    else:
        entries = lookup_pids(args.access_token, unique)
    if args.names:
        resolve_names(args.access_token, entries)

    if args.json:
        rendered = json.dumps({str(k): v for k, v in entries.items()}, indent=2)
        if args.output:
            Path(args.output).write_text(rendered + "\n")
            print(args.output)
        else:
            print(rendered)
    else:
        if args.output:
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                _print_table(entries, show_names=args.names)
            Path(args.output).write_text(buf.getvalue())
            print(args.output)
        else:
            _print_table(entries, show_names=args.names)

    # A partial result is not a success: exit non-zero so a caller that only
    # checks the status cannot mistake a silently-dropped PID for one that
    # resolved. The PIDs that DID resolve are still printed above.
    #
    # THREE outcomes, three exit codes. A bare non-zero beside `NOT FOUND` is
    # read as confirmation of nonexistence — that is how this skill once helped
    # conclude four live wells were dead — so "could not address" and "value
    # unknown" get their own codes and their own words.
    missing = [
        pid
        for pid, e in entries.items()
        if not e.get("found") and not e.get("unaddressable")
    ]
    unaddressable = [pid for pid, e in entries.items() if e.get("unaddressable")]
    uncomputed = [pid for pid, e in entries.items() if e.get("value_uncomputed")]

    if missing:
        # Wording preserved verbatim ("PID(s)"), not modernized to "id(s)": this
        # line is observable output on the plain-PID path, which must stay
        # byte-identical. Accurate as-is, since an id addressed as a VPID lands
        # in `unaddressable` below rather than here.
        print(
            f"\n{len(missing)} of {len(entries)} PID(s) not found: "
            f"{', '.join(str(m) for m in missing)}",
            file=sys.stderr,
        )
    if unaddressable:
        print(
            f"\n{len(unaddressable)} id(s) could NOT BE ADDRESSED by this skill: "
            f"{', '.join(str(m) for m in unaddressable)}. This does not mean they "
            f"do not exist.",
            file=sys.stderr,
        )
    if uncomputed:
        print(
            f"\n{len(uncomputed)} id(s) resolved but their VALUE IS UNKNOWN: "
            f"{', '.join(str(m) for m in uncomputed)}. Not a report that they "
            f"have no value.",
            file=sys.stderr,
        )

    if missing:
        sys.exit(1)
    if unaddressable:
        sys.exit(3)
    if uncomputed:
        sys.exit(4)


if __name__ == "__main__":
    main()
