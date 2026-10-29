# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Normalize, expand, validate, and fetch control parameter JSON imports."""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULTS = {
    "resolution": 2048,
    "enabled": True,
    "throttle": None,
    # The server's default retry strategy is NoRetries (control-parameters-types
    # src/ControlParameters/Types.hs `defaultRetryStrategy = NoRetries`; JSON {"tag": "NoRetries"}).
    "calculateRetryStrategy": {"tag": "NoRetries"},
    "writeRetryStrategy": {"tag": "NoRetries"},
}
DEFAULT_TRIGGER = "OnInputChangeAny"
CP_ID_KEYS = {"cpId", "cpIdOrSerial"}
# A friendly CPID '<engineHost>-<uuid>' as the server parses it (`parseJSONFriendlyCPIDString`,
# onping-frontend-types ControlParametersInferno.hs): an integer LJSerial read with
# `reads`, and a UUID as Data.UUID parses it (8-4-4-4-12 hex digits, either case).
_FRIENDLY_HOST_RE = re.compile(r"-?[0-9]+")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# /cpInferno/list element tags (onping-frontend-types ReadableControlParameterInferno, #16220).
READABLE_TAG = "ReadableControlParameterInferno"  # contents: {cpId, cpData}
ORPHANED_TAG = "OrphanedControlParameterInferno"  # contents: [{cpId, cpData}, [missing PID, ...]]
PROHIBITED_TAG = "ProhibitedReadControlParameterInferno"  # contents: CPID
FAILED_TAG = "FailedToReadControlParameterInfernoPermissions"  # contents: CPID
NOT_READABLE_TAGS = {PROHIBITED_TAG, FAILED_TAG}
LIST_ELEMENT_TAGS = {READABLE_TAG, ORPHANED_TAG} | NOT_READABLE_TAGS


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
    """True for the server default retry strategy, NoRetries (Types.hs), or a legacy spelling."""
    if isinstance(value, str):
        return value.lower() == "default"
    if isinstance(value, dict):
        tag = value.get("tag")
        constructor = value.get("constructor")
        if tag in ("NoRetries", "DefaultRetryStrategy") or constructor in ("NoRetries", "DefaultRetryStrategy"):
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
    """Split a friendly '<engineHost>-<uuid>' CPID the way the server does.

    The UUID is the last five '-' parts and must be a UUID; everything before it is
    the engine host and must be an integer (`parseJSONFriendlyCPIDString`,
    onping-frontend-types ControlParametersInferno.hs). inferno-cp-import's
    `_cp_id_text` applies the same rule.
    """
    parts = value.split("-")
    if len(parts) < 6:
        return None
    host_text, per_engine_id = "-".join(parts[:-5]), "-".join(parts[-5:])
    if not _FRIENDLY_HOST_RE.fullmatch(host_text) or not _UUID_RE.fullmatch(per_engine_id):
        return None
    return int(host_text), per_engine_id


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
    """Friendly form of one CP's fields.

    The default trigger (OnInputChangeAny) is omitted, on a create and on an update, as
    the server's friendly ToJSON does (onping-frontend-types ControlParametersInferno.hs);
    /cpInferno/import reads a missing trigger back as OnInputChangeAny.
    """
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
    # Deep copies: the DEFAULTS dicts must not be shared by every expanded CP.
    if "calculateRetryStrategy" not in out or is_default_retry_strategy(out.get("calculateRetryStrategy")):
        out["calculateRetryStrategy"] = copy.deepcopy(DEFAULTS["calculateRetryStrategy"])
    if "writeRetryStrategy" not in out or is_default_retry_strategy(out.get("writeRetryStrategy")):
        out["writeRetryStrategy"] = copy.deepcopy(DEFAULTS["writeRetryStrategy"])

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


def wrapper_tag(value: Any) -> str | None:
    """The tag of any ``{"tag": <str>, "contents": ...}`` wrapper, known or not."""
    if isinstance(value, dict) and "contents" in value and isinstance(value.get("tag"), str):
        return value["tag"]
    return None


def list_element_tag(value: Any) -> str | None:
    """The tag of a known /cpInferno/list element, or None if value is not one."""
    tag = wrapper_tag(value)
    return tag if tag in LIST_ELEMENT_TAGS else None


def cpid_text(value: Any) -> str:
    if value is None:
        return "<unparsed>"
    friendly = cpid_to_friendly(value)
    if friendly is not None:
        return friendly
    if isinstance(value, str):
        return value
    return json.dumps(value)


@dataclass
class OrphanInfo:
    path: str
    cp_id: str
    name: str
    missing_pids: Any
    live_pids: list[int] = field(default_factory=list)

    def describe(self) -> str:
        text = (
            f"{self.path} {self.cp_id} {json.dumps(self.name)} "
            f"missing output PIDs {json.dumps(self.missing_pids)}"
        )
        if self.live_pids:
            text += f"; still claims live output PIDs {json.dumps(self.live_pids)}"
        return text


def element_cp(element: dict[str, Any]) -> Any:
    """The ``{cpId, cpData}`` object of a Readable or Orphaned element (None if malformed)."""
    contents = element.get("contents")
    if element.get("tag") == ORPHANED_TAG:
        if isinstance(contents, list) and len(contents) == 2:
            return contents[0]
        return None
    return contents


def malformed_reason(cp: Any) -> str | None:
    """Why a Readable/Orphaned element's ``{cpId, cpData}`` cannot be imported, or None.

    Both fields are required (ControlParameterInferno: ``cpId :: CPID``). Without a cpId
    the entry would be a create, so a malformed element is dropped, not passed on.
    """
    if not isinstance(cp, dict):
        return "no {cpId, cpData} object"
    if not isinstance(cp.get("cpData"), dict):
        return "no cpData object"
    if cp.get("cpId") is None:
        return "no cpId"
    return None


def orphan_info(element: dict[str, Any], path: str) -> OrphanInfo:
    contents = element.get("contents")
    cp: Any = None
    missing: Any = None
    if isinstance(contents, list) and len(contents) == 2:
        cp, missing = contents
    cp_id = cpid_text(cp.get("cpId")) if isinstance(cp, dict) else "<unparsed>"
    name: Any = ""
    live: list[int] = []
    if isinstance(cp, dict) and isinstance(cp.get("cpData"), dict):
        cp_data = cp["cpData"]
        name = cp_data.get("name", "")
        missing_set = {int(pid) for pid in missing if is_number(pid)} if isinstance(missing, list) else set()
        live = [pid for pid in extract_output_pids(cp_data.get("outputs")) if pid not in missing_set]
    return OrphanInfo(
        path=path,
        cp_id=cp_id,
        name=name if isinstance(name, str) else str(name),
        missing_pids=missing,
        live_pids=live,
    )


@dataclass
class ListElement:
    """One tagged /cpInferno/list element found in a document, and what normalize does with it."""

    path: str
    tag: str
    element: dict[str, Any]
    action: str = ""  # "unwrapped", "dropped" or "malformed" (dropped: no usable {cpId, cpData})
    orphan: OrphanInfo | None = None
    reason: str = ""  # why a malformed element cannot be imported

    @property
    def known(self) -> bool:
        return self.tag in LIST_ELEMENT_TAGS


DROPPED = object()  # `scan_list_document`: marks a dropped element while rebuilding


def root_dropped(elements: list["ListElement"]) -> bool:
    """True when the document root is itself a list element that was not kept."""
    return any(el.path == "$" and el.action != "unwrapped" for el in elements)


def scan_list_document(
    doc: Any, include_orphans: bool = False, build: bool = True
) -> tuple[Any, list[ListElement]]:
    """The single walk over /cpInferno/list elements, shared by normalize and validate.

    Returns ``(import_document, elements)``. In the import document each
    ``{tag, contents}`` wrapper is replaced as follows; nothing is normalised here
    (normalize runs one `transform_document` pass over the result):

    - ``ReadableControlParameterInferno``: its raw ``{cpId, cpData}`` object, which
      /cpInferno/import reads as an update (`NewOrExistingControlParameterInferno2` accepts
      a nested ``cpData``);
    - ``OrphanedControlParameterInferno``: dropped, or its ``{cpId, cpData}`` when
      ``include_orphans``;
    - ``ProhibitedRead...`` / ``FailedToRead...`` (CPID only, nothing to import) and
      unknown tags: dropped;
    - a Readable/Orphaned element with no usable ``{cpId, cpData}``: dropped as malformed.

    A dropped element is removed: from its list, or, as the value of an object key,
    together with its key (never left as ``null``). When the document root is itself a
    dropped element, the import document is ``[]`` (and normalize exits 1, see
    `normalize_list_document_status`).

    With ``build=False`` only the element list is computed (validate) and the import
    document is None.

    A known tag is recognised anywhere outside a CP object. An unknown ``{tag, contents}``
    wrapper counts as a list element only in a list that is the document root, a value of
    the root object (multi-Lumberjack output), or a list that also holds known elements.
    """
    elements: list[ListElement] = []

    def visit(item: dict[str, Any], at: str, tag: str) -> tuple[bool, Any]:
        record = ListElement(path=at, tag=tag, element=item)
        elements.append(record)
        if tag == ORPHANED_TAG:
            record.orphan = orphan_info(item, at)
        if tag not in (READABLE_TAG, ORPHANED_TAG):
            record.action = "dropped"
            return False, None
        cp = element_cp(item)
        reason = malformed_reason(cp)
        if reason is not None:
            record.action, record.reason = "malformed", reason
            return False, None
        if tag == ORPHANED_TAG and not include_orphans:
            record.action = "dropped"
            return False, None
        record.action = "unwrapped"
        return True, cp

    def walk(value: Any, at: str, top: bool) -> Any:
        """The rebuilt value, or ``DROPPED`` when ``value`` is itself a dropped element."""
        if isinstance(value, list):
            listing = top or any(list_element_tag(item) is not None for item in value)
            out = []
            for index, item in enumerate(value):
                item_path = f"{at}[{index}]"
                tag = list_element_tag(item) or (wrapper_tag(item) if listing else None)
                if tag is None:
                    out.append(walk(item, item_path, False))
                    continue
                keep, new_item = visit(item, item_path, tag)
                if keep:
                    out.append(new_item)
            return out if build else None
        if isinstance(value, dict):
            tag = list_element_tag(value)
            if tag is not None:
                keep, new_value = visit(value, at, tag)
                if not keep:
                    return DROPPED
                return new_value if build else None
            if "cpData" in value or is_cp_data_dict(value):
                return value if build else None
            out_dict = {}
            for key, item in value.items():
                new_item = walk(item, f"{at}.{key}", at == "$")
                if new_item is not DROPPED:
                    out_dict[key] = new_item
            return out_dict if build else None
        return value if build else None

    result = walk(doc, "$", True)
    if result is DROPPED:
        return ([] if build else None), elements
    return result, elements


def report_list_elements(elements: list[ListElement], import_doc: Any, include_orphans: bool) -> None:
    """stderr notices for every element normalize did not pass through as a plain CP."""
    orphans = [el.orphan for el in elements if el.orphan is not None and el.action != "malformed"]
    if orphans:
        if include_orphans:
            head = (
                f"cp-import-json: kept {len(orphans)} orphaned CP(s) (--include-orphans); "
                "an output PID was deleted, so re-importing as-is points at PIDs that do not exist:"
            )
        else:
            head = (
                f"cp-import-json: omitted {len(orphans)} orphaned CP(s) (an output PID was deleted); "
                "pass --include-orphans to keep them:"
            )
        print(head, file=sys.stderr)
        for orphan in orphans:
            print(f"  {orphan.describe()}", file=sys.stderr)

    not_readable = [el for el in elements if el.tag in NOT_READABLE_TAGS]
    if not_readable:
        print(
            f"cp-import-json: omitted {len(not_readable)} not-readable element(s) "
            "(only a CPID, no cpData to import):",
            file=sys.stderr,
        )
        for el in not_readable:
            reason = "prohibited (no read permission)" if el.tag == PROHIBITED_TAG else "failed permission lookup"
            print(f"  {el.path} {reason}: {cpid_text(el.element.get('contents'))}", file=sys.stderr)

    unknown = [el for el in elements if not el.known]
    if unknown:
        print(
            f"cp-import-json: omitted {len(unknown)} element(s) with an unknown tag "
            "(not a known /cpInferno/list tag; this skill may need an update):",
            file=sys.stderr,
        )
        for el in unknown:
            print(f"  {el.path} unknown tag: {el.tag}", file=sys.stderr)

    malformed = [el for el in elements if el.action == "malformed"]
    if malformed:
        print(
            f"cp-import-json: dropped {len(malformed)} malformed element(s) "
            "(no usable {cpId, cpData}; exit status 1):",
            file=sys.stderr,
        )
        for el in malformed:
            cp = element_cp(el.element)
            cp_id = cpid_text(cp.get("cpId")) if isinstance(cp, dict) else "<unparsed>"
            print(f"  {el.path} {el.tag} {cp_id}: {el.reason}", file=sys.stderr)

    # Output exclusivity: a dropped orphan still claims its live output PIDs on the server.
    if include_orphans:
        return
    claimed: dict[int, OrphanInfo] = {}
    for orphan in orphans:
        for pid in orphan.live_pids:
            claimed.setdefault(pid, orphan)
    if not claimed:
        return
    for cp_path, cp_data, _container in collect_cp_entries(import_doc):
        for pid in extract_output_pids(cp_data.get("outputs")):
            if pid in claimed:
                orphan = claimed[pid]
                print(
                    f"cp-import-json: output PID {pid} at {cp_path} is also claimed by omitted "
                    f"orphan {orphan.cp_id} ({orphan.path}); output exclusivity still applies "
                    "until the orphan is repointed or deleted",
                    file=sys.stderr,
                )


def normalize_list_document_status(doc: Any, include_orphans: bool = False) -> tuple[Any, bool]:
    """Normalize a document that may hold cp-list output into an import document.

    Each tagged element is unwrapped to its nested ``{cpId, cpData}`` or dropped, as
    `scan_list_document` describes; one `transform_document` pass then normalises the
    result. Every element that is not a plain readable CP is listed on stderr.

    Returns ``(document, ok)``. ``ok`` is False (normalize exits 1) when a malformed
    element was dropped, or when the root itself was a dropped element (the document
    is then ``[]``).
    """
    import_doc, elements = scan_list_document(doc, include_orphans=include_orphans)
    result = transform_document(import_doc, mode="normalize")
    report_list_elements(elements, result, include_orphans)
    dropped_root = root_dropped(elements)
    if dropped_root:
        print(
            "cp-import-json: the document root is itself a list element that was not kept; "
            "the output is [] (exit status 1)",
            file=sys.stderr,
        )
    malformed = any(el.action == "malformed" for el in elements)
    return result, not (malformed or dropped_root)


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
    # Findings on tagged /cpInferno/list elements keep their own code under --strict.
    tagged_findings: list[ValidationMessage] = []
    orphan_count = 0
    not_readable_count = 0
    unknown_count = 0
    malformed_count = 0
    # Enumerate-only walk: no import document is built, and the orphan details computed
    # during the walk are reused below.
    for el in scan_list_document(doc, build=False)[1]:
        element_path, tag, element = el.path, el.tag, el.element
        if el.action == "malformed":
            malformed_count += 1
            tagged_findings.append(
                ValidationMessage(
                    path=element_path,
                    code="malformed_element",
                    message=(
                        f"{tag} element has {el.reason}; normalize drops it and exits 1 "
                        "(a list element needs both cpId and cpData to be imported)."
                    ),
                )
            )
        elif tag == ORPHANED_TAG:
            orphan_count += 1
            info = el.orphan
            assert info is not None
            tagged_findings.append(
                ValidationMessage(
                    path=element_path,
                    code="orphaned_cp",
                    message=(
                        f"Orphaned control parameter {info.cp_id} {json.dumps(info.name)}: "
                        f"output PID(s) {json.dumps(info.missing_pids)} no longer exist. "
                        "Re-importing it as-is points at PIDs that do not exist; "
                        "repoint (/cpInferno/update) or delete (/cpInferno/delete) it first."
                    ),
                )
            )
        elif tag in NOT_READABLE_TAGS:
            not_readable_count += 1
            reason = "no read permission" if tag == PROHIBITED_TAG else "permission lookup failed"
            tagged_findings.append(
                ValidationMessage(
                    path=element_path,
                    code="not_readable",
                    message=(
                        f"Control parameter {cpid_text(element.get('contents'))} is not readable "
                        f"({tag}: {reason}); it has no cpData and cannot be imported."
                    ),
                )
            )
        elif tag not in LIST_ELEMENT_TAGS:
            unknown_count += 1
            tagged_findings.append(
                ValidationMessage(
                    path=element_path,
                    code="unknown_tag",
                    message=(
                        f"Element with unknown tag {tag!r} in a /cpInferno/list array; it is not one "
                        "of the four known list tags, so normalize omits it (this skill may need an update)."
                    ),
                )
            )

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

    if strict:
        errors.extend(tagged_findings)
    else:
        warnings.extend(tagged_findings)

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
            "orphanedControlParameters": orphan_count,
            "notReadable": not_readable_count,
            "unknownTags": unknown_count,
            "malformedElements": malformed_count,
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


def add_include_orphans_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include-orphans",
        action="store_true",
        help=(
            "Keep OrphanedControlParameterInferno elements (CPs whose output PID was deleted); "
            "by default they are omitted and listed on stderr"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Control-parameter import JSON formatter, expander, and validator."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    normalize = sub.add_parser("normalize", help="Convert CP JSON to friendly format")
    add_io_args(normalize)
    add_include_orphans_arg(normalize)

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
    add_include_orphans_arg(fetch_normalize)

    return parser


def handle_transform(
    command: str,
    input_path: str | None,
    output_path: str | None,
    pretty: bool,
    include_orphans: bool = False,
) -> int:
    doc = read_json(input_path)
    ok = True
    if command == "normalize":
        result, ok = normalize_list_document_status(doc, include_orphans=include_orphans)
    else:
        result = transform_document(doc, mode=command)
    write_json(result, output_path, pretty=pretty)
    return 0 if ok else 1


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
    include_orphans: bool = False,
) -> int:
    if len(lumberjack_ids) == 1:
        raw = fetch_control_parameters(access_token, lumberjack_ids[0])
    else:
        raw = {
            str(lumberjack_id): fetch_control_parameters(access_token, lumberjack_id)
            for lumberjack_id in lumberjack_ids
        }

    normalized, ok = normalize_list_document_status(raw, include_orphans=include_orphans)
    write_json(normalized, output_path, pretty=pretty)
    return 0 if ok else 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "normalize":
        code = handle_transform("normalize", args.input, args.output, args.pretty, args.include_orphans)
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
            include_orphans=args.include_orphans,
        )

    sys.exit(code)


if __name__ == "__main__":
    main()
