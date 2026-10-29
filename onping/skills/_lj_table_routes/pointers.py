"""PID / VPID pointers in their three encodings, plus the shared tag selectors.

  - data-table cell text (`parsePointerFromText` / `pointerToText` in
    onping-datatable-types): "1234" is PID 1234, "4321 VPID" is VPID 4321.
    Anything else is rejected with "Invalid PID or VPID format for: ...".
  - log-table column key (the `OnpingKey` JSON instances in onping-tag-types):
    a bare integer is a PID; `{"keyType": "VPID", "keyValue": 4321}` is a VPID.
  - CLI: `--pid N` / `--vpid N`.

PID and VPID numbering are separate, so VPID 1234 is NOT PID 1234.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TEXT_SELECTOR = "TextTagSelector"
INVALID_SELECTOR = "InvalidTagSelector"
EVENT_SELECTOR = "LastUpdateDateTimeTagSelector"

# Every TagSelector constructor (onping-datatable-types), in UI order.
SELECTORS = (
    "TextTagSelector",
    "PIDTagSelector",
    "ResultTagSelector",
    "UnitTagSelector",
    "DescriptionTagSelector",
    "LastUpdateDateTimeTagSelector",
    "LastUpdateDateTagSelector",
    "LastUpdateTimeTagSelector",
    "WriteabilityTagSelector",
    "CompanyTagSelector",
    "CompanyIdTagSelector",
    "SiteTagSelector",
    "SiteIdTagSelector",
    "LocationTagSelector",
    "LocationIdTagSelector",
    "InvalidTagSelector",
)
# Log tables cannot hold Text or Invalid columns (asProjection drops them).
LOGTABLE_SELECTORS = tuple(s for s in SELECTORS if s not in (TEXT_SELECTOR, INVALID_SELECTOR))
# Selectors a user may put on a new data-table column.
DATATABLE_SELECTORS = tuple(s for s in SELECTORS if s != INVALID_SELECTOR)

_CELL = re.compile(r"\A([0-9]+)( VPID)?\Z")


@dataclass(frozen=True)
class Pointer:
    kind: str  # "PID" or "VPID"
    value: int

    def __str__(self) -> str:
        return f"{self.kind} {self.value}"


def normalize_selector(name: str) -> str:
    """Accept `Result`, `result`, or `ResultTagSelector`; return the constructor name."""
    want = name.strip().lower()
    for sel in SELECTORS:
        if want in (sel.lower(), sel.lower().removesuffix("tagselector")):
            return sel
    raise ValueError(f"unknown selector {name!r}; choose one of: "
                     + ", ".join(s.removesuffix("TagSelector") for s in SELECTORS))


def parse_cell(text: str) -> Pointer:
    """Parse data-table cell text exactly as the server's `parsePointerFromText` does."""
    m = _CELL.match(text)
    if not m:
        raise ValueError(f"Invalid PID or VPID format for: {text}")
    return Pointer("VPID" if m.group(2) else "PID", int(m.group(1)))


def try_parse_cell(text: Any) -> Pointer | None:
    if not isinstance(text, str):
        return None
    try:
        return parse_cell(text)
    except ValueError:
        return None


def render_cell(p: Pointer) -> str:
    return f"{p.value} VPID" if p.kind == "VPID" else str(p.value)


def parse_key(raw: Any) -> Pointer:
    """Parse a log-table `columnSchemaKey` / `schemaHeaderEventSource`."""
    if isinstance(raw, bool):
        raise ValueError(f"not an OnpingKey: {raw!r}")
    if isinstance(raw, int):
        return Pointer("PID", raw)
    if isinstance(raw, dict) and raw.get("keyType") in ("PID", "VPID"):
        return Pointer(raw["keyType"], int(raw["keyValue"]))
    raise ValueError(f"not an OnpingKey: {raw!r}")


def render_key(p: Pointer) -> Any:
    return p.value if p.kind == "PID" else {"keyType": "VPID", "keyValue": p.value}


def from_cli(pid: int | None = None, vpid: int | None = None) -> Pointer | None:
    if pid is not None and vpid is not None:
        raise ValueError("give --pid or --vpid, not both")
    if pid is not None:
        return Pointer("PID", pid)
    if vpid is not None:
        return Pointer("VPID", vpid)
    return None
