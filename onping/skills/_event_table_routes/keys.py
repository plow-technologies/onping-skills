"""OnpingKey parsing and the flat bindings view of an EventTableConfiguration.

JSON key encoding (the `OnpingKey` JSON instances in onping-tag-types):
  - a bare integer is a PID: `500001`
  - an object carries its own type: `{"keyType": "PID" | "VPID", "keyValue": N}`

PID and VPID numbering are separate, so a VPID 500001 is NOT PID 500001.

The trigger column is the column whose `eventColumnIndex` equals
`eventTableEventColumn` — NOT the column at list position 0
(`fetchEventTable` in the onping-core event-table data source).

`eventTableMaxEvents` is `{"tag": "FixedMaxEvents", "contents": N}` or
`{"tag": "DynamicMaxEvents", "contents": <OnpingKey>}`; the JSON decoder also
accepts a bare number for FixedMaxEvents. DynamicMaxEvents is a second place a
table can read a PID.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Key:
    kind: str  # "PID" or "VPID"
    value: int

    def __str__(self) -> str:
        return f"{self.kind} {self.value}"


def parse_key(raw: Any) -> Key:
    if isinstance(raw, bool):
        raise ValueError(f"not an OnpingKey: {raw!r}")
    if isinstance(raw, int):
        return Key("PID", raw)
    if isinstance(raw, dict) and raw.get("keyType") in ("PID", "VPID"):
        return Key(raw["keyType"], int(raw["keyValue"]))
    raise ValueError(f"not an OnpingKey: {raw!r}")


@dataclass(frozen=True)
class Binding:
    where: str  # "column" or "maxEvents"
    index: int | None
    name: str
    key: Key
    trigger: bool


def max_events(config: dict) -> tuple[str, Key | int | None]:
    """Return ("Fixed", N), ("Dynamic", Key), or ("Unknown", None)."""
    raw = config.get("eventTableMaxEvents")
    if isinstance(raw, int) and not isinstance(raw, bool):
        return "Fixed", raw
    if isinstance(raw, dict):
        if raw.get("tag") == "FixedMaxEvents":
            return "Fixed", raw.get("contents")
        if raw.get("tag") == "DynamicMaxEvents":
            return "Dynamic", parse_key(raw.get("contents"))
    return "Unknown", None


def bindings(config: dict) -> list[Binding]:
    """Every key the table reads: each column, then a DynamicMaxEvents key."""
    trigger_index = config.get("eventTableEventColumn")
    out = [
        Binding(
            where="column",
            index=col.get("eventColumnIndex"),
            name=col.get("eventColumnName", ""),
            key=parse_key(col.get("eventColumnKey")),
            trigger=col.get("eventColumnIndex") == trigger_index,
        )
        for col in config.get("eventTableParams", [])
    ]
    kind, value = max_events(config)
    if kind == "Dynamic":
        out.append(Binding("maxEvents", None, "row count (DynamicMaxEvents)", value, False))
    return out


def pid_matches(config: dict, pid: int) -> tuple[list[Binding], list[Binding]]:
    """Return (bindings that read PID `pid`, bindings that read VPID `pid`)."""
    found = bindings(config)
    return (
        [b for b in found if b.key == Key("PID", pid)],
        [b for b in found if b.key == Key("VPID", pid)],
    )


def describe(b: Binding) -> str:
    if b.where == "maxEvents":
        return f"{b.name} reads {b.key}"
    trigger = " (trigger)" if b.trigger else ""
    return f"column {b.index} {b.name!r}{trigger} reads {b.key}"
