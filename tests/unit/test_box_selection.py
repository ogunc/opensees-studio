"""The box-selection rule: a member needs both joints inside."""

from __future__ import annotations

from opensees_studio.core import Node, Project, TrussElement
from opensees_studio.core.selection import elements_with_nodes_inside


def _project() -> Project:
    return Project(
        nodes=[Node(id=i, coords=(float(i), 0.0, 0.0)) for i in range(1, 5)],
        elements=[
            TrussElement(id=1, nodes=(1, 2), area=0.01, material_id=1),
            TrussElement(id=2, nodes=(3, 4), area=0.01, material_id=1),
        ],
    )


def test_a_member_is_taken_only_when_every_joint_is_inside() -> None:
    project = _project()

    assert elements_with_nodes_inside(project, {1, 2}) == {1}
    assert elements_with_nodes_inside(project, {1}) == set()
    assert elements_with_nodes_inside(project, {1, 2, 3, 4}) == {1, 2}
    assert elements_with_nodes_inside(project, set()) == set()
