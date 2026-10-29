"""The mutating-primitive contract shared by every data-table and log-table write skill.

  1. read the current state;
  2. apply a pure local transform;
  3. validate;
  4. print a before/after preview;
  5. without --yes nothing is posted, and --dry-run wins over --yes;
  6. write a backup JSON of the pre-edit state (default path, or --backup PATH);
  7. POST;
  8. read back and compare; any mismatch exits non-zero.

This module holds steps 5 and 6 and the flags that drive them, so every write
skill gates the same way.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from typing import Any


def add_mutation_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--yes", action="store_true",
                   help="actually POST the change (without it, preview only)")
    p.add_argument("--dry-run", action="store_true",
                   help="preview only; never POST (wins over --yes)")
    p.add_argument("--backup", metavar="PATH",
                   help="where to write the pre-edit JSON backup "
                        "(default: ./<kind>-<lj>-<uuid>-<UTC>.backup.json)")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def should_post(args: argparse.Namespace) -> bool:
    if args.dry_run:
        print("\nDRY RUN — nothing was posted.")
        return False
    if not args.yes:
        print("\nPREVIEW ONLY — nothing was posted. Re-run with --yes to apply.")
        return False
    return True


def new_column_mark(args: argparse.Namespace, label: str = "new") -> str:
    """Grid marker for a column this run adds. The uuid4 is drawn per run, so a
    preview's UUID is not the one a later --yes run will store."""
    if args.yes and not args.dry_run:
        return f"   <-- {label}"
    return f"   <-- {label}; UUID is drawn again on --yes"


def write_backup(args: argparse.Namespace, kind: str, lj: Any, uuid: str, state: Any) -> str:
    path = args.backup or f"./{kind}-{lj}-{uuid}-{utc_stamp()}.backup.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")
    path = os.path.abspath(path)
    print(f"Backup of the pre-edit state: {path}")
    return path
