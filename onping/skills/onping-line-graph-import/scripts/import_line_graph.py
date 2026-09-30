# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "pyyaml"]
# ///
"""Import a full OnPing line-graph widget from a Dhall / JSON / YAML file.

Wraps `POST /content/widgets/line-graph/import/{id}` with a `text/plain` Dhall
body. Accepts three input formats:

  - `.dhall`         — passthrough (byte-preserving, round-trip friendly)
  - `.json` / `.yaml` — friendly compact spec; compiled to Dhall by expanding
                       the DisplayNameConfig union boilerplate per parameter

MUTATING: `--yes`-gated. Default is a local `--dry-run` — parses input, checks
top-level record shape, extracts the pid list (which the server will
permission-check), and reports what would be written. No network call is made
on dry-run because there is no `/parse` endpoint on line-graph widgets (unlike
`/hmi/parse`).

`--new` runs a two-step: `POST /config` to mint a fresh id, then `POST /import/#new-id`
to populate. If the import fails after the mint, the orphaned widget is left
behind and its id is printed (there is no delete route to clean it up).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _line_graph_routes.line_graph_http import (
    _fail,
    extract_error,
    post_dhall,
    post_empty,
)
from _line_graph_routes.routes import ROUTES


# ─── DisplayNameConfig Dhall union type (used verbatim by every parameter) ───

DNC_TYPE = """< DisplayByText : Text
        | DisplayByParameter :
            < DisplayParameterPID : { _1 : Natural, _2 : List Text }
            | DisplayParameterVPID :
                { _1 : Natural
                , _2 : < VPIDName | InputMetadata : List Text >
                }
            >
        | DisplayByOtherParameter :
            < DisplayParameterPID : { _1 : Natural, _2 : List Text }
            | DisplayParameterVPID :
                { _1 : Natural
                , _2 : < VPIDName | InputMetadata : List Text >
                }
            >
        >"""

DNP_TYPE = """< DisplayParameterPID : { _1 : Natural, _2 : List Text }
            | DisplayParameterVPID :
                { _1 : Natural
                , _2 : < VPIDName | InputMetadata : List Text >
                }
            >"""

EVENT_PARAM_ELEM_TYPE = f"""{{ pid : Optional {{ type : Text, value : Integer }}
           , name : Text
           , display_name_config : {DNC_TYPE.replace(chr(10), chr(10) + '  ')}
           , should_display : Bool
           , icon : Text
           , color : Text
           , hidden : Bool
           }}"""


# ─────────────────────────── input reading + sniff ──────────────────────────


def _read_input(path: str | None, fmt_hint: str | None) -> tuple[str, str]:
    """Read the input file (or stdin) and return (text, format).

    Format is one of "dhall", "json", "yaml", determined by:
      1. Explicit --input-format flag if given.
      2. File extension: .dhall/.dh -> dhall; .json -> json; .yaml/.yml -> yaml.
      3. First-non-whitespace-char peek: `{` or `[` -> json (JSON is a subset
         we allow, but a `{` might also be a Dhall record — we disambiguate on
         the next character: `{ ` (Dhall) vs `{"` (JSON). YAML has no clean
         sniff; require --input-format for stdin YAML.
    """
    if path:
        text = Path(path).read_text()
        if fmt_hint:
            return text, fmt_hint
        ext = Path(path).suffix.lower()
        if ext in (".dhall", ".dh"):
            return text, "dhall"
        if ext == ".json":
            return text, "json"
        if ext in (".yaml", ".yml"):
            return text, "yaml"
    else:
        text = sys.stdin.read()
        if fmt_hint:
            return text, fmt_hint

    # Fallback: sniff by first two non-whitespace characters.
    stripped = text.lstrip()
    if stripped.startswith("["):
        # A Dhall [Field] list is the wrong-shape case; still call it dhall and
        # let the shape check reject it with a clear message.
        return text, "dhall"
    if stripped.startswith("{"):
        # Distinguish Dhall record `{ key = ...` from JSON `{"key": ...`.
        if stripped[:2] in ('{"', "{'"):
            return text, "json"
        return text, "dhall"
    _fail(
        f"Could not detect input format from {path or 'stdin'}. "
        f"Pass --input-format {{dhall,json,yaml}} explicitly."
    )


# ─────────────────────── friendly JSON/YAML -> Dhall ────────────────────────


def _dhall_string(s: str) -> str:
    """Emit a Dhall string literal (double-quoted; escape backslash + quote)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dhall_integer(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def _dhall_bool(b: bool) -> str:
    return "True" if b else "False"


def _dhall_pid_optional(pid: dict | None) -> str:
    """Encode `pid : Optional { type : Text, value : Integer }`."""
    if pid is None:
        return "None { type : Text, value : Integer }"
    ptype = pid.get("type", "PID")
    pvalue = int(pid["value"])
    return f'Some {{ type = "{ptype}", value = {_dhall_integer(pvalue)} }}'


def _dhall_display_name_config(cfg: str | dict) -> str:
    """Emit a Dhall DisplayNameConfig with the full union boilerplate.

    Accepts three friendly shapes:
      "some text"           -> DisplayByText "some text"
      {"text": "..."}      -> DisplayByText "..."
      {"parameter": {"pid": 12345, "metadata": ["parameterName"]}}
                           -> DisplayByParameter (DisplayParameterPID {_1=…, _2=…})
      {"parameter_vpid": {"vpid": 12345, "name": true}}
                           -> DisplayByParameter (DisplayParameterVPID {_1=…, _2=VPIDName})
      {"parameter_vpid": {"vpid": 12345, "metadata": ["..."]}}
                           -> DisplayByParameter (DisplayParameterVPID {_1=…, _2=InputMetadata …})
      {"other_parameter": ...}  -> DisplayByOtherParameter (…)
    """
    if isinstance(cfg, str):
        return f"{DNC_TYPE}.DisplayByText {_dhall_string(cfg)}"
    if not isinstance(cfg, dict):
        raise ValueError(f"display_name_config must be a string or dict, got {type(cfg).__name__}")
    if "text" in cfg:
        return f"{DNC_TYPE}.DisplayByText {_dhall_string(cfg['text'])}"

    variant_key = "DisplayByParameter" if "parameter" in cfg else (
        "DisplayByOtherParameter" if "other_parameter" in cfg else None
    )
    if variant_key is None:
        raise ValueError(
            "display_name_config dict must have key 'text', 'parameter', or 'other_parameter'; "
            f"got keys {list(cfg.keys())}"
        )
    inner = cfg[variant_key.replace("DisplayBy", "").lower().replace("_parameter", "_parameter") if False else ("parameter" if variant_key == "DisplayByParameter" else "other_parameter")]

    if "vpid" in inner:
        vpid = int(inner["vpid"])
        if inner.get("name") is True:
            snd = "< VPIDName | InputMetadata : List Text >.VPIDName"
        else:
            metadata = inner.get("metadata", [])
            metalist = "[ " + ", ".join(_dhall_string(m) for m in metadata) + " ]" if metadata else "([] : List Text)"
            snd = f"< VPIDName | InputMetadata : List Text >.InputMetadata {metalist}"
        param = f"{DNP_TYPE}.DisplayParameterVPID {{ _1 = {vpid}, _2 = {snd} }}"
    else:
        pid = int(inner["pid"])
        metadata = inner.get("metadata", ["parameterName"])
        metalist = "[ " + ", ".join(_dhall_string(m) for m in metadata) + " ]"
        param = f"{DNP_TYPE}.DisplayParameterPID {{ _1 = {pid}, _2 = {metalist} }}"

    return f"{DNC_TYPE}.{variant_key} ( {param} )"


def _dhall_parameter(param: dict) -> str:
    """Emit a Dhall y-axis Parameter record from a friendly dict."""
    pid = param.get("pid")
    name = param.get("name", "")
    dnc = param.get("display_name_config", name)  # default: DisplayByText <name>
    graph_type = param.get("graph_type", "line")
    color = param.get("color", "#0758bb")
    line_width = float(param.get("line_width", 1.0))
    hidden = bool(param.get("hidden", False))
    return (
        "{ pid = " + _dhall_pid_optional(pid)
        + f", name = {_dhall_string(name)}"
        + f", display_name_config = {_dhall_display_name_config(dnc)}"
        + f", graph_type = {_dhall_string(graph_type)}"
        + f", color = {_dhall_string(color)}"
        + f", line_width = {line_width}"
        + f", hidden = {_dhall_bool(hidden)}"
        + " }"
    )


def _dhall_yaxis(axis: dict) -> str:
    opposite = bool(axis.get("opposite", False))
    description = axis.get("description", "")
    scale = axis.get("scale", "linear")
    range_min = axis.get("rangeMin")
    range_max = axis.get("rangeMax")
    params = axis.get("parameters", [])
    params_dhall = ",\n      ".join(_dhall_parameter(p) for p in params) if params else ""
    rmin = f"Some {_dhall_integer(int(range_min))}" if range_min is not None else "None Integer"
    rmax = f"Some {_dhall_integer(int(range_max))}" if range_max is not None else "None Integer"
    return (
        "{ opposite = " + _dhall_bool(opposite)
        + f", description = {_dhall_string(description)}"
        + f", scale = {_dhall_string(scale)}"
        + f", rangeMin = {rmin}"
        + f", rangeMax = {rmax}"
        + ", parameters =\n      [ " + params_dhall + "\n      ]"
        + " }"
    )


def _dhall_event_parameter(ev: dict) -> str:
    pid = ev.get("pid")
    name = ev.get("name", "")
    dnc = ev.get("display_name_config", "")
    should_display = bool(ev.get("should_display", True))
    icon = ev.get("icon", "dot-circle-o")
    color = ev.get("color", "#0758bb")
    hidden = bool(ev.get("hidden", False))
    return (
        "{ pid = " + _dhall_pid_optional(pid)
        + f", name = {_dhall_string(name)}"
        + f", display_name_config = {_dhall_display_name_config(dnc)}"
        + f", should_display = {_dhall_bool(should_display)}"
        + f", icon = {_dhall_string(icon)}"
        + f", color = {_dhall_string(color)}"
        + f", hidden = {_dhall_bool(hidden)}"
        + " }"
    )


def _compile_friendly_to_dhall(spec: dict) -> str:
    """Compile a friendly JSON/YAML spec into a Dhall ExportedLineGraphWidget record."""
    if not isinstance(spec, dict):
        _fail(f"Friendly input must be a top-level object, got {type(spec).__name__}")
    title = spec.get("title", "New Chart")
    time_period = int(spec.get("timePeriod", 1))
    time_unit = spec.get("timeUnit", "hour")
    update_interval = int(spec.get("updateInterval", 60))
    y_axes = spec.get("yAxes", [])
    event_params = spec.get("eventParameters", [])
    max_step = int(spec.get("maxStep", 1))
    normalize_value = bool(spec.get("normalizeValue", False))
    latest_value_line = spec.get("latestValueLine")  # None -> None Bool, else Some ...
    legend_with_current_value = bool(spec.get("legendWithCurrentValue", True))

    y_axes_dhall = ",\n  ".join(_dhall_yaxis(a) for a in y_axes) if y_axes else ""
    events_dhall = ",\n  ".join(_dhall_event_parameter(e) for e in event_params) if event_params else ""
    if not event_params:
        # Need a typed empty list.
        events_dhall = f"[] : List {EVENT_PARAM_ELEM_TYPE}"
        events_block = events_dhall
    else:
        events_block = "[ " + events_dhall + "\n  ]"

    latest = "None Bool" if latest_value_line is None else (
        f"Some {_dhall_bool(bool(latest_value_line))}"
    )

    return (
        "{ title = " + _dhall_string(title)
        + f"\n, timePeriod = {_dhall_integer(time_period)}"
        + f"\n, timeUnit = {_dhall_string(time_unit)}"
        + f"\n, updateInterval = {_dhall_integer(update_interval)}"
        + "\n, yAxes =\n  [ " + y_axes_dhall + "\n  ]"
        + "\n, eventParameters =\n  " + events_block
        + f"\n, maxStep = {_dhall_integer(max_step)}"
        + f"\n, normalizeValue = {_dhall_bool(normalize_value)}"
        + f"\n, latestValueLine = {latest}"
        + f"\n, legendWithCurrentValue = {_dhall_bool(legend_with_current_value)}"
        + "\n}"
    )


# ─────────────────────── local shape check + pid extract ─────────────────────


REQUIRED_TOP_KEYS = (
    "title",
    "timePeriod",
    "timeUnit",
    "updateInterval",
    "yAxes",
    "eventParameters",
    "maxStep",
    "normalizeValue",
    "latestValueLine",
    "legendWithCurrentValue",
)


def _check_dhall_full_shape(dhall_text: str) -> list[str]:
    """Return a list of shape errors. Empty list = shape OK.

    This is a light textual check, not a Dhall type-check. It detects the two
    most common failure modes: (1) wrong shape (the input is a `[Field]` list,
    not a record), (2) missing top-level keys.
    """
    errors: list[str] = []
    stripped = dhall_text.lstrip()
    if stripped.startswith("["):
        errors.append(
            "Input is a Dhall LIST (starts with '['), but /import expects a "
            "record. This looks like a `-export-data` output — use "
            "`onping-line-graph-import-data` instead. See "
            "_line_graph_routes/SKILL.md for the schema gotcha."
        )
        return errors
    if not stripped.startswith("{"):
        errors.append(
            f"Input does not start with '{{' — not a Dhall record. First 80 chars:\n{stripped[:80]}"
        )
        return errors
    for key in REQUIRED_TOP_KEYS:
        # Match `<key> =` or `<key>:` at a plausible position (line start or after `, `).
        needle_eq = f"{key} ="
        needle_colon = f"{key} :"
        if needle_eq not in dhall_text and needle_colon not in dhall_text:
            errors.append(f"Missing top-level key: `{key}`")
    return errors


def _extract_pids(dhall_text: str) -> list[tuple[str, int]]:
    """Extract every `{ type = "PID"|"VPID", value = +N }` reference in order.

    Returns a list of (type, value) tuples. Used for the dry-run permission
    preview.
    """
    import re

    pids: list[tuple[str, int]] = []
    pattern = re.compile(
        r'\{\s*type\s*=\s*"(PID|VPID)"\s*,\s*value\s*=\s*\+?(-?\d+)\s*\}'
    )
    for m in pattern.finditer(dhall_text):
        pids.append((m.group(1), int(m.group(2))))
    # Deduplicate preserving order (a pid may be referenced from both the y-axis
    # parameter's `pid` and its `display_name_config` `_1`; only the first
    # matters for the permission-preview report).
    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, int]] = []
    for tup in pids:
        if tup not in seen:
            seen.add(tup)
            out.append(tup)
    return out


# ─────────────────────────────────── main ───────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(
        description="Import a full OnPing line-graph widget from a Dhall/JSON/YAML file "
        "via POST /content/widgets/line-graph/import/{id}. MUTATING; requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("--id", dest="widget_id", help="LineGraphWidgetId to overwrite (required unless --new)")
    p.add_argument(
        "--new",
        action="store_true",
        help="mint a fresh widget id via POST /config, then import into it (two-step)",
    )
    p.add_argument("--input", dest="input_path", help="input file (default: read from stdin)")
    p.add_argument(
        "--input-format",
        choices=("dhall", "json", "yaml"),
        help="input format override (default: auto-detect by extension / content)",
    )
    p.add_argument("--yes", action="store_true", help="perform the import (required to write)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit preview (default when --yes is not passed); wins over --yes",
    )
    p.add_argument("--json", dest="emit_json", action="store_true", help="emit the imported widget JSON on success")
    args = p.parse_args()

    if not args.widget_id and not args.new:
        _fail("Either --id <widget-id> or --new is required.")
    if args.widget_id and args.new:
        _fail("Pass either --id OR --new, not both.")

    # ── 1. Read + compile input to Dhall ──
    text, fmt = _read_input(args.input_path, args.input_format)
    if fmt == "dhall":
        dhall_body = text
    elif fmt == "json":
        try:
            spec = json.loads(text)
        except json.JSONDecodeError as e:
            _fail(f"Invalid JSON input: {e}")
        dhall_body = _compile_friendly_to_dhall(spec)
    elif fmt == "yaml":
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as e:
            _fail(f"Invalid YAML input: {e}")
        dhall_body = _compile_friendly_to_dhall(spec)
    else:
        _fail(f"Unknown input format: {fmt}")

    # ── 2. Local shape check + pid extraction ──
    errors = _check_dhall_full_shape(dhall_body)
    pids = _extract_pids(dhall_body)

    # ── 3. Preview or apply ──
    if args.dry_run or not args.yes:
        print("=== PREVIEW ===")
        if args.new:
            print("Would MINT a fresh widget id via POST /config, then IMPORT into it.")
        else:
            print(f"Would OVERWRITE widget id: {args.widget_id}")
        print(f"Input format: {fmt}")
        if fmt != "dhall":
            print("(friendly input compiled to Dhall — the Dhall body will be POSTed)")
        print()
        print("Shape check:")
        if errors:
            for e in errors:
                print(f"  ✗ {e}")
        else:
            print("  ✓ Dhall record has all required top-level keys.")
        print()
        print(
            f"PID/VPID list ({len(pids)} unique refs — the server will "
            f"permission-check EVERY one; the widget is NOT modified if ANY is denied):"
        )
        for kind, value in pids:
            print(f"  {kind} {value}")
        print()
        print("--dry-run — no write performed.")
        if errors:
            sys.exit(2)
        return

    if errors:
        _fail(
            "Local shape check failed; refusing to POST. Fix these issues (or "
            "re-run without --yes for a full preview):\n"
            + "\n".join(f"  ✗ {e}" for e in errors)
        )

    # ── 4. --new: mint a fresh id first, then import into it ──
    target_id = args.widget_id
    if args.new:
        mint_resp = post_empty(args.access_token, ROUTES["config"]["endpoint"])
        if not (200 <= mint_resp.status_code < 300):
            _fail(f"HTTP {mint_resp.status_code} minting fresh widget: {extract_error(mint_resp)}")
        try:
            target_id = mint_resp.json()
        except ValueError:
            _fail(f"Expected JSON id, got: {mint_resp.text[:500]}")
        if not isinstance(target_id, str):
            _fail(f"Expected JSON string id, got: {target_id!r}")
        print(f"Minted fresh widget id: {target_id}", file=sys.stderr)

    # ── 5. Import the Dhall body ──
    resp = post_dhall(
        args.access_token,
        ROUTES["import"]["endpoint"],
        dhall_body,
        widget_id=target_id,
    )
    if not (200 <= resp.status_code < 300):
        err = extract_error(resp)
        if args.new:
            _fail(
                f"HTTP {resp.status_code} importing into fresh widget {target_id}: {err}\n"
                f"The widget {target_id} was CREATED but is now EMPTY. "
                f"There is no delete route — clean up by removing its parent "
                f"dashboard, or leave it orphaned."
            )
        _fail(
            f"HTTP {resp.status_code} importing into widget {target_id}: {err}\n"
            f"The target widget was NOT modified."
        )

    try:
        widget = resp.json()
    except ValueError:
        _fail(f"Expected JSON widget in response, got: {resp.text[:500]}")

    if args.new:
        print(target_id)
    else:
        print(f"Imported into widget {target_id}", file=sys.stderr)
    if args.emit_json:
        print(json.dumps(widget))


if __name__ == "__main__":
    main()
