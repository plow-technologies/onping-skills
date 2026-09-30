# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Import Inferno OnPing control parameters from a JSON file.

Mirrors the OnPing v3 web UI's import action on
`/v3/inferno/control-parameters?ljSerial=<n>`: `POST /cpInferno/import` with a
JSON array of CP objects as the body (`Content-Type: text/plain;charset=UTF-8`).

This is the INFERNO control-parameter engine (`cpInferno/*`), the same one that
`cp-list` (`cpInferno/list`) and `cp-import-json` use. It is NOT the classic CP
system (`/cp/*`, used by classic-cp-import / classic-cp-export).

`cpInferno/import` is **addOrUpdate keyed by `cpId`**: an entry whose `cpId`
matches an existing Inferno CP OVERWRITES it (name, description, inputs, outputs,
resolution, script, trigger); a new `cpId` creates one. So this is a MUTATION —
no network call happens unless `--yes` is passed; the default and `--dry-run`
only preview the affected cpIds.

`cpId` is `{ljSerial}-{uuid}`; the ljSerial prefix identifies which Lumberjack a
CP belongs to. The preview groups cpIds by ljSerial so an unintended serial is
visible before applying. Confirm the current state of a Lumberjack's CPs with
cp-list before overwriting.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

BASE_URL = "https://onping.plowtech.net"
TIMEOUT_SECONDS = 30

# Required for every entry. `cpId` is intentionally NOT required: an entry with
# no `cpId` is a CREATE — the server mints a `perEngineId`, infers the
# `engineHost`/ljSerial from the output PIDs, and enables the new CP (verified
# live 2026-07-01). An entry WITH a matching `cpId` overwrites (addOrUpdate).
# `resolution` and `description` are also optional: the web-UI import body
# carries `resolution`, but the export round-trip format omits it (server
# defaults it, observed 2048).
REQUIRED_FIELDS = ("name", "inputs", "outputs", "script", "trigger")


def _fail(msg: str) -> "None":
    print(msg, file=sys.stderr)
    sys.exit(1)


def _read_input(path: str | None) -> str:
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            _fail(f"Could not read --input {path}: {e}")
    data = sys.stdin.read()
    if not data.strip():
        _fail("No JSON provided — pass --input PATH or pipe the file on stdin.")
    return data


def _parse_and_validate(raw: str) -> list[dict]:
    """Parse the JSON body and validate it locally before any send.

    Must be a JSON array of objects, each carrying the required Inferno CP
    fields; duplicate cpIds are rejected (the round-trip keys on cpId). Any
    failure exits non-zero and imports nothing.
    """
    try:
        parsed = json.loads(raw)
    except ValueError as e:
        _fail(f"Input is not valid JSON: {e}")

    if not isinstance(parsed, list):
        _fail("Input must be a JSON array of Inferno CP objects.")
    if not parsed:
        _fail("Input array is empty — nothing to import.")

    seen: dict[str, int] = {}
    dupes: list[str] = []
    for i, cp in enumerate(parsed):
        if not isinstance(cp, dict):
            _fail(f"Entry {i} is not a JSON object.")
        missing = [key for key in REQUIRED_FIELDS if key not in cp]
        if missing:
            _fail(f"Entry {i} (cpId {cp.get('cpId', '<create>')}) missing required field(s): {missing}")
        # cpId is optional (absent => create). When present it must be well-formed
        # and unique within the file (the update round-trip keys on it).
        cp_id = cp.get("cpId")
        if cp_id is not None:
            if not isinstance(cp_id, str) or "-" not in cp_id:
                _fail(f"Entry {i} has a malformed cpId {cp_id!r} (expected '{{ljSerial}}-{{uuid}}').")
            if cp_id in seen:
                if cp_id not in dupes:
                    dupes.append(cp_id)
            seen[cp_id] = i

    if dupes:
        _fail(f"Refusing to import: duplicate cpId(s) in the file: {dupes}")

    return parsed


def _lj_serial(cp_id: str | None) -> str:
    """The ljSerial prefix of a '{ljSerial}-{uuid}' cpId.

    A missing cpId is a CREATE — the server infers the ljSerial from the output
    PIDs, so it is not known ahead of the request; group these under '<create>'.
    """
    if not cp_id:
        return "<create>"
    return cp_id.split("-", 1)[0]


def _import(token: str, body: str) -> dict:
    """POST the JSON body to /cpInferno/import; return a result record.

    Auth-expiry (redirect to /auth/login or an HTML login body) fails fast via
    _fail(); never reported as imported. A non-2xx is a failure with the raw
    body surfaced. A JSON {"error":...} on a 2xx is also a failure.
    """
    url = f"{BASE_URL}/cpInferno/import"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=body.encode("utf-8"),
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return {"imported": False, "error": f"request error: {e}"}

    # Auth-expiry fail-fast (redirect to auth or HTML login page).
    if resp.history and (
        "/auth/login" in resp.url or resp.url.rstrip("/").endswith("/auth")
    ):
        _fail(
            f"Access token redirected to auth — token may be expired "
            f"(final URL: {resp.url}). Nothing was imported."
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        _fail(
            "Expected JSON but received HTML — access token may be expired "
            "or the route returned an error page. Nothing was imported."
        )

    if not (200 <= resp.status_code < 300):
        return {
            "imported": False,
            "error": f"HTTP {resp.status_code}",
            "response": resp.text[:2000],
        }

    # 2xx. Surface the body; a JSON {"error": ...} envelope is a failure.
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        return {"imported": False, "error": str(parsed["error"])}
    return {"imported": True, "response": parsed if parsed is not None else resp.text[:2000]}


_OVERWRITE_WARNING = (
    "Import is addOrUpdate keyed by cpId: any existing Inferno CP with a matching "
    "cpId above will be OVERWRITTEN (name, description, inputs, outputs, resolution, "
    "script, trigger). An entry with NO cpId (grouped under '<create>') CREATES a "
    "new, enabled CP — the server mints the cpId and infers the Lumberjack from the "
    "output PIDs. Confirm the current state of each affected Lumberjack with cp-list "
    "before applying, and capture the prior CP definition so an overwrite can be "
    "rolled back (there is no Inferno CP undo — a created CP must be removed via "
    "cpInferno/delete)."
)


def _print_preview(cps: list[dict], input_label: str) -> None:
    print("DRY RUN — no request sent. Pass --yes to import.", file=sys.stderr)
    # Group cpIds by ljSerial so cross-Lumberjack scope is visible; entries with
    # no cpId are creates (server assigns the id) and group under '<create>'.
    by_serial: dict[str, list[dict]] = {}
    for cp in cps:
        by_serial.setdefault(_lj_serial(cp.get("cpId")), []).append(cp)

    print(f"Would create/overwrite {len(cps)} Inferno CP(s) from {input_label}:")
    for serial in sorted(by_serial):
        label = "CREATE (server-assigned cpId)" if serial == "<create>" else f"ljSerial {serial}"
        print(f"  {label}:")
        for cp in by_serial[serial]:
            print(
                f"    {cp.get('cpId', '<new>')}  name={cp['name']!r}  "
                f"trigger={cp['trigger']!r}  resolution={cp.get('resolution', '<none>')}"
            )
    print("\n" + _OVERWRITE_WARNING, file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Import Inferno OnPing control parameters from a JSON file via "
        "POST /cpInferno/import. Mutating (addOrUpdate by cpId); requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("--input", help="JSON CP-array file to import (default: stdin)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the affected cpIds; make no request (wins over --yes)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="actually import (required for any network call)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = p.parse_args()

    raw = _read_input(args.input)
    cps = _parse_and_validate(raw)
    # A missing cpId is a CREATE (server assigns the id); represent it as null.
    cp_ids = [cp.get("cpId") for cp in cps]
    input_label = args.input or "<stdin>"

    # Safety gate: no network call unless --yes; --dry-run wins over --yes.
    preview = args.dry_run or not args.yes
    if preview:
        if args.json:
            by_serial: dict[str, list[str | None]] = {}
            for cp_id in cp_ids:
                by_serial.setdefault(_lj_serial(cp_id), []).append(cp_id)
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "input": input_label,
                        "cpIds": cp_ids,
                        "byLjSerial": by_serial,
                    },
                    indent=2,
                )
            )
        else:
            _print_preview(cps, input_label)
        sys.exit(0)

    result = _import(args.access_token, raw)

    if args.json:
        print(json.dumps({"mode": "import", "cpIds": cp_ids, "result": result}, indent=2))
    else:
        if result.get("imported"):
            print(f"Imported {len(cp_ids)} Inferno CP(s) (cpIds: {cp_ids}).")
            print(json.dumps(result.get("response"), indent=2))
        else:
            print(f"Import FAILED — {result.get('error', 'unknown')}", file=sys.stderr)
            if result.get("response"):
                print(result["response"], file=sys.stderr)

    if not result.get("imported"):
        sys.exit(1)


if __name__ == "__main__":
    main()
