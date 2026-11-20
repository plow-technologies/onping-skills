# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Import one Inferno script from an ExportedScript JSON file.

POSTs the file produced by inferno-script-export (GET /script/export/{hash}) to
one of three routes. Each route type-checks the script against its own prelude:

  --kind vp  ->  POST /script/vp/import  (VP/CP prelude; saved as a VirtualParameterScript)
  --kind cp  ->  POST /script/cp/import  (VP/CP prelude; saved as a ControlParameterScript)
  --kind ml  ->  POST /script/ml/import  (ML prelude; saved as an MLInferenceScript with
                                         `models` and `inputs`)

Since onping 2026.10.13 (#16217) an ML file carries `models`, `inputs` and
`outputs`, and the ML route rejects it (`inferno.import.io`) unless every named
argument is exactly one of them. ML files exported before that release have
`models` only; they are refused locally. Export them again, name the inputs
with --ml-input NAME[=r|w|rw], or, for a server older than 2026.10.13, send
them unchanged with --allow-old-ml-format.

The old /script/import route became /script/vp/import in onping 2026.10.4 and
no longer exists, so nothing falls back to it.

What the import does depends on the file's `hash`:

  * The server has that hash, and it is the latest version of its script: the
    import saves a NEW VERSION on top of it, as an edit in the editor does. The
    new version keeps the server's group, visibility and description; the file's
    `group` and `visibility` are ignored. The new version gets a new hash.
  * The server has that hash but the script has been saved since: rejected with
    a 422 `inferno.import.version` diagnostic. Export the latest and redo the edit.
  * The hash is null, absent, or unknown to this server: the import CREATES a
    new script, with the file's `group` and `visibility`.

A route can only update scripts of its own type: /script/vp/import only VP
scripts, /script/cp/import only CP scripts, /script/ml/import only ML inference
scripts. Anything else is a 422 `inferno.import.scriptType`. Mask and ML
training scripts have no import route.

This is a MUTATION. No request is sent unless --yes is passed; the default and
--dry-run only preview.

Exit codes: 0 success or preview; 1 input, HTTP, transport or auth error;
2 usage error; 3 the server rejected the script with diagnostics (422);
4 --yes refused locally because an ML file has no inputs but some outputs
(see --allow-empty-inputs). With --json, exit 4 prints a JSON object on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import NamedTuple

import requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _token_input import token_source  # noqa: E402

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net").rstrip("/")
TIMEOUT_SECONDS = 60

ROUTES = {"vp": "/script/vp/import", "cp": "/script/cp/import", "ml": "/script/ml/import"}

# `hash`, `models`, `inputs` and `outputs` are optional on import (FromJSON uses .:?).
REQUIRED_FIELDS = ("name", "args", "body", "type", "author", "group", "visibility", "timestamp")

EXIT_REJECTED = 3
# --yes refused by a local safety gate (a file with no inputs but some outputs).
EXIT_REFUSED = 4

# Diagnostic sources that call for a different next step than editing the body.
# inferno.import.scriptType and inferno.import.output depend on more than the
# source; see _hint().
SOURCE_HINTS = {
    "inferno.import.version": "export the latest version, re-apply the edit, and import that",
    "inferno.import.models": "check `models` keys against `args`, and that each model version exists",
    "inferno.import.io": "every argument must be exactly one of `inputs`, `outputs` or `models`; "
    "re-export a file from before onping 2026.10.13 with inferno-script-export, "
    "or name the inputs with --ml-input",
}

# ScriptInputType's JSON (plow-inferno Plow/Inferno/Types/Metadata.hs).
INPUT_MODES = ("r", "w", "rw")

# The release whose export format added `inputs` and `outputs` (#16217).
ML_IO_RELEASE = "onping 2026.10.13"

# The script type named in Import.hs's wrongScriptTypeDiagnostic ("This file was
# exported from a <type> script, ...") and the --kind whose route updates it.
# None means no import route updates that script type.
SCRIPT_TYPE_KINDS = (
    ("virtual parameter script", "vp"),
    ("control parameter script", "cp"),
    ("Inferno ML inference script", "ml"),
    ("Inferno ML training script", None),
    ("mask script", None),
    ("script with no script type", None),
)

# validateScriptOutput (VP/CP) and the ML route's output check.
OUTPUT_HINTS = {
    "vp": "the result cannot be a function, array, tuple, `rep`, open record, or nested record",
    "cp": "the result cannot be a function, array, tuple, `rep`, open record, or nested record",
    "ml": "ML inference scripts must return `array of write`",
}


def _fail(msg: str) -> None:
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
        _fail("No JSON provided -- pass --input PATH or pipe the file on stdin.")
    return data


def ml_input_spec(value: str) -> tuple[str, str]:
    """argparse type= for one --ml-input NAME[=r|w|rw] (mode `r` by default); bad values exit 2."""
    name, sep, mode = value.partition("=")
    name = name.strip()
    mode = mode.strip() if sep else "r"
    if not name:
        raise argparse.ArgumentTypeError(f"{value!r}: the argument name is blank")
    if mode not in INPUT_MODES:
        raise argparse.ArgumentTypeError(f"{value!r}: mode {mode!r} is not one of r, w, rw")
    return name, mode


def merge_ml_inputs(specs: list[tuple[str, str]]) -> dict[str, str]:
    """Combine parsed --ml-input values; ValueError if a name is given twice with different modes."""
    inputs: dict[str, str] = {}
    for name, mode in specs:
        if name in inputs and inputs[name] != mode:
            raise ValueError(f"--ml-input names {name} twice, with modes {inputs[name]!r} and {mode!r}")
        inputs[name] = mode
    return inputs


def _io_problems(args: list, inputs: dict, outputs: list, models: dict) -> list[str]:
    """checkInputOutputArguments (the server's import check), same wording."""
    arg_names = [a for a in args if a]  # [name | Just (Ident name) <- args]
    problems = [
        f"{name} is not an argument of the script."
        for name in [*inputs, *outputs]
        if name not in arg_names
    ]
    for name in arg_names:
        roles = [
            role
            for role, present in (
                ("an input", name in inputs),
                ("an output", name in outputs),
                ("a model", name in models),
            )
            if present
        ]
        if not roles:
            problems.append(f"The argument {name} is not listed as an input, an output or a model.")
        elif len(roles) > 1:
            problems.append(f"The argument {name} is listed as {' and '.join(roles)}.")
    return problems


def is_mangled(script: dict) -> bool:
    """No inputs but some outputs: the re-export of a script imported before onping 2026.10.13.

    The same rule as inferno-script-export's is_mangled. An absent or null
    `inputs` counts as `{}`, because the server's FromJSON reads it with .:? and
    then mempty.
    """
    inputs = script.get("inputs")
    outputs = script.get("outputs")
    return (inputs is None or inputs == {}) and isinstance(outputs, list) and len(outputs) > 0


class Checked(NamedTuple):
    """parse_and_validate's result."""

    script: dict
    # The file's own inputs/outputs, exactly as they were in the file (they may
    # be malformed), when --ml-input replaced a different split; else None.
    replaced: dict | None = None
    # True when an old-format ML file is sent unchanged (--allow-old-ml-format).
    old_format: bool = False


def _ml_shape_problems(script: dict, keys: tuple[str, ...]) -> list[str]:
    """Shapes the server's FromJSON would fail to parse (HTTP 400).

    It parses `models`, `inputs` and `outputs` with .:? on every route, so null
    or absent is fine, and an empty value of the right shape decodes to mempty.
    """
    expected = {
        "models": "an object mapping argument names to model version UUIDs",
        "inputs": 'an object mapping argument names to "r", "w" or "rw"',
        "outputs": "a list of argument names",
    }
    problems = []
    for key in keys:
        value = script.get(key)
        if value is None:
            continue
        if key == "outputs":
            ok = isinstance(value, list) and all(isinstance(o, str) for o in value)
        else:
            ok = isinstance(value, dict)
        if not ok:
            problems.append(f"`{key}` must be {expected[key]}, not {json.dumps(value)}")
    return problems


def parse_and_validate(
    raw: str,
    kind: str,
    ml_inputs: dict[str, str] | None = None,
    allow_old_format: bool = False,
) -> Checked:
    """Parse the ExportedScript and check it locally before any send.

    With `ml_inputs` (--ml-input, --kind ml only), `inputs` and `outputs` are
    rewritten: the named arguments become inputs, and every other named
    non-model argument becomes an output.

    With `allow_old_format` (--allow-old-ml-format), an ML file with neither
    `inputs` nor `outputs` is sent unchanged, for a server older than
    onping 2026.10.13.

    Any failure exits non-zero and imports nothing.
    """
    try:
        script = json.loads(raw)
    except ValueError as e:
        _fail(f"Input is not valid JSON: {e}")

    if isinstance(script, list):
        count = len(script)
        _fail(
            f"Only one script can be imported at a time, but this file is a list of {count} "
            f"script{'' if count == 1 else 's'}. Export a single script with inferno-script-export."
        )
    if not isinstance(script, dict):
        _fail("Input must be one ExportedScript JSON object.")

    missing = [key for key in REQUIRED_FIELDS if key not in script]
    if missing:
        _fail(f"Input is missing ExportedScript field(s): {missing}")
    if not isinstance(script["name"], str) or not script["name"].strip():
        _fail("The name field cannot be blank.")
    if not isinstance(script["body"], str):
        _fail("The body field must be a string.")
    if not isinstance(script["args"], list) or not all(a is None or isinstance(a, str) for a in script["args"]):
        _fail("The args field must be a list of argument names (or null for an unnamed argument).")
    script_hash = script.get("hash")
    if script_hash is not None and not isinstance(script_hash, str):
        _fail(f"The hash field must be a string or null, not {script_hash!r}.")

    if kind in ("vp", "cp"):
        # Every route parses the three keys, so a bad shape is a 400 even here.
        shape = _ml_shape_problems(script, ("models", "inputs", "outputs"))
        if shape:
            _fail(
                "The server would refuse the file (HTTP 400): " + "; ".join(shape) + ". Remove the "
                f"key{'s' if len(shape) > 1 else ''}, because the {kind.upper()} route does not use "
                "them."
            )
        # An empty value of the right shape decodes to mempty, and importPlowScript
        # never reads exportedScriptML, so it is sent as is.
        ml_keys = [key for key in ("models", "inputs", "outputs") if script.get(key)]
        if ml_keys:
            named = " and ".join(f"`{key}`" for key in ml_keys)
            _fail(
                f"This file has {named}, which only ML inference scripts use. The {kind.upper()} route "
                f"would drop them silently. Use --kind ml, or remove {named}."
            )
        return Checked(script)

    # kind == "ml"
    shape = _ml_shape_problems(script, ("models",))
    if shape:
        _fail("The server would refuse the file (HTTP 400): " + "; ".join(shape) + ".")
    models = script.get("models") or {}
    arg_names = {a for a in script["args"] if a}
    problems = [f"{name} is not an argument of the script" for name in models if name not in arg_names]
    for name, version in models.items():
        try:
            uuid.UUID(str(version))
        except ValueError:
            problems.append(f"model version {version!r} for {name} is not a UUID")
    if problems:
        _fail("Invalid models: " + "; ".join(problems) + ".")

    replaced = None
    if ml_inputs:
        old_inputs, old_outputs = script.get("inputs"), script.get("outputs")
        new_inputs = dict(ml_inputs)
        # The server's export rule, duplicates and all: every named
        # argument that is neither an input nor a model. A name that is not an
        # argument, or is a model, is reported by _io_problems below.
        new_outputs = [a for a in script["args"] if a and a not in ml_inputs and a not in models]
        file_had_split = old_inputs not in (None, {}) or old_outputs not in (None, [])
        if file_had_split and (old_inputs, old_outputs) != (new_inputs, new_outputs):
            replaced = {"inputs": old_inputs, "outputs": old_outputs}
        script["inputs"], script["outputs"] = new_inputs, new_outputs
    elif script.get("inputs") is None and script.get("outputs") is None:
        # FromJSON reads both with .:?, so an absent key and null are the same,
        # and the server then checks the file with empty inputs and outputs. It
        # only fails if some named argument is not a model.
        unlisted = [a for a in script["args"] if a and a not in models]
        if unlisted and allow_old_format:
            return Checked(script, old_format=True)
        override = (
            f"For a server older than {ML_IO_RELEASE}, pass --allow-old-ml-format to send the file "
            "unchanged."
        )
        if unlisted and not models:
            _fail(
                "This file has no `models`, `inputs` or `outputs`, so it may not be an ML inference "
                "script: VP and CP exports have none of them (or only `\"models\": {}` before "
                f"{ML_IO_RELEASE}). If it is a VP or CP script, retry with --kind vp or --kind cp. If "
                f"it is an ML script exported before {ML_IO_RELEASE}, export it again with "
                "inferno-script-export, or name the inputs with --ml-input NAME[=r|w|rw]. "
                f"{override} Nothing was sent."
            )
        if unlisted:
            _fail(
                f"This ML file has no `inputs` or `outputs`, the format from before {ML_IO_RELEASE}. "
                f"{ML_IO_RELEASE} and later reject it (inferno.import.io) unless every argument is "
                "exactly one of `inputs`, `outputs` or `models`. Export it again with "
                "inferno-script-export, or name the inputs with --ml-input NAME[=r|w|rw] (every other "
                f"non-model argument becomes an output). {override} Nothing was sent."
            )

    inputs = script.get("inputs")
    outputs = script.get("outputs")
    inputs = {} if inputs is None else inputs
    outputs = [] if outputs is None else outputs
    if not isinstance(inputs, dict):
        _fail('The inputs field must be an object mapping argument names to "r", "w" or "rw".')
    bad_modes = [f"{name}: {mode!r}" for name, mode in inputs.items() if mode not in INPUT_MODES]
    if bad_modes:
        _fail(
            'Invalid input mode(s), expected "r", "w" or "rw": ' + "; ".join(bad_modes)
            + ". The server would refuse the file (HTTP 400)."
        )
    if not isinstance(outputs, list) or not all(isinstance(o, str) for o in outputs):
        _fail("The outputs field must be a list of argument names.")
    io_problems = _io_problems(script["args"], inputs, outputs, models)
    if io_problems:
        source = " set by --ml-input" if ml_inputs else ""
        _fail(
            f"Invalid inputs/outputs{source} (the server would reject them with inferno.import.io):\n"
            + "\n".join(f"  - {p}" for p in io_problems)
        )
    return Checked(script, replaced)


def _plan(script: dict) -> str:
    script_hash = script.get("hash")
    if script_hash:
        return (
            f"UPDATE if this server has {script_hash} and it is the latest version (a new version; "
            "keeps the server's group, visibility and description), otherwise CREATE a new script "
            f"in group {json.dumps(script['group'])}, visibility {json.dumps(script['visibility'])}"
        )
    return (
        f"CREATE a new script in group {json.dumps(script['group'])}, "
        f"visibility {json.dumps(script['visibility'])}"
    )


def _mangled_warning(script: dict, allow_empty_inputs: bool = False) -> str:
    shown = "`inputs: {}`" if script.get("inputs") == {} else "no `inputs`"
    warning = (
        f"This ML file has {shown} and {len(script['outputs'])} output(s): the script was likely "
        f"imported before {ML_IO_RELEASE}, which saved no inputs, so its export lists every "
        "non-model argument as an output. "
    )
    if allow_empty_inputs:
        return warning + (
            "--allow-empty-inputs is set, so --yes will send it with no inputs. Name the inputs "
            "with --ml-input NAME[=r|w|rw] instead if the script has any."
        )
    return warning + (
        "Name the inputs with --ml-input NAME[=r|w|rw], or pass --allow-empty-inputs if the "
        "script really has no inputs."
    )


def _inputs_text(inputs) -> str:
    """`name (mode), ...`, "none", or raw JSON when `inputs` is not an object of strings."""
    if inputs is None:
        return "none"
    if not isinstance(inputs, dict) or not all(isinstance(m, str) for m in inputs.values()):
        return f"{json.dumps(inputs)} (malformed)"
    return ", ".join(f"{name} ({mode})" for name, mode in inputs.items()) or "none"


def _outputs_text(outputs) -> str:
    """`a, b`, "none", or raw JSON when `outputs` is not a list of strings (never split a string)."""
    if outputs is None:
        return "none"
    if not isinstance(outputs, list) or not all(isinstance(o, str) for o in outputs):
        return f"{json.dumps(outputs)} (malformed)"
    return ", ".join(outputs) or "none"


def _old_format_warning() -> str:
    return (
        f"--allow-old-ml-format: this ML file has no `inputs` or `outputs` and is sent unchanged. "
        f"{ML_IO_RELEASE} and later reject it (inferno.import.io); use this only for an older server."
    )


def _no_effect_notices(checked: "Checked", kind: str, ml_inputs, allow_empty: bool, allow_old: bool) -> list[str]:
    if kind != "ml":
        return []
    notices = []
    if allow_empty and (ml_inputs or not is_mangled(checked.script)):
        why = "--ml-input sets the inputs" if ml_inputs else "the file is not missing its inputs"
        notices.append(f"NOTICE: --allow-empty-inputs has no effect: {why}.")
    if allow_old and not checked.old_format:
        why = "--ml-input sets the inputs and outputs" if ml_inputs else "the file is not in the old format"
        notices.append(f"NOTICE: --allow-old-ml-format has no effect: {why}.")
    return notices


def preview(
    checked: Checked,
    kind: str,
    input_label: str,
    rewritten: bool = False,
    allow_empty_inputs: bool = False,
) -> dict:
    script, replaced = checked.script, checked.replaced
    info = {
        "mode": "dry-run",
        "input": input_label,
        "kind": kind,
        "route": ROUTES[kind],
        "hash": script.get("hash"),
        "name": script["name"],
        "args": script["args"],
        "type": script["type"],
        "models": script.get("models") or {},
    }
    if kind == "ml":
        info["inputs"] = script.get("inputs") or {}
        info["outputs"] = script.get("outputs") or []
        info["inputsFrom"] = "--ml-input" if rewritten else "file"
        # The file's own split, as it was in the file, when --ml-input replaced a
        # different one; else null.
        info["replaced"] = replaced
        info["oldFormat"] = checked.old_format
        warnings = [_mangled_warning(script, allow_empty_inputs)] if is_mangled(script) else []
        if checked.old_format:
            warnings.append(_old_format_warning())
        if replaced:
            warnings.append(
                "--ml-input replaces the file's own inputs and outputs (shown as `file inputs` and "
                "`file outputs`); the posted body uses the --ml-input split."
            )
        info["warnings"] = warnings
    info["plan"] = _plan(script)
    return info


def _print_preview(info: dict) -> None:
    print("DRY RUN -- no request sent. Pass --yes to import.", file=sys.stderr)
    print(f"Would POST {info['input']} to {info['route']} (--kind {info['kind']}):")
    print(f"  name:   {info['name']!r}")
    print(f"  args:   {info['args']}")
    print(f"  type:   {info['type']}")
    if info["models"] or info["kind"] == "ml":
        print(f"  models: {info['models']}")
    if info["kind"] == "ml":
        source = " (set by --ml-input)" if info["inputsFrom"] == "--ml-input" else ""
        print(f"  inputs: {_inputs_text(info['inputs'])}{source}")
        print(f"  outputs: {_outputs_text(info['outputs'])}{source}")
        if info.get("replaced"):
            print(f"  file inputs (replaced): {_inputs_text(info['replaced']['inputs'])}")
            print(f"  file outputs (replaced): {_outputs_text(info['replaced']['outputs'])}")
    print(f"  plan:   {info['plan']}")
    for w in info.get("warnings") or []:
        print(f"WARNING: {w}", file=sys.stderr)
    print(
        "\nAn import cannot be undone. An update adds a version that becomes the script's latest; "
        "a create adds a new script. Parameters that use the old hash are not repointed -- "
        "update them yourself (for ML parameters, ml-parameter-update).",
        file=sys.stderr,
    )


def _position(pos: dict) -> str:
    # The server sends 0-based LSP positions; editors show 1-based ones.
    line, char = pos.get("line"), pos.get("character")
    if not isinstance(line, int) or not isinstance(char, int):
        return "?:?"
    return f"{line + 1}:{char + 1}"


def _script_type_hint(message: str) -> str:
    for script_type, target in SCRIPT_TYPE_KINDS:
        if script_type in message:
            article = "an" if script_type[0] in "AEIOUaeiou" else "a"
            if target is None:
                return f"no import route updates {article} {script_type}; edit it in the OnPing editor"
            return f"this is {article} {script_type}; retry with --kind {target}"
    return "this script belongs to another route; retry with the --kind for its script type"


def _hint(source: str, message: str, kind: str) -> str | None:
    if source == "inferno.import.scriptType":
        return _script_type_hint(message)
    if source == "inferno.import.output":
        return OUTPUT_HINTS[kind]
    return SOURCE_HINTS.get(source)


def _format_diagnostic(d: dict, kind: str) -> str:
    rng = d.get("range") or {}
    start = rng.get("start") or {}
    end = rng.get("end") or {}
    source = d.get("source", "?")
    # inferno.import.* diagnostics are about the whole file and carry a 0:0-0:0 range.
    if source.startswith("inferno.import.") and not any(
        (p.get("line"), p.get("character")) != (0, 0) for p in (start, end)
    ):
        where = "file"
    else:
        where = f"{_position(start)}-{_position(end)}"
    message = d.get("message", "")
    line = f"  {where} {d.get('severity', '?')} {source}: {message}"
    hint = _hint(source, message, kind)
    if hint:
        line += f"\n    -> {hint}"
    return line


def import_script(token: str, kind: str, script: dict) -> dict:
    """POST the script and classify the response.

    Returns {"status": "created"|"updated"|"rejected"|"error", ...}. An auth
    redirect or an HTML body exits through _fail().
    """
    url = f"{BASE_URL}{ROUTES[kind]}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(script).encode("utf-8"),
            allow_redirects=False,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return {"status": "error", "error": f"request error: {e}"}

    if 300 <= resp.status_code < 400:
        _fail(
            f"HTTP {resp.status_code} redirect to {resp.headers.get('Location', '<unknown>')} -- "
            "the access token may be expired. Nothing was imported."
        )
    if resp.text.lstrip()[:5].lower() in ("<!doc", "<html"):
        hint = " (is the route deployed on this server?)" if resp.status_code == 404 else ""
        _fail(f"HTTP {resp.status_code}: expected JSON but received HTML{hint}. Nothing was imported.")

    try:
        body = resp.json()
    except ValueError:
        return {"status": "error", "error": f"HTTP {resp.status_code}", "response": resp.text[:2000]}

    if isinstance(body, dict) and "error" in body:
        hint = ""
        if resp.status_code == 401:
            hint = " -- the access token is expired or invalid; run onping-login again"
        elif resp.status_code == 404 and body["error"] == "NotFound":
            # Live 2026-10-11: an authenticated request to a missing route gets JSON, not HTML.
            hint = f" -- this server has no {ROUTES[kind]} route (it needs onping 2026.10.4 or later)"
        return {"status": "error", "error": f"HTTP {resp.status_code}: {body['error']}{hint}"}
    if isinstance(body, dict) and "typed-error" in body:
        typed = body["typed-error"] or {}
        return {
            "status": "rejected",
            "httpStatus": resp.status_code,
            "diagnostics": typed.get("diagnostics", []) if isinstance(typed, dict) else [],
        }
    if not (200 <= resp.status_code < 300) or not isinstance(body, dict) or "hash" not in body:
        return {"status": "error", "error": f"HTTP {resp.status_code}", "response": body}
    return {
        "status": "updated" if body.get("updatedFrom") else "created",
        "result": body,
    }


def _print_result(outcome: dict, kind: str) -> None:
    status = outcome["status"]
    if status in ("created", "updated"):
        r = outcome["result"]
        if status == "created":
            print(f"CREATED {r['name']!r}: {r['hash']}")
        else:
            print(f"UPDATED {r['name']!r}: {r['updatedFrom']} -> {r['hash']}")
        print(f"  type:   {r.get('type')}")
        print(f"  inputs: {r.get('inputs')}")
        for w in r.get("warnings") or []:
            print(_format_diagnostic(w, kind))
    elif status == "rejected":
        diagnostics = outcome["diagnostics"]
        print(
            f"REJECTED (HTTP {outcome['httpStatus']}) with {len(diagnostics)} diagnostic(s). "
            "Nothing was imported. Positions are 1-based line:column in the script body "
            "(--json keeps the server's 0-based ones).",
            file=sys.stderr,
        )
        for d in diagnostics:
            print(_format_diagnostic(d, kind), file=sys.stderr)
    else:
        print(f"Import FAILED -- {outcome.get('error', 'unknown')}", file=sys.stderr)
        if outcome.get("response") is not None:
            print(json.dumps(outcome["response"]) if not isinstance(outcome["response"], str) else outcome["response"], file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Import one Inferno script from an ExportedScript JSON file via POST "
        "/script/vp/import (--kind vp), /script/cp/import (--kind cp) or /script/ml/import "
        "(--kind ml). Mutating; requires --yes.",
    )
    p.add_argument(
        "--kind",
        required=True,
        choices=sorted(ROUTES),
        help="vp: virtual parameter script (/script/vp/import); cp: control parameter script "
        "(/script/cp/import); ml: ML inference script (/script/ml/import)",
    )
    p.add_argument("--input", help="ExportedScript JSON file (default: stdin)")
    p.add_argument(
        "--ml-input",
        action="append",
        default=[],
        type=ml_input_spec,
        metavar="NAME[=r|w|rw]",
        help="--kind ml only, repeatable: make NAME an input (mode r by default) and every other "
        "non-model argument an output, replacing the file's inputs and outputs. For a file "
        "exported before onping 2026.10.13, or one whose inputs were lost by an older import",
    )
    p.add_argument(
        "--allow-empty-inputs",
        action="store_true",
        help="--kind ml only: send a file with no inputs (`{}`, null or absent) and non-empty "
        "`outputs` with --yes",
    )
    p.add_argument(
        "--allow-old-ml-format",
        action="store_true",
        help="--kind ml only: send an ML file with neither `inputs` nor `outputs` unchanged, for a "
        "server older than onping 2026.10.13 (2026.10.13 and later reject it)",
    )
    p.add_argument(
        "--as-new",
        action="store_true",
        help="send hash: null so the import creates a new script instead of updating",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the import; make no request (wins over --yes)",
    )
    p.add_argument("--yes", action="store_true", help="actually import (required for any network call)")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = token_source.parse(p, None, stdin_busy=lambda a: not a.input)
    if args.kind != "ml":
        if args.ml_input:
            p.error(f"--ml-input is for --kind ml only; the {args.kind.upper()} route has no inputs or outputs")
        if args.allow_empty_inputs:
            p.error("--allow-empty-inputs is for --kind ml only")
        if args.allow_old_ml_format:
            p.error("--allow-old-ml-format is for --kind ml only")

    try:
        ml_inputs = merge_ml_inputs(args.ml_input) if args.ml_input else None
    except ValueError as e:
        p.error(str(e))
    checked = parse_and_validate(
        _read_input(args.input), args.kind, ml_inputs, allow_old_format=args.allow_old_ml_format
    )
    script = checked.script
    if args.as_new:
        script["hash"] = None
    input_label = args.input or "<stdin>"
    for notice in _no_effect_notices(
        checked, args.kind, ml_inputs, args.allow_empty_inputs, args.allow_old_ml_format
    ):
        print(notice, file=sys.stderr)

    def _preview() -> dict:
        return preview(
            checked,
            args.kind,
            input_label,
            rewritten=ml_inputs is not None,
            allow_empty_inputs=args.allow_empty_inputs,
        )

    # Safety gate: no network call unless --yes; --dry-run wins over --yes.
    if args.dry_run or not args.yes:
        info = _preview()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            _print_preview(info)
        sys.exit(0)

    if args.kind == "ml" and is_mangled(script) and not args.allow_empty_inputs:
        message = f"{_mangled_warning(script)} Nothing was sent."
        if args.json:
            # The dry-run preview's shape, with mode/status "refused" and the reason.
            info = _preview()
            info.update(mode="refused", status="refused", error=message, exitCode=EXIT_REFUSED)
            print(json.dumps(info, indent=2))
        else:
            print(message, file=sys.stderr)
        sys.exit(EXIT_REFUSED)

    outcome = import_script(args.access_token, args.kind, script)
    if args.json:
        print(json.dumps({"mode": "import", "kind": args.kind, "route": ROUTES[args.kind], **outcome}, indent=2))
    else:
        _print_result(outcome, args.kind)

    if outcome["status"] == "rejected":
        sys.exit(EXIT_REJECTED)
    if outcome["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
