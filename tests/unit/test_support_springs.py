"""Support springs on the node model and in the frame plan, without OpenSees."""

from __future__ import annotations

import pytest

from opensees_studio.core import Node, Project
from opensees_studio.services.frame_members import plan_frame_members


def test_a_node_without_springs_dumps_no_spring_key() -> None:
    assert "spring" not in Node(id=1, coords=(0.0, 0.0, 0.0)).model_dump()
    node = Node(id=1, coords=(0.0, 0.0, 0.0), spring=(1.0, 0, 0, 0, 0, 0))
    assert node.model_dump()["spring"] == (1.0, 0, 0, 0, 0, 0) and node.has_spring


@pytest.mark.parametrize("bad", [-1.0, float("nan")])
def test_negative_or_nan_stiffness_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="not negative"):
        Node(id=1, coords=(0.0, 0.0, 0.0), spring=(bad, 0, 0, 0, 0, 0))


def test_the_plan_grounds_each_sprung_joint_in_solver_dofs() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), spring=(10.0, 99.0, 20.0, 0.0, 30.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
        ],
    )
    plan = plan_frame_members(project)
    (spring,) = plan.springs
    (ground,) = plan.nodes
    # 2D: Ux, Uz, Ry are OpenSees DOFs 1, 2, 3; ky (not a 2D DOF) is ignored.
    assert spring.dirs == (1, 2, 3) and spring.stiffnesses == (10.0, 20.0, 30.0)
    assert (spring.node_a, spring.node_b) == (ground.tag, 1)
    assert plan.grounds == [ground.tag] and plan.attached[1] == [ground]
    assert ground.tag == 3 and ground.coords == (0.0, 0.0)
