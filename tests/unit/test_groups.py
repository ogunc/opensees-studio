"""Groups: membership edits, pruning, validation and an unchanged file without groups."""

from __future__ import annotations

import pytest

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Group, Node, Project
from opensees_studio.core.groups import (
    group_members,
    group_named,
    groups_of,
    prune_groups,
    with_members,
)


def _project() -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=i, coords=(float(i), 0.0, 0.0)) for i in (1, 2, 3)],
        sections=[ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, Iy=1.0, G=1.0, J=1.0)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ],
        groups=[Group(id=1, name="Beams", node_ids=[3, 1, 1], element_ids=[2, 1])],
    )


def test_members_are_sorted_and_unique() -> None:
    assert _project().groups[0].node_ids == [1, 3]


def test_add_remove_and_replace() -> None:
    group = _project().groups[0]
    assert with_members(group, [2], mode="add").node_ids == [1, 2, 3]
    assert with_members(group, [1], [1], mode="remove").element_ids == [2]
    replaced = with_members(group, [2], [], mode="replace")
    assert (replaced.node_ids, replaced.element_ids) == ([2], [])
    with pytest.raises(ValueError):
        with_members(group, mode="toggle")


def test_lookups() -> None:
    project = _project()
    assert group_named(project, " beams ") is project.groups[0]
    assert group_members(project, 1) == ({1, 3}, {1, 2})
    assert group_members(project, 9) == (set(), set())
    assert groups_of(project, node_id=3) == [project.groups[0]]
    assert groups_of(project, node_id=2) == []


def test_prune_drops_what_the_model_lost() -> None:
    project = _project()
    project.nodes[:] = [n for n in project.nodes if n.id != 3]
    project.elements[:] = [e for e in project.elements if e.id != 2]
    assert prune_groups(project)
    assert (project.groups[0].node_ids, project.groups[0].element_ids) == ([1], [1])
    assert not prune_groups(project)


def test_validation_names_missing_members_and_repeated_names() -> None:
    project = _project()
    project.groups.append(Group(id=2, name="BEAMS", node_ids=[42]))
    with pytest.raises(ValueError, match="share the name") as info:
        project.validate_references()
    assert "missing joint(s) [42]" in str(info.value)


def test_colour_must_be_hex() -> None:
    assert Group(id=1, colour="#AABBCC").colour == "#aabbcc"
    with pytest.raises(ValueError):
        Group(id=1, colour="red")


def test_a_project_without_groups_dumps_no_groups_key() -> None:
    project = _project()
    project.groups.clear()
    assert "groups" not in project.model_dump()
    assert Project.model_validate_json(_project().model_dump_json()).groups == _project().groups
