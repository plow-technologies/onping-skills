# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Normalize, expand, validate, and fetch control parameter JSON imports."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from typing import Any

import requests

DEFAULTS = {
    "resolution": 2048,
    "enabled": True,
    "throttle": None,
    "calculateRetryStrategy": "default",
    "writeRetryStrategy": "default",
}
DEFAULT_TRIGGER = "OnInputChangeAny"
CP_ID_KEYS = {"cpId", "cpIdOrSerial"}


@dataclass
class ValidationMessage:
    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def simplify_number(value: float) -> float | int:
    if math.isfinite(value) and float(value).is_integer():
        return int(value)
    return value


def read_json(path: str | None) -> Any:
    try:
        if path:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return json.load(sys.stdin)
    except FileNotFoundError:
        print(f"Input file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)


def write_json(data: Any, output_path: str | None, pretty: bool = True) -> None:
    dump = json.dumps(data, indent=2 if pretty else None, sort_keys=False)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(dump)
            f.write("\n")
    else:
        print(dump)


def is_default_retry_strategy(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() == "default"
    if isinstance(value, dict):
        tag = value.get("tag")
        constructor = value.get("constructor")
        if tag == "DefaultRetryStrategy" or constructor == "DefaultRetryStrategy":
            return True
        if value == {"DefaultRetryStrategy": {}}:
            return True
    return False


def is_cp_data_dict(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    required = {"inputs", "outputs", "script"}
    return required.issubset(value.keys())


def normalize_record_output_map(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        out: dict[str, Any] = {}
        for item in value:
            if isinstance(item, dict) and "mapKey" in item and "mapValue" in item:
                out[str(item["mapKey"])] = item["mapValue"]
            else:
                return value
        return out
    return value


def is_generic_output(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if "ScalarOutput" in value or "RecordOutput" in value:
        return True
    tag = value.get("tag")
    return tag in {"ScalarOutput", "RecordOutput"}


def normalize_outputs(value: Any) -> Any:
    if is_number(value):
        return int(value)
    if not isinstance(value, dict):
        return value

    if "ScalarOutput" in value:
        scalar = value["ScalarOutput"]
        return int(scalar) if is_number(scalar) else scalar
    if "RecordOutput" in value:
        return normalize_record_output_map(value["RecordOutput"])

    tag = value.get("tag")
    if tag == "ScalarOutput":
        contents = value.get("contents")
        return int(contents) if is_number(contents) else contents
    if tag == "RecordOutput":
        return normalize_record_output_map(value.get("contents"))

    return value


def expand_outputs(value: Any) -> Any:
    if is_number(value):
        return {"ScalarOutput": int(value)}
    if isinstance(value, dict):
        if is_generic_output(value):
            return value
        return {"RecordOutput": value}
    return value


def cpid_to_friendly(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None

    if "engineHost" in value and "perEngineId" in value:
        return f"{value['engineHost']}-{value['perEngineId']}"

    if "CPID" in value and isinstance(value["CPID"], dict):
        cp = value["CPID"]
        if "engineHost" in cp and "perEngineId" in cp:
            return f"{cp['engineHost']}-{cp['perEngineId']}"

    if "ACPID" in value and isinstance(value["ACPID"], dict):
        cp = value["ACPID"]
        if "engineHost" in cp and "perEngineId" in cp:
            return f"{cp['engineHost']}-{cp['perEngineId']}"

    tag = value.get("tag")
    contents = value.get("contents")
    if tag in {"CPID", "ACPID"} and isinstance(contents, dict):
        if "engineHost" in contents and "perEngineId" in contents:
            return f"{contents['engineHost']}-{contents['perEngineId']}"

    return None


def parse_friendly_cpid(value: str) -> tuple[int, str] | None:
    if "-" not in value:
        return None
    host_text, per_engine_id = value.rsplit("-", 1)
    if not host_text or not per_engine_id:
        return None
    try:
        host = int(host_text)
    except ValueError:
        return None
    return host, per_engine_id


def normalize_cp_id_field(field_name: str, value: Any) -> Any:
    if field_name == "cpIdOrSerial" and is_number(value):
        return int(value)

    friendly = cpid_to_friendly(value)
    if friendly is not None:
        return friendly

    if field_name == "cpIdOrSerial" and isinstance(value, dict) and "ALJSerial" in value:
        serial = value["ALJSerial"]
        if is_number(serial):
            return int(serial)

    return value


def expand_cp_id_field(field_name: str, value: Any) -> Any:
    if field_name == "cpIdOrSerial" and is_number(value):
        return {"ALJSerial": int(value)}

    if isinstance(value, str):
        parsed = parse_friendly_cpid(value)
        if parsed is None:
            return value
        host, per_engine_id = parsed
        if field_name == "cpId":
            return {"engineHost": host, "perEngineId": per_engine_id}
        return {"ACPID": {"engineHost": host, "perEngineId": per_engine_id}}

    if field_name == "cpId" and isinstance(value, dict) and "ACPID" in value:
        acpid = value.get("ACPID")
        if isinstance(acpid, dict) and "engineHost" in acpid and "perEngineId" in acpid:
            return {"engineHost": acpid["engineHost"], "perEngineId": acpid["perEngineId"]}

    if field_name == "cpIdOrSerial" and isinstance(value, dict) and "CPID" in value:
        cp = value.get("CPID")
        if isinstance(cp, dict) and "engineHost" in cp and "perEngineId" in cp:
            return {"ACPID": {"engineHost": cp["engineHost"], "perEngineId": cp["perEngineId"]}}

    return value


def unpack_on_cron_schedule(value: Any) -> tuple[str | None, Any, bool]:
    if isinstance(value, str):
        return value, None, True
    if isinstance(value, dict):
        if "_1" in value:
            return value.get("_1"), value.get("_2"), True
        if "schedule" in value:
            return value.get("schedule"), value.get("retry"), True
    if isinstance(value, list) and len(value) == 2:
        return value[0], value[1], True
    return None, None, False


def parse_on_input_change(value: Any) -> tuple[str | None, Any]:
    if value == "OnInputChangeAny":
        return "any", None
    if isinstance(value, dict):
        if "OnInputChangeAny" in value:
            return "any", None
        if "OnInputChangeOnly" in value:
            return "only", value["OnInputChangeOnly"]
        if "OnInputChangeExcept" in value:
            return "except", value["OnInputChangeExcept"]
        tag = value.get("tag")
        if tag == "OnInputChangeAny":
            return "any", None
        if tag == "OnInputChangeOnly":
            return "only", value.get("contents")
        if tag == "OnInputChangeExcept":
            return "except", value.get("contents")
    return None, None


def normalize_trigger(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if is_number(value):
        return value
    if isinstance(value, str):
        if value == "OnInputChangeAny":
            return None
        return value
    if not isinstance(value, dict):
        return value

    if "OnInputChange" in value:
        mode, payload = parse_on_input_change(value["OnInputChange"])
        if mode == "any":
            return None
        if mode == "only":
            return payload
        if mode == "except":
            return value

    if "OnCronSchedule" in value:
        schedule, retry, ok = unpack_on_cron_schedule(value["OnCronSchedule"])
        if ok and isinstance(schedule, str) and retry in (None, {}):
            return schedule
        return value

    if "Periodic" in value:
        periodic = value["Periodic"]
        if is_number(periodic):
            return simplify_number(float(periodic) / 60.0)

    tag = value.get("tag")
    contents = value.get("contents")
    if tag == "OnInputChange":
        mode, payload = parse_on_input_change(contents)
        if mode == "any":
            return None
        if mode == "only":
            return payload
        if mode == "except":
            return value
    if tag == "OnCronSchedule":
        schedule, retry, ok = unpack_on_cron_schedule(contents)
        if ok and isinstance(schedule, str) and retry in (None, {}):
            return schedule
        return value
    if tag == "Periodic" and is_number(contents):
        return simplify_number(float(contents) / 60.0)

    mode, payload = parse_on_input_change(value)
    if mode == "any":
        return None
    if mode == "only":
        return payload
    if mode == "except":
        return value

    return value


def is_generic_trigger(value: Any) -> bool:
    if isinstance(value, str):
        return value == "OnInputChangeAny"
    if not isinstance(value, dict):
        return False
    if any(key in value for key in ("OnInputChange", "OnCronSchedule", "Periodic")):
        return True
    tag = value.get("tag")
    return tag in {"OnInputChange", "OnCronSchedule", "Periodic"}


def expand_trigger(value: Any) -> Any:
    if value is None:
        return DEFAULT_TRIGGER
    if isinstance(value, str):
        if value == "OnInputChangeAny":
            return value
        return {"OnCronSchedule": {"_1": value, "_2": None}}
    if isinstance(value, list):
        return {"OnInputChange": {"OnInputChangeOnly": value}}
    if is_number(value):
        return {"Periodic": simplify_number(float(value) * 60.0)}
    if isinstance(value, dict) and is_generic_trigger(value):
        return value
    return value


def normalize_cp_data(cp_data: dict[str, Any]) -> dict[str, Any]:
    out = dict(cp_data)

    if "outputs" in out:
        out["outputs"] = normalize_outputs(out["outputs"])
    if "trigger" in out:
        out["trigger"] = normalize_trigger(out["trigger"])

    if out.get("resolution") == DEFAULTS["resolution"]:
        out.pop("resolution", None)
    if out.get("enabled") is DEFAULTS["enabled"]:
        out.pop("enabled", None)
    if out.get("throttle") is DEFAULTS["throttle"]:
        out.pop("throttle", None)
    if "calculateRetryStrategy" in out and is_default_retry_strategy(out.get("calculateRetryStrategy")):
        out.pop("calculateRetryStrategy", None)
    if "writeRetryStrategy" in out and is_default_retry_strategy(out.get("writeRetryStrategy")):
        out.pop("writeRetryStrategy", None)

    if out.get("trigger") is None:
        out.pop("trigger", None)

    return out


def expand_cp_data(cp_data: dict[str, Any]) -> dict[str, Any]:
    out = dict(cp_data)

    if "outputs" in out:
        out["outputs"] = expand_outputs(out["outputs"])

    out["resolution"] = out.get("resolution", DEFAULTS["resolution"])
    out["enabled"] = out.get("enabled", DEFAULTS["enabled"])
    out["throttle"] = out.get("throttle", DEFAULTS["throttle"])
    if "calculateRetryStrategy" not in out or is_default_retry_strategy(out.get("calculateRetryStrategy")):
        out["calculateRetryStrategy"] = DEFAULTS["calculateRetryStrategy"]
    if "writeRetryStrategy" not in out or is_default_retry_strategy(out.get("writeRetryStrategy")):
        out["writeRetryStrategy"] = DEFAULTS["writeRetryStrategy"]

    out["trigger"] = expand_trigger(out.get("trigger"))

    return out


def transform_document(value: Any, mode: str) -> Any:
    if isinstance(value, list):
        return [transform_document(item, mode) for item in value]

    if not isinstance(value, dict):
        return value

    if is_cp_data_dict(value):
        if mode == "normalize":
            return normalize_cp_data(value)
        return expand_cp_data(value)

    out: dict[str, Any] = {}
    for key, item in value.items():
        if key == "cpData" and isinstance(item, dict):
            out[key] = normalize_cp_data(item) if mode == "normalize" else expand_cp_data(item)
            continue

        if key in CP_ID_KEYS:
            if mode == "normalize":
                out[key] = normalize_cp_id_field(key, item)
            else:
                out[key] = expand_cp_id_field(key, item)
            continue

        out[key] = transform_document(item, mode)

    return out


def extract_output_pids(outputs: Any) -> list[int]:
    pids: list[int] = []

    normalized = normalize_outputs(outputs)
    if is_number(normalized):
        pids.append(int(normalized))
        return pids

    if isinstance(normalized, dict):
        for value in normalized.values():
            if is_number(value):
                pids.append(int(value))

    return pids


def detect_trigger_kind(trigger: Any) -> str | None:
    normalized = normalize_trigger(trigger)
    if normalized is None:
        return "OnInputChangeAny"
    if isinstance(normalized, list):
        return "OnInputChangeOnly"
    if isinstance(normalized, str):
        return "OnCronSchedule"
    if is_number(normalized):
        return "Periodic"

    if isinstance(trigger, dict):
        if "OnInputChange" in trigger:
            mode, _ = parse_on_input_change(trigger["OnInputChange"])
            if mode == "except":
                return "OnInputChangeExcept"
        tag = trigger.get("tag")
        if tag == "OnInputChange":
            mode, _ = parse_on_input_change(trigger.get("contents"))
            if mode == "except":
                return "OnInputChangeExcept"

    return None


def collect_cp_entries(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any], dict[str, Any] | None]]:
    entries: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []

    def walk(value: Any, at: str) -> None:
        if isinstance(value, dict):
            if "cpData" in value and isinstance(value["cpData"], dict):
                entries.append((f"{at}.cpData", value["cpData"], value))
                for key, item in value.items():
                    if key != "cpData":
                        walk(item, f"{at}.{key}")
                return

            if is_cp_data_dict(value):
                entries.append((at, value, None))
                return

            for key, item in value.items():
                walk(item, f"{at}.{key}")
            return

        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{at}[{index}]")

    walk(node, path)
    return entries


def validate_document(doc: Any, strict: bool = False) -> dict[str, Any]:
    errors: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []
    entries = collect_cp_entries(doc)
    seen_outputs: dict[int, str] = {}

    for cp_path, cp_data, container in entries:
        for required in ("inputs", "outputs", "script", "name", "description"):
            if required not in cp_data:
                errors.append(
                    ValidationMessage(
                        path=f"{cp_path}.{required}",
                        code="missing_required",
                        message=f"Missing required field '{required}'.",
                    )
                )

        if "script" in cp_data and not isinstance(cp_data["script"], str):
            errors.append(
                ValidationMessage(
                    path=f"{cp_path}.script",
                    code="invalid_type",
                    message="'script' must be a string.",
                )
            )

        if "inputs" in cp_data and not isinstance(cp_data["inputs"], (list, dict)):
            errors.append(
                ValidationMessage(
                    path=f"{cp_path}.inputs",
                    code="invalid_type",
                    message="'inputs' must be a list or dict.",
                )
            )

        if "resolution" in cp_data:
            resolution = cp_data["resolution"]
            if not isinstance(resolution, int) or isinstance(resolution, bool) or resolution <= 0:
                errors.append(
                    ValidationMessage(
                        path=f"{cp_path}.resolution",
                        code="invalid_value",
                        message="'resolution' must be a positive integer.",
                    )
                )

        if "enabled" in cp_data and not isinstance(cp_data["enabled"], bool):
            errors.append(
                ValidationMessage(
                    path=f"{cp_path}.enabled",
                    code="invalid_type",
                    message="'enabled' must be a boolean.",
                )
            )

        if "throttle" in cp_data and cp_data["throttle"] is not None and not is_number(cp_data["throttle"]):
            errors.append(
                ValidationMessage(
                    path=f"{cp_path}.throttle",
                    code="invalid_type",
                    message="'throttle' must be null or numeric seconds.",
                )
            )

        for text_field in ("name", "description"):
            if text_field in cp_data and not isinstance(cp_data[text_field], str):
                errors.append(
                    ValidationMessage(
                        path=f"{cp_path}.{text_field}",
                        code="invalid_type",
                        message=f"'{text_field}' must be a string.",
                    )
                )

        if "outputs" in cp_data:
            outputs = cp_data["outputs"]
            normalized = normalize_outputs(outputs)
            if not (is_number(normalized) or isinstance(normalized, dict)):
                errors.append(
                    ValidationMessage(
                        path=f"{cp_path}.outputs",
                        code="invalid_value",
                        message="'outputs' must be scalar PID or record map.",
                    )
                )
            else:
                for pid in extract_output_pids(outputs):
                    if pid in seen_outputs and seen_outputs[pid] != cp_path:
                        warnings.append(
                            ValidationMessage(
                                path=f"{cp_path}.outputs",
                                code="output_exclusivity",
                                message=(
                                    f"Output PID {pid} is already used by another control parameter "
                                    f"at {seen_outputs[pid]}."
                                ),
                            )
                        )
                    else:
                        seen_outputs[pid] = cp_path

        if "trigger" in cp_data:
            trigger_kind = detect_trigger_kind(cp_data["trigger"])
            if trigger_kind is None:
                errors.append(
                    ValidationMessage(
                        path=f"{cp_path}.trigger",
                        code="invalid_trigger",
                        message="Trigger format is not recognized.",
                    )
                )

        if container is not None:
            for cp_key in CP_ID_KEYS:
                if cp_key not in container:
                    continue
                cp_id = container[cp_key]
                if isinstance(cp_id, str) and parse_friendly_cpid(cp_id) is None:
                    warnings.append(
                        ValidationMessage(
                            path=f"{cp_path.rsplit('.', 1)[0]}.{cp_key}",
                            code="cpid_parse_fallback",
                            message=(
                                "Friendly CPID parsing failed; treating value as generic format. "
                                "Use '<engineHost>-<perEngineId>' for friendly CPID strings."
                            ),
                        )
                    )

    if strict and warnings:
        for warning in warnings:
            errors.append(
                ValidationMessage(
                    path=warning.path,
                    code="strict_warning",
                    message=warning.message,
                )
            )
        warnings = []

    report = {
        "ok": len(errors) == 0,
        "strict": strict,
        "stats": {
            "controlParameters": len(entries),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "errors": [error.to_dict() for error in errors],
        "warnings": [warning.to_dict() for warning in warnings],
    }
    return report


def fetch_control_parameters(access_token: str, lumberjack_id: int) -> Any:
    url = "https://onping.plowtech.net/cpInferno/list"
    headers = {
        "Accept": "application/json",
        "Content-Type": "text/plain;charset=UTF-8",
        "Authorization": f"Bearer {access_token}",
    }
    tries = 0

    while True:
        try:
            resp = requests.post(
                url,
                data=str(lumberjack_id),
                headers=headers,
                allow_redirects=False,
                timeout=15,
            )
        except requests.RequestException as exc:
            print(f"Request error for Lumberjack {lumberjack_id}: {exc}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(
                    "Authentication failed too many times "
                    f"for Lumberjack {lumberjack_id} (status {resp.status_code}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(
                f"HTTP {resp.status_code} for Lumberjack {lumberjack_id}:\n{resp.text}",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            return resp.json()
        except ValueError as exc:
            print(
                f"Failed to decode JSON response for Lumberjack {lumberjack_id}: {exc}",
                file=sys.stderr,
            )
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)


def add_io_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", help="Input JSON file path (defaults to stdin)")
    parser.add_argument("--output", help="Output JSON file path (defaults to stdout)")
    parser.add_argument(
        "--pretty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pretty-print JSON output (default: true)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Control-parameter import JSON formatter, expander, and validator."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    normalize = sub.add_parser("normalize", help="Convert CP JSON to friendly format")
    add_io_args(normalize)

    expand = sub.add_parser("expand", help="Convert friendly CP JSON to explicit format")
    add_io_args(expand)

    validate = sub.add_parser("validate", help="Validate CP import JSON")
    add_io_args(validate)
    validate.add_argument(
        "--strict",
        action="store_true",
        help="Treat validation warnings as errors",
    )

    fetch_normalize = sub.add_parser(
        "fetch-normalize",
        help="Fetch control parameters by Lumberjack ID and normalize result",
    )
    fetch_normalize.add_argument("access_token", help="OnPing OAuth2 access token")
    fetch_normalize.add_argument(
        "lumberjack_ids",
        nargs="+",
        type=int,
        help="One or more numeric Lumberjack IDs",
    )
    fetch_normalize.add_argument("--output", help="Output JSON file path (defaults to stdout)")
    fetch_normalize.add_argument(
        "--pretty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pretty-print JSON output (default: true)",
    )

    return parser


def handle_transform(command: str, input_path: str | None, output_path: str | None, pretty: bool) -> int:
    doc = read_json(input_path)
    result = transform_document(doc, mode=command)
    write_json(result, output_path, pretty=pretty)
    return 0


def handle_validate(input_path: str | None, output_path: str | None, pretty: bool, strict: bool) -> int:
    doc = read_json(input_path)
    report = validate_document(doc, strict=strict)
    write_json(report, output_path, pretty=pretty)
    return 0 if report["ok"] else 1


def handle_fetch_normalize(
    access_token: str,
    lumberjack_ids: list[int],
    output_path: str | None,
    pretty: bool,
) -> int:
    if len(lumberjack_ids) == 1:
        raw = fetch_control_parameters(access_token, lumberjack_ids[0])
    else:
        raw = {
            str(lumberjack_id): fetch_control_parameters(access_token, lumberjack_id)
            for lumberjack_id in lumberjack_ids
        }

    normalized = transform_document(raw, mode="normalize")
    write_json(normalized, output_path, pretty=pretty)
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "normalize":
        code = handle_transform("normalize", args.input, args.output, args.pretty)
    elif args.command == "expand":
        code = handle_transform("expand", args.input, args.output, args.pretty)
    elif args.command == "validate":
        code = handle_validate(args.input, args.output, args.pretty, args.strict)
    else:
        code = handle_fetch_normalize(
            access_token=args.access_token,
            lumberjack_ids=args.lumberjack_ids,
            output_path=args.output,
            pretty=args.pretty,
        )

    sys.exit(code)


if __name__ == "__main__":
    main()
