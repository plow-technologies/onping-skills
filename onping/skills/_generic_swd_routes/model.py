"""The generic-SWD configuration model: decode, validate, edit, diff, back up.

A configuration is reduced to the fields the edge stores
(the kiosk server configuration type):

  {"name": str,
   "lanes": [{"number": int, "read_pid": int, "script": str,
              "write_pid": int, "wait": float}],
   "status_map": [[float, status], ...]}

where a status is "Available", "WaitingToStart", "Pumping" or
{"disabled": message}. The enrichment that kiosk/config adds (PID
descriptions, raw and masked values, the read status) is kept apart, in
`enrichment()`, and is never compared or sent.

Validation mirrors the decoder (FrontendKioskServerConfig, LaneStatus,
Word64 lane numbers) and adds what the edge needs to run an offload. The
bounds marked "choice" are this skill's, not the server's.
"""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

FORMAT = "onping-generic-swd-config/1"
PLAIN_STATUSES = ("Available", "WaitingToStart", "Pumping")
REQUIRED_STATUSES = PLAIN_STATUSES  # the edge's offload polls for each in turn
MAX_NAME = 200  # choice
MAX_MESSAGE = 200  # choice
MAX_SCRIPT = 4096  # choice
MAX_LANE = 2**64 - 1  # Word64
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
OUTPUT_RE = re.compile(r"\boutput\s*:=")


class ModelError(Exception):
    """A configuration or an edit that cannot be applied."""


# ─────────────────────────────── helpers ───────────────────────────────


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) and math.isfinite(float(v))


def _controls(text: str, allowed: str = "") -> bool:
    return any((ord(ch) < 32 and ch not in allowed) or ord(ch) == 127 for ch in text)


def status_text(status: Any) -> str:
    if isinstance(status, dict):
        return f"Disabled({status.get('disabled')!r})"
    return str(status)


def num_text(v: float) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def valid_uuid(text: str) -> bool:
    return bool(UUID_RE.match(text or ""))


# ─────────────────────────────── decode / encode ───────────────────────────────


def _pid_of(param: Any, where: str) -> int:
    if not isinstance(param, dict) or not _is_int(param.get("laneParamPID")):
        raise ModelError(f"{where}: missing an integer laneParamPID")
    return param["laneParamPID"]


def from_wire(cfg: Any) -> dict:
    """FrontendKioskServerConfig -> the model. ModelError on a shape that cannot decode."""
    if not isinstance(cfg, dict):
        raise ModelError("the configuration is not a JSON object")
    for key in ("frontendConfigName", "frontendConfigLanes", "frontendConfigStatusMap"):
        if key not in cfg:
            raise ModelError(f"the configuration has no {key}")
    lanes_in = cfg["frontendConfigLanes"]
    smap_in = cfg["frontendConfigStatusMap"]
    if not isinstance(lanes_in, list):
        raise ModelError("frontendConfigLanes is not a list")
    if not isinstance(smap_in, list):
        raise ModelError("frontendConfigStatusMap is not a list")
    lanes = []
    for i, ln in enumerate(lanes_in):
        where = f"lane entry {i + 1}"
        if not isinstance(ln, dict):
            raise ModelError(f"{where} is not an object")
        lanes.append({
            "number": ln.get("frontendLaneNumber"),
            "read_pid": _pid_of(ln.get("frontendLaneReadPID"), f"{where} read PID"),
            "script": ln.get("frontendLaneReadMaskScript"),
            "write_pid": _pid_of(ln.get("frontendLaneWritePID"), f"{where} write PID"),
            "wait": ln.get("frontendLaneWriteWaitingToStartVal"),
        })
    smap = []
    for i, pair in enumerate(smap_in):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ModelError(f"status map entry {i + 1} is not a [value, status] pair")
        smap.append([pair[0], pair[1]])
    return {"name": cfg["frontendConfigName"], "lanes": lanes, "status_map": smap}


def _param(pid: int) -> dict:
    return {"laneParamPID": pid, "laneParamName": None, "laneParamRawValue": None,
            "laneParamMaskedValue": None, "laneParamStatus": None}


def to_wire(model: dict) -> dict:
    """The model -> FrontendKioskServerConfig, every LaneParamConfig field present."""
    lanes = sorted(model["lanes"], key=lambda ln: ln["number"])
    return {
        "frontendConfigName": model["name"],
        "frontendConfigLanes": [
            {"frontendLaneNumber": ln["number"],
             "frontendLaneReadPID": _param(ln["read_pid"]),
             "frontendLaneReadMaskScript": ln["script"],
             "frontendLaneWritePID": _param(ln["write_pid"]),
             "frontendLaneWriteWaitingToStartVal": float(ln["wait"])}
            for ln in lanes
        ],
        "frontendConfigStatusMap": [[float(v), copy.deepcopy(s)]
                                    for v, s in sorted(model["status_map"], key=lambda p: float(p[0]))],
    }


def enrichment(cfg: dict) -> dict[int, dict]:
    """{lane number: {read: LaneParamConfig, write: LaneParamConfig}} as kiosk/config reported them."""
    out: dict[int, dict] = {}
    for ln in cfg.get("frontendConfigLanes") or []:
        if isinstance(ln, dict) and _is_int(ln.get("frontendLaneNumber")):
            out[ln["frontendLaneNumber"]] = {"read": ln.get("frontendLaneReadPID") or {},
                                             "write": ln.get("frontendLaneWritePID") or {}}
    return out


def canonical(model: dict) -> str:
    """A comparable form: lanes by number, the status map by value, numbers as floats."""
    return json.dumps(to_wire(model), sort_keys=True)


# ─────────────────────────────── validation ───────────────────────────────


def script_problems(script: str) -> list[str]:
    """Shape checks for a mask script. The grammar itself is not checked here."""
    if script == "":
        return []
    out = []
    if len(script) > MAX_SCRIPT:
        out.append(f"is {len(script)} characters; the limit is {MAX_SCRIPT}")
    if _controls(script, "\n\t"):
        out.append("contains a control character other than newline or tab")
    depth, in_str, esc, unbalanced = 0, False, False, False
    for ch in script:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                unbalanced = True
    if in_str:
        out.append("has an unterminated string literal")
    if unbalanced or depth != 0:
        out.append("has unbalanced parentheses")
    if not OUTPUT_RE.search(script):
        out.append("never assigns output (the edge reads the result from `output := ...`)")
    return out


def status_problems(status: Any) -> list[str]:
    if isinstance(status, str):
        return [] if status in PLAIN_STATUSES else [
            f"status {status!r} is not Available, WaitingToStart, Pumping or {{\"disabled\": message}}"]
    if isinstance(status, dict) and set(status) == {"disabled"}:
        msg = status["disabled"]
        if not isinstance(msg, str) or not msg.strip():
            return ["a disabled status needs a non-blank message"]
        out = []
        if len(msg) > MAX_MESSAGE:
            out.append(f"a disabled message is {len(msg)} characters; the limit is {MAX_MESSAGE}")
        if _controls(msg):
            out.append("a disabled message contains a control character")
        return out
    return [f"status {json.dumps(status)} is not Available, WaitingToStart, Pumping or {{\"disabled\": message}}"]


def validate(model: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a whole configuration."""
    errors: list[str] = []
    warnings: list[str] = []
    name = model.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name: must be a non-blank string")
    else:
        if len(name) > MAX_NAME:
            errors.append(f"name: {len(name)} characters; the limit is {MAX_NAME}")
        if _controls(name):
            errors.append("name: contains a control character")

    lanes = model.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        errors.append("lanes: a kiosk needs at least one lane")
        lanes = lanes if isinstance(lanes, list) else []
    seen: set[int] = set()
    for i, ln in enumerate(lanes):
        num = ln.get("number")
        tag = f"lane {num}" if _is_int(num) else f"lane entry {i + 1}"
        if not _is_int(num) or not (0 <= num <= MAX_LANE):
            errors.append(f"{tag}: the lane number must be an integer from 0 to {MAX_LANE}")
        elif num in seen:
            errors.append(f"{tag}: the lane number is used twice")
        else:
            seen.add(num)
        for key, label in (("read_pid", "read PID"), ("write_pid", "write PID")):
            pid = ln.get(key)
            if not _is_int(pid) or pid <= 0:
                errors.append(f"{tag}: the {label} must be a positive integer")
        if _is_int(ln.get("read_pid")) and ln.get("read_pid") == ln.get("write_pid"):
            warnings.append(f"{tag}: the read PID and the write PID are the same PID")
        if not _is_num(ln.get("wait")):
            errors.append(f"{tag}: the waiting-to-start value must be a finite number")
        script = ln.get("script")
        if not isinstance(script, str):
            errors.append(f"{tag}: the mask script must be a string (empty for none)")
        else:
            errors.extend(f"{tag}: the mask script {p}" for p in script_problems(script))

    smap = model.get("status_map")
    if not isinstance(smap, list):
        errors.append("status map: must be a list of [value, status] pairs")
        smap = []
    values: set[float] = set()
    present: set[str] = set()
    for pair in smap:
        v, s = pair
        if not _is_num(v):
            errors.append(f"status map: the value {json.dumps(v)} is not a finite number")
        elif float(v) in values:
            errors.append(f"status map: the value {num_text(v)} appears twice "
                          f"(the server would keep only the last)")
        else:
            values.add(float(v))
        probs = status_problems(s)
        where = f"status map {num_text(v)}" if _is_num(v) else "status map"
        errors.extend(f"{where}: {p}" for p in probs)
        if not probs:
            present.add(s if isinstance(s, str) else "Disabled")
    for need in REQUIRED_STATUSES:
        if need not in present:
            errors.append(f"status map: no value maps to {need}; the offload needs Available, "
                          f"WaitingToStart and Pumping")
    return errors, warnings


# ─────────────────────────────── edits ───────────────────────────────


def _lane(model: dict, number: int) -> dict | None:
    for ln in model["lanes"]:
        if ln["number"] == number:
            return ln
    return None


def name_set(model: dict, name: str) -> dict:
    new = copy.deepcopy(model)
    new["name"] = name
    return new


def lane_set(model: dict, number: int, *, read_pid: int | None = None, write_pid: int | None = None,
             script: str | None = None, wait: float | None = None) -> dict:
    new = copy.deepcopy(model)
    ln = _lane(new, number)
    if ln is None:
        raise ModelError(f"lane {number} does not exist; use lane-add")
    if read_pid is not None:
        ln["read_pid"] = read_pid
    if write_pid is not None:
        ln["write_pid"] = write_pid
    if script is not None:
        ln["script"] = script
    if wait is not None:
        ln["wait"] = wait
    return new


def lane_add(model: dict, number: int, read_pid: int, write_pid: int, wait: float, script: str = "") -> dict:
    new = copy.deepcopy(model)
    if _lane(new, number) is not None:
        raise ModelError(f"lane {number} already exists; use lane-set")
    new["lanes"].append({"number": number, "read_pid": read_pid, "script": script,
                         "write_pid": write_pid, "wait": wait})
    return new


def lane_delete(model: dict, number: int) -> dict:
    new = copy.deepcopy(model)
    if _lane(new, number) is None:
        raise ModelError(f"lane {number} does not exist")
    new["lanes"] = [ln for ln in new["lanes"] if ln["number"] != number]
    return new


def status_set(model: dict, value: float, status: Any) -> dict:
    new = copy.deepcopy(model)
    new["status_map"] = [p for p in new["status_map"] if not (_is_num(p[0]) and float(p[0]) == float(value))]
    new["status_map"].append([value, status])
    return new


def status_delete(model: dict, value: float) -> dict:
    new = copy.deepcopy(model)
    kept = [p for p in new["status_map"] if not (_is_num(p[0]) and float(p[0]) == float(value))]
    if len(kept) == len(new["status_map"]):
        raise ModelError(f"the status map has no value {num_text(value)}")
    new["status_map"] = kept
    return new


# ─────────────────────────────── diff ───────────────────────────────


def touched(old: dict, new: dict) -> dict[int, dict]:
    """{lane number: {"new": bool, "read": bool, "write": bool, "script": bool}} for lanes the edit adds or changes."""
    before = {ln["number"]: ln for ln in old["lanes"]}
    out: dict[int, dict] = {}
    for ln in new["lanes"]:
        prev = before.get(ln["number"])
        if prev is None:
            out[ln["number"]] = {"new": True, "read": True, "write": True, "script": True}
            continue
        flags = {"new": False,
                 "read": prev["read_pid"] != ln["read_pid"],
                 "write": prev["write_pid"] != ln["write_pid"],
                 "script": prev["script"] != ln["script"],
                 "wait": float(prev["wait"]) != float(ln["wait"])}
        if any(flags.values()):
            out[ln["number"]] = flags
    return out


def _lane_text(ln: dict) -> str:
    return (f"read PID {ln['read_pid']}, write PID {ln['write_pid']}, "
            f"waiting-to-start {num_text(ln['wait'])}, script {json.dumps(ln['script'])}")


def diff(old: dict, new: dict) -> list[str]:
    lines: list[str] = []
    if old["name"] != new["name"]:
        lines.append(f"name: {json.dumps(old['name'])} -> {json.dumps(new['name'])}")
    before = {ln["number"]: ln for ln in old["lanes"]}
    after = {ln["number"]: ln for ln in new["lanes"]}
    for num in sorted(set(before) | set(after)):
        a, b = before.get(num), after.get(num)
        if a is None:
            lines.append(f"+ lane {num}: {_lane_text(b)}")
        elif b is None:
            lines.append(f"- lane {num}: {_lane_text(a)}")
        else:
            for key, label in (("read_pid", "read PID"), ("write_pid", "write PID")):
                if a[key] != b[key]:
                    lines.append(f"lane {num} {label}: {a[key]} -> {b[key]}")
            if a["script"] != b["script"]:
                lines.append(f"lane {num} script: {json.dumps(a['script'])} -> {json.dumps(b['script'])}")
            if float(a["wait"]) != float(b["wait"]):
                lines.append(f"lane {num} waiting-to-start: {num_text(a['wait'])} -> {num_text(b['wait'])}")
    sm_a = {float(v): s for v, s in old["status_map"] if _is_num(v)}
    sm_b = {float(v): s for v, s in new["status_map"] if _is_num(v)}
    for v in sorted(set(sm_a) | set(sm_b)):
        a, b = sm_a.get(v), sm_b.get(v)
        if a is None:
            lines.append(f"+ status {num_text(v)}: {status_text(b)}")
        elif b is None:
            lines.append(f"- status {num_text(v)}: {status_text(a)}")
        elif a != b:
            lines.append(f"status {num_text(v)}: {status_text(a)} -> {status_text(b)}")
    return lines


# ─────────────────────────────── backups ───────────────────────────────


def backup_doc(kiosk: dict, model: dict, captured_at: str) -> dict:
    return {
        "format": FORMAT,
        "kiosk_uuid": kiosk["uuid"],
        "kiosk_group_id": kiosk["group_id"],
        "captured_at": captured_at,
        "config": to_wire(model),
    }


def read_config_file(text: str, uuid: str) -> dict:
    """A backup document or a bare FrontendKioskServerConfig -> the model. ModelError if unusable."""
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ModelError(f"the file is not JSON: {exc}") from exc
    if isinstance(doc, dict) and "format" in doc:
        if doc.get("format") != FORMAT:
            raise ModelError(f"the file's format is {doc.get('format')!r}, not {FORMAT!r}")
        if doc.get("kiosk_uuid") != uuid:
            raise ModelError(f"the file is for kiosk {doc.get('kiosk_uuid')}, not {uuid}")
        doc = doc.get("config")
    return from_wire(doc)
