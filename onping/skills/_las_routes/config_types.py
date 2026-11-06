"""`ConfigType`: parse, validate, coerce from the command line, render, mask.

The wire form (`lumberjack-packages-config-types`, `Lumberjack/Package/Config/Types.hs`):

    {"tag": "CURL" | "CPort" | "CInteger" | "CBool" | "CText" | "CPassword" | "CFloat"}
    {"tag": "CMaybe", "contents": <ConfigType>}
    {"tag": "CList",  "contents": <ConfigType>}

The validation rules follow the package-side `FromJSON` decoders, so a value
accepted here is one the package can parse when it restarts. Two rules are
stricter on purpose: `CPort` must be 0-65535 (the OnPing UI's range; the decoder
is a bounded Int) and `CURL` must contain no whitespace (the decoder takes any
text). A type with any other tag is UNKNOWN: it is kept verbatim in a schema,
but no value is valid for it, so it can never be set.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

SCALARS = ("CURL", "CPort", "CInteger", "CBool", "CText", "CPassword", "CFloat")
WRAPPERS = ("CMaybe", "CList")
MASK = "********"
PORT_MAX = 65535

_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def is_known(t: Any) -> bool:
    if not isinstance(t, dict):
        return False
    tag = t.get("tag")
    if tag in SCALARS:
        return True
    if tag in WRAPPERS:
        return is_known(t.get("contents"))
    return False


def type_name(t: Any) -> str:
    """`CInteger`, `CMaybe CText`, `CList (CMaybe CPort)`; unknown -> `unknown <json>`."""
    if not isinstance(t, dict) or "tag" not in t:
        return f"unknown {json.dumps(t, sort_keys=True)}"
    tag = t["tag"]
    if tag in SCALARS:
        return tag
    if tag in WRAPPERS and is_known(t.get("contents")):
        inner = type_name(t["contents"])
        return f"{tag} ({inner})" if " " in inner else f"{tag} {inner}"
    return f"unknown {json.dumps(t, sort_keys=True)}"


def has_password(t: Any) -> bool:
    if not isinstance(t, dict):
        return False
    if t.get("tag") == "CPassword":
        return True
    if t.get("tag") in WRAPPERS:
        return has_password(t.get("contents"))
    return False


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate(t: Any, v: Any, where: str = "value") -> list[str]:
    """Every reason `v` does not fit `t` (empty list = valid)."""
    if not is_known(t):
        return [f"{where}: the stored type {type_name(t)} is not one this skill knows; "
                "it cannot be set"]
    tag = t["tag"]
    if tag == "CInteger":
        return [] if _is_int(v) else [f"{where}: expected an integer, got {_show(v)}"]
    if tag == "CPort":
        if not _is_int(v):
            return [f"{where}: expected a port number (integer 0-{PORT_MAX}), got {_show(v)}"]
        if not 0 <= v <= PORT_MAX:
            return [f"{where}: port {v} is outside the range 0-{PORT_MAX}"]
        return []
    if tag == "CFloat":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return [f"{where}: expected a number, got {_show(v)}"]
        if isinstance(v, float) and not math.isfinite(v):
            return [f"{where}: expected a finite number, got {v}"]
        return []
    if tag == "CBool":
        return [] if isinstance(v, bool) else [f"{where}: expected true or false, got {_show(v)}"]
    if tag in ("CText", "CPassword"):
        if isinstance(v, str):
            return []
        hint = ""
        if isinstance(v, (bool, int, float)) or v is None:
            hint = " (in YAML, quote it to keep it as text)"
        return [f"{where}: expected text, got {_show(v, tag)}{hint}"]
    if tag == "CURL":
        if not isinstance(v, str):
            return [f"{where}: expected a URL string, got {_show(v)}"]
        if re.search(r"\s", v):
            return [f"{where}: a URL must not contain whitespace"]
        return []
    if tag == "CMaybe":
        return [] if v is None else validate(t["contents"], v, where)
    if tag == "CList":
        if not isinstance(v, list):
            return [f"{where}: expected a JSON array, got {_show(v)}"]
        errs: list[str] = []
        for i, item in enumerate(v):
            errs += validate(t["contents"], item, f"{where}[{i}]")
        return errs
    return [f"{where}: unhandled type {type_name(t)}"]  # pragma: no cover


def _show(v: Any, tag: str | None = None) -> str:
    if tag == "CPassword":
        return type(v).__name__
    try:
        text = json.dumps(v)
    except (TypeError, ValueError):
        return f"a {type(v).__name__} ({v!r})"[:80]
    return text if len(text) <= 60 else text[:57] + "..."


def from_cli(t: Any, text: str) -> Any:
    """Turn the text after `KEY=` into a value of type `t`. Raises ValueError."""
    if not is_known(t):
        raise ValueError(f"the stored type {type_name(t)} is not one this skill knows")
    tag = t["tag"]
    if tag in ("CInteger", "CPort"):
        if not _INT.match(text.strip()):
            raise ValueError(f"expected an integer, got {text!r}")
        return int(text.strip())
    if tag == "CFloat":
        s = text.strip()
        if _INT.match(s):
            return int(s)
        if not _FLOAT.match(s):
            raise ValueError(f"expected a number, got {text!r}")
        f = float(s)
        if not math.isfinite(f):
            raise ValueError(f"expected a finite number, got {text!r}")
        return f
    if tag == "CBool":
        s = text.strip().lower()
        if s in ("true", "false"):
            return s == "true"
        raise ValueError(f"expected true or false, got {text!r}")
    if tag in ("CText", "CPassword", "CURL"):
        return text
    if tag == "CMaybe":
        return None if text.strip() == "null" else from_cli(t["contents"], text)
    if tag == "CList":
        try:
            v = json.loads(text)
        except ValueError as e:
            raise ValueError(f"expected a JSON array, got {text!r}") from e
        if not isinstance(v, list):
            raise ValueError(f"expected a JSON array, got {text!r}")
        return v
    raise ValueError(f"unhandled type {type_name(t)}")  # pragma: no cover


def mask(t: Any, v: Any) -> Any:
    """`v` with every CPassword string replaced by MASK (null stays null)."""
    if not isinstance(t, dict):
        return v
    tag = t.get("tag")
    if tag == "CPassword":
        return MASK if v is not None else None
    if tag == "CMaybe":
        return None if v is None else mask(t.get("contents"), v)
    if tag == "CList" and isinstance(v, list):
        return [mask(t.get("contents"), x) for x in v]
    return v


def render(t: Any, v: Any, show_secrets: bool = False) -> str:
    """Display form: JSON text, with CPassword values masked unless show_secrets."""
    shown = v if show_secrets else mask(t, v)
    return json.dumps(shown, ensure_ascii=False)


def same_value(a: Any, b: Any) -> bool:
    """JSON equality that keeps booleans apart from numbers (Python's 1 == True)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_value(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b
