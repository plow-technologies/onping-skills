"""The ownership guard for the generic-SWD skills.

Reads: the kiosk must be listed by kiosk/configs for the caller's own owned
and member groups, and its group must be one of them.

Writes: the caller must own the kiosk's group. Every PID a write adds or
changes must pass OnPing's PID-write rule (onping-core Writes.hs,
writeOnpingParameterWithAuth): the lister returns it, its location has
exactly one permission group among the groups the caller can see, and the
caller owns that group. A changed write PID must also be TagWriteable.

The server checks group access on each kiosk route too (HTTP 403). This guard
runs first and is stricter for writes: it needs ownership, not membership.

Every read here fails closed: a failed or odd answer raises Refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import routes


class Refused(Exception):
    """The guard refuses; nothing was written."""


@dataclass
class Caller:
    owned: dict[str, str | None]
    member: dict[str, str | None]

    @property
    def visible(self) -> list[str]:
        return list(dict.fromkeys([*self.owned, *self.member]))

    def name(self, gid: str) -> str | None:
        return self.owned.get(gid) or self.member.get(gid)


@dataclass
class Kiosk:
    uuid: str
    name: Any
    group_id: str
    ip: Any
    port: Any
    owned: bool
    raw: dict = field(repr=False, default_factory=dict)

    def doc(self, caller: Caller) -> dict:
        return {"uuid": self.uuid, "name": self.name, "group_id": self.group_id,
                "group_name": caller.name(self.group_id), "owned": self.owned,
                "ip": self.ip, "port": self.port}


def caller(token: str) -> Caller:
    try:
        owned = routes.owned_groups(token)
    except routes.RouteFailure as exc:
        raise Refused(f"could not read your owned groups ({exc}); the guard fails closed") from exc
    try:
        member = routes.member_groups(token)
    except routes.RouteFailure as exc:
        raise Refused(f"could not read your member groups ({exc}); the guard fails closed") from exc
    return Caller(owned, member)


def to_kiosk(raw: dict, who: Caller) -> Kiosk | None:
    uuid = (raw.get("kioskUUID") or {}).get("unKioskUUID") if isinstance(raw.get("kioskUUID"), dict) else None
    gid = raw.get("kioskGroupId")
    if not isinstance(uuid, str) or not isinstance(gid, str):
        return None
    return Kiosk(uuid=uuid, name=raw.get("kioskName"), group_id=gid, ip=raw.get("kioskIP"),
                 port=raw.get("kioskPort"), owned=gid in who.owned, raw=raw)


def list_kiosks(token: str, who: Caller, groups: list[str] | None = None) -> list[Kiosk]:
    """The kiosks in the given groups (default: every group the caller can see).

    A group the caller neither owns nor belongs to is refused before any request.
    """
    visible = who.visible
    if groups:
        foreign = [g for g in groups if g not in visible]
        if foreign:
            raise Refused(f"you neither own nor belong to group(s) {', '.join(foreign)}")
        ask = list(dict.fromkeys(groups))
    else:
        ask = visible
    if not ask:
        return []
    raw = routes.kiosks(token, ask)
    out = []
    for item in raw:
        k = to_kiosk(item, who)
        if k is not None and k.group_id in ask:
            out.append(k)
    return out


def find_kiosk(token: str, who: Caller, uuid: str, *, write: bool) -> Kiosk:
    """The kiosk with this UUID, if the caller may read (or, with write, change) it."""
    try:
        listed = list_kiosks(token, who)
    except routes.RouteFailure as exc:
        raise Refused(f"could not list your kiosks ({exc}); the guard fails closed") from exc
    matches = [k for k in listed if k.uuid.lower() == uuid.lower()]
    if not matches:
        raise Refused(f"kiosk {uuid} is not in any group you own or belong to")
    if len(matches) > 1 and len({k.group_id for k in matches}) > 1:
        raise Refused(f"kiosk {uuid} is listed under more than one group; refusing")
    kiosk = matches[0]
    if write and not kiosk.owned:
        raise Refused(f"you do not own group {kiosk.group_id} ({who.name(kiosk.group_id)}) of kiosk {uuid}; "
                      f"changing a kiosk needs ownership of its group")
    return kiosk


def pid_report(token: str, who: Caller, model: dict, touched: dict[int, dict]) -> tuple[dict[int, dict], list[str], list[str]]:
    """Look up every lane PID; apply the PID-write rule to the touched ones.

    Returns (entries by PID, problems that refuse the write, warnings).
    """
    pids = sorted({ln["read_pid"] for ln in model["lanes"]} | {ln["write_pid"] for ln in model["lanes"]})
    try:
        listed = routes.lister(token, pids)
    except routes.RouteFailure as exc:
        raise Refused(f"could not look up the lane PIDs ({exc}); the guard fails closed") from exc

    checks: list[tuple[int, str, int]] = []  # (lane, role, pid) that must pass
    for ln in model["lanes"]:
        t = touched.get(ln["number"])
        if t and t.get("read"):
            checks.append((ln["number"], "read", ln["read_pid"]))
        if t and t.get("write"):
            checks.append((ln["number"], "write", ln["write_pid"]))
    must = {pid for _, _, pid in checks}

    refs = {listed[p].get("location_id") for p in must if listed.get(p, {}).get("found")}
    refs = {r for r in refs if isinstance(r, int) and not isinstance(r, bool)}
    by_location: dict[int, list[str]] = {}
    if refs:
        try:
            by_location = routes.location_groups(token, who.visible, refs)
        except routes.RouteFailure as exc:
            raise Refused(f"could not read the PIDs' location groups ({exc}); the guard fails closed") from exc

    problems: list[str] = []
    warnings: list[str] = []
    for ln in model["lanes"]:
        for role, key in (("read", "read_pid"), ("write", "write_pid")):
            pid = ln[key]
            entry = listed.get(pid, {})
            tag = f"lane {ln['number']} {role} PID {pid}"
            enforce = (ln["number"], role, pid) in checks
            found = bool(entry.get("found"))

            def note(msg: str) -> None:
                if enforce:
                    problems.append(msg)
                else:
                    warnings.append(f"{msg} (unchanged by this edit)")

            if not found:
                note(f"{tag}: not returned by the parameter lister (it does not exist, or you cannot see it)")
                continue
            if role == "write" and entry.get("writeability") != "TagWriteable":
                note(f"{tag}: is not writeable ({entry.get('writeability')})")
            if not enforce:
                continue
            ref = entry.get("location_id")
            gids = by_location.get(ref, []) if ref in refs else []
            entry["location_groups"] = gids
            if not gids:
                problems.append(f"{tag}: location {ref} has no permission group you can see; "
                                f"OnPing's PID-write rule needs exactly one")
            elif len(gids) > 1:
                problems.append(f"{tag}: location {ref} is in {len(gids)} groups; "
                                f"OnPing's PID-write rule needs exactly one")
            elif gids[0] not in who.owned:
                problems.append(f"{tag}: you do not own group {gids[0]} ({who.name(gids[0])}) of location {ref}")
    return listed, problems, warnings
