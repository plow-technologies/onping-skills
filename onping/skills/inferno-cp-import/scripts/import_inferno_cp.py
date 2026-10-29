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
import re
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
# The server's parser (`NewOrExistingControlParameterInferno2` FromJSON,
# onping-frontend-types src/OnPing/Frontend/Types/ControlParametersInferno.hs)
# reads the CP fields either at top level or nested under `cpData`, so both
# `{cpId?, inputs, ...}` and `{cpId?, cpData: {inputs, ...}}` are accepted here.
# `name` and `description` default to "".
# `trigger` is optional on a create and on an update: in the server's friendly
# format a missing (or null) trigger IS OnInputChangeAny. The friendly ToJSON omits
# that default (`toJSONFriendlyTrigger ... OnInputChangeAny = Nothing`), and
# `parseJSONFriendlyTrigger Nothing` restores it, so /cpInferno/export/json
# output round-trips with no trigger.
REQUIRED_FIELDS = ("inputs", "outputs", "script")
DEFAULT_TRIGGER_LABEL = "<default: OnInputChangeAny>"
# `cpIdOrSerial` is the key of the Dhall import format (`NewOrExistingControlParameterInferno`,
# ControlParametersInferno.hs). The JSON/YAML import parses
# `NewOrExistingControlParameterInferno2`, which reads only `cpId`
# (Handler/ControlParameters/Inferno.hs), so a JSON entry keyed by `cpIdOrSerial`
# would silently become a create.
DHALL_CP_ID_KEY = "cpIdOrSerial"
# A UUID as Data.UUID parses it (8-4-4-4-12 hex digits, either case).
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# An LJSerial (Int32) as `reads` parses it in the friendly string.
_HOST_RE = re.compile(r"-?[0-9]+")


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


ORPHANED_TAG = "OrphanedControlParameterInferno"


def _is_tagged(entry: object) -> bool:
    return isinstance(entry, dict) and "tag" in entry and "contents" in entry


def _fields(cp: dict) -> dict:
    """The CP fields of an entry: its nested `cpData` object, or the entry itself (flat)."""
    nested = cp.get("cpData")
    return nested if isinstance(nested, dict) else cp


def _friendly_cp_id(host: object, uuid: object) -> str | None:
    """Canonical '{ljSerial}-{uuid}' text, or None when either part does not parse."""
    if isinstance(host, bool):
        return None
    if isinstance(host, str) and _HOST_RE.fullmatch(host):
        host = int(host)
    if not isinstance(host, int) or not isinstance(uuid, str) or not _UUID_RE.fullmatch(uuid):
        return None
    return f"{host}-{uuid.lower()}"


def _cp_id_text(cp_id: object) -> str | None:
    """A cpId as canonical '{ljSerial}-{uuid}' text (for the preview and duplicate check).

    Same rule as the server's `parseJSONFriendlyCPID` (onping-frontend-types
    ControlParametersInferno.hs) and cp-import-json's `parse_friendly_cpid`:

    - a friendly string: split on '-', at least six parts, the last five are the UUID
      and the rest is an integer LJSerial (`reads`);
    - otherwise the generic CPID object (`Aeson.parseJSON`). CPID's FromJSON is
      the generic one with default options (control-parameters-types
      ControlParameters/Types.hs), which ignores extra keys; `engineHost` is
      an integer or a numeric string (lumberjack-identity-types Types.hs,
      js-safe `parseJSONSafe`), and `perEngineId` a UUID string.

    The UUID is lower-cased, since Data.UUID parses either case. Returns None for a
    missing cpId (a create) and for anything the server would not parse.
    """
    if isinstance(cp_id, str):
        parts = cp_id.split("-")
        if len(parts) < 6:
            return None
        return _friendly_cp_id("-".join(parts[:-5]), "-".join(parts[-5:]))
    if isinstance(cp_id, dict) and "engineHost" in cp_id and "perEngineId" in cp_id:
        return _friendly_cp_id(cp_id["engineHost"], cp_id["perEngineId"])
    return None


def _cp_list_element_message(index: int, entry: dict, entries: list) -> str:
    """Refusal text for raw /cpInferno/list elements (`{"tag", "contents"}`).

    cp-list passes the server's tagged union through unchanged
    (Readable / Orphaned / ProhibitedRead / FailedToReadPermissions, onping #16220);
    none of those wrappers is an import entry. Every entry is scanned, so every
    orphan in the file is named with its missing output PIDs.
    """
    tagged = sum(1 for e in entries if _is_tagged(e))
    orphans = []
    for i, e in enumerate(entries):
        if not (_is_tagged(e) and e.get("tag") == ORPHANED_TAG):
            continue
        contents = e.get("contents")
        missing = contents[1] if isinstance(contents, list) and len(contents) == 2 else None
        orphans.append(f"entry {i} missing output PID(s) {json.dumps(missing)}")
    detail = ""
    if orphans:
        detail = (
            f" {len(orphans)} of them are orphaned CPs whose output PIDs no longer exist, so "
            f"re-importing them as-is points at PIDs that do not exist ({'; '.join(orphans)})."
        )
    return (
        f"Entry {index} is a raw cp-list element (tag {entry.get('tag')!r}). "
        f"{tagged} of {len(entries)} entries are tagged list elements: this is cp-list output.{detail} "
        "Normalise it with cp-import-json first: `cp_import_json.py normalize` unwraps each "
        "readable CP to its {cpId, cpData} import entry, omits orphans by default and drops "
        "not-readable elements, listing them on stderr. Nothing was sent."
    )


def _parse_and_validate(raw: str) -> list[dict]:
    """Parse the JSON body and validate it locally before any send.

    Must be a JSON array of objects, each carrying the required Inferno CP
    fields, flat or nested under `cpData`; a present cpId must parse as the server
    parses it; `cpIdOrSerial` (the Dhall key) is refused; duplicate cpIds are
    rejected (the round-trip keys on cpId). Any failure exits non-zero and imports
    nothing.
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
        if _is_tagged(cp):
            _fail(_cp_list_element_message(i, cp, parsed))
        if "cpData" in cp and not isinstance(cp["cpData"], dict):
            _fail(f"Entry {i} has a cpData that is not a JSON object.")
        if DHALL_CP_ID_KEY in cp:
            _fail(
                f"Entry {i} has {DHALL_CP_ID_KEY} {cp[DHALL_CP_ID_KEY]!r}, the key of the Dhall import "
                "format. The JSON import reads only cpId and ignores cpIdOrSerial, so this entry "
                "would be imported as a new CP. Use cpId with the CPID for an update, or drop the "
                "key for a create. Nothing was sent."
            )
        fields = _fields(cp)
        label = cp.get("cpId", "<create>")
        missing = [key for key in REQUIRED_FIELDS if key not in fields]
        if missing:
            _fail(f"Entry {i} (cpId {label}) missing required field(s): {missing}")
        # cpId is optional (absent => create). When present it must be well-formed
        # and unique within the file (the update round-trip keys on it).
        raw_id = cp.get("cpId")
        if raw_id is not None:
            cp_id = _cp_id_text(raw_id)
            if cp_id is None:
                _fail(
                    f"Entry {i} has a malformed cpId {raw_id!r} (expected '{{ljSerial}}-{{uuid}}', "
                    "or an {engineHost, perEngineId} object)."
                )
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
        by_serial.setdefault(_lj_serial(_cp_id_text(cp.get("cpId"))), []).append(cp)

    print(f"Would create/overwrite {len(cps)} Inferno CP(s) from {input_label}:")
    for serial in sorted(by_serial):
        label = "CREATE (server-assigned cpId)" if serial == "<create>" else f"ljSerial {serial}"
        print(f"  {label}:")
        for cp in by_serial[serial]:
            fields = _fields(cp)
            trigger = fields.get("trigger")
            # A missing or null trigger is OnInputChangeAny, on a create and an update alike.
            trigger_text = DEFAULT_TRIGGER_LABEL if trigger is None else repr(trigger)
            print(
                f"    {_cp_id_text(cp.get('cpId')) or '<new>'}  name={fields.get('name', '')!r}  "
                f"trigger={trigger_text}  "
                f"resolution={fields.get('resolution', '<none>')}"
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
    cp_ids = [_cp_id_text(cp.get("cpId")) for cp in cps]
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
