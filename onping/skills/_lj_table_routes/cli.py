"""Shared CLI pieces: argument helpers, grid printers, and the verified write flows.

The write flows implement steps 4-8 of the mutating contract (see `mutate.py`)
once, so every column skill previews, gates, backs up, posts, and reads back
the same way.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from . import datatable as dt
from . import logtable as lt
from .lj_http import LJTableError, die
from .mutate import should_post, write_backup
from .pointers import Pointer, from_cli, normalize_selector


def base_parser(description: str, *, needs_table: bool = True) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("access_token", help="OnPing bearer token from onping-login")
    if needs_table:
        p.add_argument("lj", type=int, help="Lumberjack serial the table lives on")
        p.add_argument("table_uuid", help="the table's UUID (from the -list skill)")
    return p


def pointer_args(p: argparse.ArgumentParser, *, prefix: str = "", what: str = "") -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument(f"--{prefix}pid", type=int, metavar="N", help=f"{what} PID N".strip())
    g.add_argument(f"--{prefix}vpid", type=int, metavar="N", help=f"{what} VPID N".strip())


def pointer_from(args: argparse.Namespace, prefix: str = "") -> Pointer | None:
    key = prefix.replace("-", "_")
    return from_cli(getattr(args, f"{key}pid"), getattr(args, f"{key}vpid"))


def selector_arg(value: str) -> str:
    try:
        return normalize_selector(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def dump(obj: Any, path: str | None = None) -> None:
    text = json.dumps(obj, indent=2, sort_keys=True, default=str)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(path)
    else:
        print(text)


def _short(sel: str | None) -> str:
    return str(sel or "").removesuffix("TagSelector")


def print_datatable_grid(src: dict, marks: dict[str, str] | None = None) -> None:
    marks = marks or {}
    print(f"{'pos':>4}  {'uuid':36}  {'selector':18}  {'hidden':6}  name")
    for c in dt.columns(src):
        print(f"{c['position']:>4}  {c['id']:36}  {_short(c['selector']):18}  "
              f"{'yes' if c['hidden'] else '':6}  {c['name']}{marks.get(c['id'], '')}")


def print_logtable_grid(sch: dict, marks: dict[str, str] | None = None) -> None:
    marks = marks or {}
    print(f"{'pos':>4}  {'uuid':36}  {'key':14}  {'selector':18}  {'event':5}  {'hidden':6}  name")
    for c in lt.columns(sch):
        print(f"{c['position']:>4}  {c['id']:36}  {str(c['key']):14}  {_short(c['selector']):18}  "
              f"{'*' if c['event'] else '':5}  {'yes' if c['hidden'] else '':6}  "
              f"{c['name']}{marks.get(c['id'], '')}")


# ------------------------------------------------------------ write flows

def datatable_metadata_flow(args: argparse.Namespace, token: str, before: dict, after: dict,
                            *, title: str, marks: dict[str, str] | None = None,
                            warning: str | None = None, backup_state: Any = None) -> None:
    """Preview a header edit, then gate, back up, POST metadata/update, and verify."""
    print(f"{title}\nData table {before['tableName']!r} ({before['tableId']}) on LJ {before['tableLJSerial']}\n")
    print("BEFORE")
    print_datatable_grid(before)
    print("\nAFTER")
    print_datatable_grid(after, marks)
    if warning:
        print(f"\n⚠️  {warning}")
    if not should_post(args):
        return
    write_backup(args, "datatable", before["tableLJSerial"], before["tableId"],
                 before if backup_state is None else backup_state)
    try:
        dt.post_metadata(token, after)
        print("POST metadata/update: OK")
        readback = dt.find_source(token, before["tableLJSerial"], before["tableId"])
    except LJTableError as e:
        die(e)
    problems = dt.header_mismatches(after, readback)
    if problems:
        fail("read-back does not match what was sent:\n  - " + "\n  - ".join(problems))
    print("Read-back matches: the header now has "
          f"{len(dt.columns(readback))} column(s) in the expected order.")


def logtable_upgrade_flow(args: argparse.Namespace, token: str, stored: dict,
                          mutate: Callable[[dict], Any], *, title: str,
                          marks_for: Callable[[Any], dict[str, str]] = lambda r: {}) -> Any:
    """Build v+1 with `mutate`, preview it, then gate, back up, POST schema/upgrade, and verify."""
    try:
        body, new, result = lt.next_version(stored, mutate)
    except ValueError as e:
        fail(str(e))
    v = stored["logTableSourceSchemaVersion"]
    print(f"{title}\nLog table {stored['logTableSourceName']!r} ({stored['logTableSourceId']}) "
          f"on LJ {stored['logTableSourceLJSerial']}\n")
    print(f"BEFORE (schema version {v})")
    print_logtable_grid(lt.schema(stored))
    print(f"\nAFTER (schema version {v + 1})")
    print_logtable_grid(new, marks_for(result))
    for note in (result if isinstance(result, list) else []):
        print(f"\nNOTE: {note}")
    print(f"\n⚠️  This creates schema version {v + 1}, whose table starts EMPTY. Rows recorded "
          f"under version {v} stay readable with onping-logtable-fetch --version {v}; they are "
          "not migrated. Column UUIDs are kept, so a later migration can map them.")
    if not should_post(args):
        return result
    write_backup(args, "logtable", stored["logTableSourceLJSerial"], stored["logTableSourceId"], stored)
    try:
        lt.post_upgrade(token, body)
        print(f"POST schema/upgrade: OK (version {v + 1})")
        readback = lt.find_source(token, stored["logTableSourceLJSerial"], stored["logTableSourceId"])
    except LJTableError as e:
        die(e)
    problems = lt.upgrade_mismatches(body, readback)
    if problems:
        fail("read-back does not match what was sent:\n  - " + "\n  - ".join(problems))
    print(f"Read-back matches: version {readback['logTableSourceSchemaVersion']}, "
          f"{len(lt.columns(lt.schema(readback)))} column(s), event PID "
          f"{lt.schema(readback)['logSchemaHeader']['schemaHeaderEventSource']}.")
    return result

