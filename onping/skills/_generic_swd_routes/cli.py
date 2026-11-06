"""Exit codes and output shared by the three generic-SWD scripts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import sys
from typing import Any

EXIT_OK = 0
EXIT_READ = 1  # a read failed, or a write was rejected and nothing changed
EXIT_USAGE = 2  # before any request
EXIT_REFUSED = 3  # guard, validation, drift or backup refusal; nothing written
EXIT_UNKNOWN = 4  # unknown outcome, or a read-back that does not match

UPDATE_SCRIPT = "~/.claude/skills/onping-generic-swd-update/scripts/update_generic_swd.py"


class Parser(argparse.ArgumentParser):
    def error(self, message: str):  # usage errors exit 2 before any request
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def restore_command(uuid: str, backup: str) -> str:
    return f"uv run {UPDATE_SCRIPT} {shlex.quote(uuid)} replace --from {shlex.quote(str(backup))} --yes"


def emit(as_json: bool, doc: dict, lines: list[str]) -> None:
    if as_json:
        print(json.dumps(doc, indent=2, sort_keys=True, default=str))
    else:
        print("\n".join(lines))


def fail(as_json: bool, code: int, message: str, doc: dict | None = None) -> int:
    """Report a failure on stderr (and as JSON on stdout with --json) and return its exit code."""
    print(message, file=sys.stderr)
    if as_json:
        out: dict[str, Any] = dict(doc or {})
        out.update({"ok": False, "exit": code, "error": message})
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return code
