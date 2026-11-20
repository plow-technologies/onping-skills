# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Export one Inferno script as importable JSON via GET /script/export/{hash}.

Read-only. The response is a single ExportedScript object -- `hash`, `name`,
`args`, `body`, `type`, `author`, `group`, `visibility`, `timestamp`, and for an
ML inference script `models`, `inputs` and `outputs` (onping 2026.10.13, #16217;
VP and CP exports have none of the three) -- which is exactly what
POST /script/{vp,cp,ml}/import accept, so the file can be edited and
re-imported with inferno-script-import as is.

The single-script route returns a bare object; the older POST /scripts/export
returns a list, which the import routes reject.

Failures, as seen live on 2026-10-01:

  * A hash this server has never stored (or whose script was deleted): HTTP 500
    whose error text contains `CouldNotFindPath`.
  * A JSON 404 `{"error": "Script not found"}`: the user can neither edit the
    script nor see it as public, or its body cannot be pretty-printed. The two
    cases cannot be told apart from the response.
  * An HTML 404: the route itself is missing (not deployed on this server).
  * HTTP 401 `{"error": "NotAuthenticated"}`: the bearer token is expired or invalid.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _token_input import shapes, token_source  # noqa: E402

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net").rstrip("/")
TIMEOUT_SECONDS = 30

# A VCObjectHash is URL-safe base64 of a 32-byte digest: 43 characters plus "=".
HASH_RE = re.compile(r"^[A-Za-z0-9_-]{43}=$")

REQUIRED_FIELDS = ("name", "args", "body", "type", "author", "group", "visibility", "timestamp")


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _is_html(text: str) -> bool:
    return text.lstrip()[:5].lower() in ("<!doc", "<html")


def export_script(token: str, script_hash: str) -> dict:
    """GET /script/export/{hash} and return the ExportedScript object.

    Every failure exits non-zero through _fail().
    """
    url = f"{BASE_URL}/script/export/{quote(script_hash, safe='')}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, allow_redirects=False, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        _fail(f"Request to {url} failed: {e}")

    if 300 <= resp.status_code < 400:
        _fail(
            f"HTTP {resp.status_code} redirect to {resp.headers.get('Location', '<unknown>')} -- "
            "the access token may be expired. Run onping-login again."
        )
    if resp.status_code == 401:
        _fail("HTTP 401 -- the access token is expired or invalid. Run onping-login again.")
    if resp.status_code == 500 and "CouldNotFindPath" in resp.text:
        _fail(
            f"No script with hash {script_hash} on {BASE_URL}: it was never saved on this "
            "server, or it has been deleted."
        )
    if resp.status_code == 404:
        if _is_html(resp.text):
            _fail(
                f"HTTP 404 with an HTML page from {url} -- this OnPing server does not have "
                "the /script/export/{hash} route (not deployed yet?)."
            )
        _fail(
            f"Script {script_hash} not found: it does not exist, the user cannot view it, "
            "or its body cannot be printed. The server does not say which."
        )
    if _is_html(resp.text):
        _fail("Expected JSON but received HTML -- the access token may be expired.")
    if not (200 <= resp.status_code < 300):
        _fail(f"HTTP {resp.status_code} from {url}: {resp.text[:2000]}")

    try:
        script = resp.json()
    except ValueError:
        _fail(f"Response is not JSON: {resp.text[:500]}")
    if not isinstance(script, dict):
        _fail(f"Expected one ExportedScript object, got {type(script).__name__}.")
    if "error" in script:
        _fail(f"OnPing error: {script['error']}")
    missing = [key for key in REQUIRED_FIELDS if key not in script]
    if missing:
        _fail(f"Response is missing ExportedScript field(s) {missing}; got keys {sorted(script)}.")
    if script.get("hash") != script_hash:
        _fail(f"Response hash {script.get('hash')!r} does not match the requested {script_hash!r}.")
    return script


def _has_ml_io(script: dict) -> bool:
    """Since onping 2026.10.13 (#16217) only ML inference exports carry `inputs` and `outputs`."""
    return "inputs" in script or "outputs" in script


def _summary(script: dict) -> str:
    models = script.get("models") or {}
    summary = (
        f"Exported {script['name']!r} ({script['hash']}): type {' '.join(str(script['type']).split())}, "
        f"{len(script['args'])} arg(s), {len(models)} model(s)"
    )
    if _has_ml_io(script):
        summary += (
            f", {len(script.get('inputs') or {})} input(s), {len(script.get('outputs') or [])} output(s)"
        )
    return summary


def is_mangled(script: dict) -> bool:
    """No inputs but some outputs: the export of a script imported before onping 2026.10.13.

    The same rule as inferno-script-import's is_mangled. An absent or null
    `inputs` counts as `{}`, because the server's FromJSON reads it with .:? and
    then mempty.
    """
    inputs = script.get("inputs")
    outputs = script.get("outputs")
    return (inputs is None or inputs == {}) and isinstance(outputs, list) and len(outputs) > 0


def mangled_warning(script: dict) -> str | None:
    """The stderr warning for is_mangled()."""
    if is_mangled(script):
        return (
            f"WARNING: {script['name']!r} has no inputs and {len(script['outputs'])} output(s). "
            "The script was likely imported before onping 2026.10.13, which saved no inputs, so "
            "every non-model argument is exported as an output. Before re-importing, name the "
            "inputs with inferno-script-import --ml-input NAME[=r|w|rw], or edit `inputs` and "
            "`outputs` in the file."
        )
    return None


def _argv_with_dash_hashes_last(argv: list[str]) -> list[str]:
    """Move hashes that start with '-' behind '--' so argparse reads them as positionals.

    URL-safe base64 uses '-', so about 1 hash in 64 starts with it.
    """
    if "--" in argv:
        return argv
    dashed = [a for a in argv if a.startswith("-") and HASH_RE.match(a)]
    if not dashed:
        return argv
    return [a for a in argv if a not in dashed] + ["--", *dashed]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export one Inferno script as importable JSON via GET /script/export/{hash}. "
        "Read-only.",
    )
    p.add_argument(
        "script_hash",
        type=shapes.script_hash_arg,
        help="script version hash (43 URL-safe base64 characters and '=')",
    )
    p.add_argument("--output", help="write the JSON to this file (default: stdout)")
    p.add_argument("--force", action="store_true", help="overwrite an existing --output file")
    p.add_argument(
        "--json",
        action="store_true",
        help="print a JSON status object instead of the text summary (with --output only)",
    )
    args = token_source.parse(p, _argv_with_dash_hashes_last(sys.argv[1:]), is_id=shapes.is_script_hash)

    if not HASH_RE.match(args.script_hash):
        _fail(
            f"{args.script_hash!r} is not a script hash: expected 43 URL-safe base64 "
            "characters followed by '='."
        )
    if args.output and os.path.exists(args.output) and not args.force:
        _fail(f"{args.output} already exists; pass --force to overwrite it.")

    script = export_script(args.access_token, args.script_hash)
    text = json.dumps(script, indent=2, ensure_ascii=False) + "\n"
    warning = mangled_warning(script)

    if not args.output:
        sys.stdout.write(text)
        print(_summary(script), file=sys.stderr)
        if warning:
            print(warning, file=sys.stderr)
        return

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)
    if warning:
        print(warning, file=sys.stderr)
    if args.json:
        status = {
            "mode": "export",
            "output": args.output,
            "hash": script["hash"],
            "name": script["name"],
            "type": script["type"],
            "models": script.get("models") or {},
        }
        for key in ("inputs", "outputs"):
            if key in script:
                status[key] = script[key]
        print(json.dumps(status, indent=2))
    else:
        print(f"{_summary(script)} -> {args.output}")


if __name__ == "__main__":
    main()
