"""Shared postgres access for the OnPing audit-recovery skills.

Used by `onping-ctable-audit-history`, `onping-ctable-audit-export`, and
`onping-audit-recover`. Three copies of this logic would drift, so there is one.

WHY THESE SKILLS EXIST AT ALL

The audit WRITE path is generic: `auditInsert` folds over every audited model, so
every save of every model lands in `<model>_audit` as a full snapshot. The audit
READ path is an enumerated list: `auditGet` dispatches over a hand-maintained
`AuditType` case list, and 51 models derive `NoIndex` so they never reach
Elasticsearch either. For those models `POST /log/audit2/query` returns nothing
and postgres is the only recovery path. Prefer `onping-audit-pull` for the models
the API does cover.

CREDENTIALS ARE RESOLVED AT RUN TIME, NEVER STORED

`resolve_pg()` reads the postgres block from the deployed `onping-audit-server`
config over SSH and connects with what it finds. No password, username, or
database name is stored in this repository, and a password rotation needs no
change here.

TWO TOPOLOGY FACTS, BOTH LEARNED THE HARD WAY

1. **The audit host is a required argument with no default.** The wiki runbook
   this work replaced hardcoded a mongo host that is now NXDOMAIN, and an IP in a
   subnet that is not production. Baking in an address is how that document became
   wrong, so nothing here carries one.

2. **Postgres binds to the database host's own address, not localhost.** Observed
   `listen_addresses = '<db-host-ip>'`. A connection to `localhost` is refused
   *from the database host itself*, so the address must come from the config's
   `host` field. The audit server and the database are also different machines,
   and only the database host has `psql`.

TRANSFER INTEGRITY

`query_json()` base64-encodes server-side and decodes locally. This is not
belt-and-braces. `psql -tA` line-wraps long values and `COPY` tab-escapes
backslashes; both produce unparseable JSON on a 655 KB cells column, and both
were observed doing exactly that. Any transfer that cannot be re-parsed is a hard
failure rather than a silently truncated result.
"""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
import sys
from typing import Any

SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "StrictHostKeyChecking=accept-new",
]
SSH_USER = "node"
DEFAULT_TIMEOUT = 300

# Where the deployed audit-server config lives on the audit host. A list because
# the deploy manifest has moved this before; the first readable one wins.
CONFIG_CANDIDATES = (
    "~/onping-audit-server/config.yml",
    "~/onping-audit-server/onping-core.yml",
)


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _ssh(host: str, command: str, *, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run one command over SSH and return stdout, or exit non-zero."""
    argv = ["ssh", *SSH_OPTS, f"{SSH_USER}@{host}", command]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        fail(f"SSH to {host} timed out after {timeout}s.")
    except FileNotFoundError:
        fail("ssh not found on PATH.")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        tail = err[-1] if err else f"exit {proc.returncode}"
        fail(
            f"SSH to {host} failed: {tail}\n"
            "  If this is 'Network is unreachable', the VPN is most likely down. "
            "This skill does not fall back to any other address."
        )
    return proc.stdout


class PgTarget:
    """Resolved postgres connection settings. Carries no default anywhere."""

    def __init__(self, audit_host: str, host: str, port: str, user: str,
                 dbname: str, password: str) -> None:
        self.audit_host = audit_host
        self.host = host
        self.port = port
        self.user = user
        self.dbname = dbname
        self.password = password
        # The host with psql is the DATABASE host, not the audit server.
        self.exec_host = audit_host

    def describe(self) -> str:
        return (
            f"audit host {self.audit_host} -> db {self.user}@{self.host}:"
            f"{self.port}/{self.dbname}"
        )


def _parse_pg_block(text: str) -> dict[str, str]:
    """Pull host/port/user/dbname/password out of the audit-server config.

    Hand-parsed rather than YAML-loaded because the file is read over SSH as text
    and the block is a flat `key: value` list under `- onping-audit:`. Only the
    five keys we need are extracted; anything else in the file is ignored.
    """
    wanted = ("host", "port", "user", "dbname", "password")
    found: dict[str, str] = {}
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- onping-audit:"):
            in_block = True
            continue
        if in_block:
            # A new list item at the same level ends the block.
            if stripped.startswith("- ") and ":" in stripped:
                break
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                if key in wanted and key not in found:
                    found[key] = value.strip().strip("'\"")
    missing = [k for k in wanted if k not in found]
    if missing:
        fail(
            "could not read the postgres settings from the deployed config; "
            f"missing {', '.join(missing)}. Check the onping-audit block."
        )
    return found


def _resolve_consul(audit_host: str, name: str) -> str:
    """Resolve a `.service.consul` name from the audit host."""
    out = _ssh(audit_host, f"getent hosts {shlex.quote(name)} || true", timeout=60)
    for line in out.splitlines():
        parts = line.split()
        if parts:
            return parts[0]
    fail(
        f"could not resolve {name} from {audit_host}. The config names it as the "
        "database host, so nothing else can be substituted safely."
    )


def resolve_pg(audit_host: str, *, verbose: bool = True) -> PgTarget:
    """Read the deployed config over SSH and return connection settings."""
    cat = " || ".join(f"cat {p} 2>/dev/null" for p in CONFIG_CANDIDATES)
    text = _ssh(audit_host, f"({cat}) | head -200")
    if not text.strip():
        fail(
            f"no readable onping-audit-server config on {audit_host}. Tried: "
            + ", ".join(CONFIG_CANDIDATES)
        )
    pg = _parse_pg_block(text)
    host = pg["host"]
    if host.endswith(".service.consul"):
        resolved = _resolve_consul(audit_host, host)
        if verbose:
            print(f"resolved {host} -> {resolved}", file=sys.stderr)
        host = resolved
    elif host in ("localhost", "127.0.0.1"):
        # Recorded because it is a real trap: postgres binds to the host's own
        # address, so a localhost connection is refused even on the db host.
        print(
            f"warning: config names the db host as {host!r}. Postgres binds to "
            "the host's own address, so this can be refused.",
            file=sys.stderr,
        )
    target = PgTarget(audit_host, host, pg["port"], pg["user"], pg["dbname"], pg["password"])
    if verbose:
        print(target.describe(), file=sys.stderr)
    return target


def _psql(target: PgTarget, sql: str, *, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run one SQL statement on the database host via SSH. SELECT only."""
    inner = (
        f"PGPASSWORD={shlex.quote(target.password)} psql "
        f"-h {shlex.quote(target.host)} -p {shlex.quote(target.port)} "
        f"-U {shlex.quote(target.user)} -d {shlex.quote(target.dbname)} "
        f"-q -X -A -t -c {shlex.quote(sql)}"
    )
    out = _ssh(target.exec_host, inner, timeout=timeout)
    if "psql: error" in out or "ERROR:" in out:
        fail(f"postgres error:\n{out.strip()[:800]}")
    return out


def query_rows(target: PgTarget, sql: str, *, sep: str = "\x1f") -> list[list[str]]:
    """Run a SELECT and return rows split on a non-printing separator.

    The separator is ASCII unit-separator rather than `|`, because audit columns
    legitimately contain pipes and a pipe-delimited parse silently mis-splits.
    """
    wrapped = sql.replace("<SEP>", sep)
    out = _psql(target, wrapped)
    rows = []
    for line in out.splitlines():
        if line.strip():
            rows.append(line.split(sep))
    return rows


def query_json(target: PgTarget, select_expr: str, from_where: str) -> Any:
    """Run a SELECT that yields one JSON value, transferred base64-safe.

    `select_expr` must produce a single json/jsonb/text column. The value is
    base64-encoded server-side so that newlines, tabs, and backslashes inside a
    large cells column survive the SSH transfer intact. A result that does not
    re-parse is a hard failure, never a truncated return.
    """
    sql = (
        f"SELECT encode(convert_to(({select_expr})::text, 'UTF8'), 'base64') {from_where}"
    )
    out = _psql(target, sql)
    b64 = "".join(out.split())
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001 - want the reason in the message
        fail(f"could not base64-decode the transferred row: {exc}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        fail(
            f"transferred row is not re-parseable JSON: {exc}. "
            "Refusing to return a partial value."
        )


def table_exists(target: PgTarget, table: str) -> bool:
    rows = query_rows(
        target,
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' "
        f"AND table_name={_lit(table)}",
    )
    return bool(rows)


def list_audit_tables(target: PgTarget) -> list[str]:
    rows = query_rows(
        target,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name LIKE '%audit%' ORDER BY 1",
    )
    return [r[0] for r in rows if r and r[0]]


def _lit(value: str) -> str:
    """Quote a string as a postgres literal."""
    return "'" + value.replace("'", "''") + "'"


def add_common_args(parser) -> None:
    """The arguments every audit-database skill shares."""
    parser.add_argument(
        "audit_host",
        help="audit-server host to read the deployed postgres config from "
        "(required; this skill carries no default address)",
    )
    parser.add_argument(
        "--quiet-resolve",
        action="store_true",
        help="do not print the resolved connection target to stderr",
    )
