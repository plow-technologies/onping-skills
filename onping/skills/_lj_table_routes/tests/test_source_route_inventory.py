"""Static route inventory for the seven Data Table source skills (source change task 5.5).

Each skill's own suite checks at run time that the routes it calls are listed and that the delete-everything
route is never reached. This file adds the cross-skill static view: no source skill script or library names the
delete-everything route or any sync route, and every route name it does use is a listed, non-forbidden route.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_ROOT))

from _lj_table_routes.routes import ROUTES  # noqa: E402

SOURCE_SKILLS = (
    "onping-datatable-create",
    "onping-datatable-rename",
    "onping-datatable-delete",
    "onping-datatable-rows-add",
    "onping-datatable-rows-delete",
    "onping-datatable-import",
    "onping-datatable-export",
)

NAMED = re.compile(r'["\'](datatable_[a-z_]+)["\']')


def _sources(skill: str):
    files = sorted((SKILLS_ROOT / skill / "scripts").glob("*.py"))
    assert files, f"{skill} has no scripts"
    return files


@pytest.mark.parametrize("skill", SOURCE_SKILLS)
def test_source_skill_names_only_listed_routes_and_no_sync_or_wipe_route(skill):
    for path in _sources(skill):
        for name in set(NAMED.findall(path.read_text())):
            assert name in ROUTES, f"{path.name} names unlisted route {name}"
            assert not ROUTES[name].get("forbidden"), f"{path.name} names forbidden route {name}"
            assert "sync" not in name, f"{path.name} names sync route {name}"


@pytest.mark.parametrize("skill", SOURCE_SKILLS)
def test_source_skill_never_spells_the_delete_everything_path(skill):
    for path in _sources(skill):
        text = path.read_text()
        assert "delete_by_table" not in text and "delete/by/table" not in text, path.name


def test_the_seven_source_skills_are_the_seven_in_the_change():
    assert len(SOURCE_SKILLS) == 7
    for skill in SOURCE_SKILLS:
        assert (SKILLS_ROOT / skill / "SKILL.md").exists()
