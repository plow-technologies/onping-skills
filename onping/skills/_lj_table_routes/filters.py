"""FilterRule helpers shared by data tables and log tables.

Both table kinds use the same `FilterRule` JSON (onping-datatable-types):
  - `{"tag": "SingleFilterRule", "contents": {"singleFilterColumnRef": uuid, ...}}`
  - `{"tag": "GroupFilterRule", "contents": {"groupFilterSubFilters": [SingleFilter, ...], ...}}`
  - a legacy flat form carrying `filterRuleColumnRef` at the top level.

A column delete must not leave a filter pointing at a column that no longer
exists, so callers ask which columns a rule references and, with
`--drop-filters`, strip those references.
"""

from __future__ import annotations

from typing import Any


def column_refs(node: Any) -> set[str]:
    """Every column UUID referenced anywhere in a rule (any key ending in ColumnRef)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("ColumnRef") and isinstance(value, str):
                found.add(value.lower())
            else:
                found |= column_refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= column_refs(item)
    return found


def rules_referencing(filters: list, column_id: str) -> list[int]:
    """Indexes of the top-level rules that reference `column_id`."""
    cid = column_id.lower()
    return [i for i, rule in enumerate(filters or []) if cid in column_refs(rule)]


def drop_column(filters: list, column_id: str) -> list:
    """Remove every reference to `column_id`.

    A single (or legacy) rule that references the column is dropped. A group
    rule loses only the matching sub-filters, and is dropped if none remain.
    """
    cid = column_id.lower()
    kept: list = []
    for rule in filters or []:
        if cid not in column_refs(rule):
            kept.append(rule)
            continue
        if isinstance(rule, dict) and rule.get("tag") == "GroupFilterRule":
            contents = dict(rule.get("contents") or {})
            subs = [s for s in contents.get("groupFilterSubFilters") or []
                    if cid not in column_refs(s)]
            if subs:
                contents["groupFilterSubFilters"] = subs
                kept.append({**rule, "contents": contents})
    return kept
