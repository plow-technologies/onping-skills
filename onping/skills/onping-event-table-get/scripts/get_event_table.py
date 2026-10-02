# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Read an OnPing event table's configuration as JSON by UUID.

`POST /event/table/config` with `{"unEventTableUUID": "<uuid>"}` returns the raw
`EventTableConfiguration`. Read-only — no `--yes` gate.

  --bindings   one row per key the table reads: each column, then a
               DynamicMaxEvents row-count key. The trigger is the column whose
               eventColumnIndex equals eventTableEventColumn.
  --pid N      answers whether PID N is bound, and where. REFERENCED and
               NOT REFERENCED both exit 0; a non-zero exit means the question
               could not be answered.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _event_table_routes.event_table_http import EventTableError, die, post_json
from _event_table_routes.keys import bindings, describe, max_events, pid_matches
from _event_table_routes.routes import ROUTES


def print_bindings(config: dict) -> None:
    kind, value = max_events(config)
    print(f"event table {config['eventTableUUID'].get('unEventTableUUID', '?')}")
    print(f"  trigger column index : {config.get('eventTableEventColumn')}")
    print(f"  max events           : {kind} {value}")
    print(f"  deleted              : {config.get('eventTableDeleted')}")
    print(f"  {'index':>5}  {'type':<4}  {'key':>9}  trigger  name")
    for b in bindings(config):
        index = "-" if b.index is None else str(b.index)
        flag = "yes" if b.trigger else ""
        print(f"  {index:>5}  {b.key.kind:<4}  {b.key.value:>9}  {flag:<7}  {b.name}")


def print_pid_answer(config: dict, pid: int) -> None:
    as_pid, as_vpid = pid_matches(config, pid)
    if as_pid:
        print(f"REFERENCED: PID {pid}")
        for b in as_pid:
            print(f"  {describe(b)}")
    else:
        print(f"NOT REFERENCED: PID {pid}")
    if as_vpid:
        print(f"  note: VPID {pid} is bound, which is a different parameter:")
        for b in as_vpid:
            print(f"    {describe(b)}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Get an OnPing event table's configuration as JSON via "
        "POST /event/table/config. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("uuid", help="event-table UUID (from onping-event-table-list)")
    p.add_argument("--output", help="write the configuration JSON to this file")
    p.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    p.add_argument("--bindings", action="store_true", help="print the flat bindings view")
    p.add_argument("--pid", type=int, help="report whether this PID is bound, and where")
    args = p.parse_args()

    try:
        config = post_json(
            args.access_token, ROUTES["config"]["endpoint"], {"unEventTableUUID": args.uuid}
        )
    except EventTableError as err:
        die(err)

    if config.get("eventTableDeleted"):
        print(f"note: event table {args.uuid} is soft-deleted (eventTableDeleted: true)",
              file=sys.stderr)

    rendered = json.dumps(config, indent=2 if args.pretty else None, sort_keys=args.pretty)
    if args.output:
        Path(args.output).write_text(rendered + "\n")
        print(f"Saved event table {args.uuid} to {args.output}", file=sys.stderr)

    if args.pid is not None:
        print_pid_answer(config, args.pid)
    if args.bindings:
        print_bindings(config)
    if args.pid is None and not args.bindings:
        print(rendered)


if __name__ == "__main__":
    main()
