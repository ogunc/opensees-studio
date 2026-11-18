"""Chains, doubles and loops of user equalDOFs and rigid links are refused (pure core).

OpenSees 3.8's Transformation handler (every eigen analysis uses it) solves
them without an error into wrong results; see ``constraint_chain_problems``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import pytest

from opensees_studio.core import EqualDOFConstraint, Node, Project, RigidLink
from opensees_studio.core.diaphragms import constraint_chain_problems

ALL_3D = (1, 2, 3, 4, 5, 6)


def _project(
    mps: Sequence[tuple[int, int, tuple[int, ...]]] = (),
    links: Sequence[tuple[Literal["beam", "bar"], int, int]] = (),
    *,
    ndm: int = 3,
    ndf: int = 6,
) -> Project:
    """Four column tops 2, 3, 5, 7 tied by ``mps`` (retained, constrained, dofs) and ``links``."""
    nodes = [
        Node(id=nid, coords=(float(nid), 0.0, 3.0))  # Z up, in 2D (the X-Z plane) and 3D
        for nid in (2, 3, 5, 7)
    ]
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=nodes,
        mp_constraints=[
            EqualDOFConstraint(retained_node=r, constrained_node=c, dofs=d) for r, c, d in mps
        ],
        rigid_links=[RigidLink(kind=k, retained_node=r, constrained_node=c) for k, r, c in links],
    )


def _refused(project: Project) -> str:
    problems = constraint_chain_problems(project)
    assert problems
    with pytest.raises(ValueError, match="Reference validation failed"):
        project.validate_references()
    return " ".join(problems)


@pytest.mark.parametrize(
    "project",
    [
        _project(),
        # A star: every constraint retained by the same node.
        _project([(2, 3, (1, 2)), (2, 5, (1, 2))], [("beam", 2, 7)]),
        # Chains through a node an equalDOF of every DOF constrains: OpenSees
        # solves them right (the probe matched Lagrange and the flexibility).
        _project([(2, 3, ALL_3D), (3, 5, (1, 2))]),
        _project([(2, 3, ALL_3D), (3, 5, ALL_3D), (5, 7, (1,))]),
        _project([(2, 3, ALL_3D)], [("beam", 3, 5)]),
        _project([(2, 3, ALL_3D)], [("bar", 3, 5)]),
        _project([(2, 3, (1, 2, 3)), (3, 5, (1,))], ndm=2, ndf=3),
    ],
)
def test_constraints_opensees_solves_right_pass(project: Project) -> None:
    assert constraint_chain_problems(project) == []
    project.validate_references()


@pytest.mark.parametrize(
    ("project", "middle", "retained"),
    [
        (_project([(2, 3, (1, 2)), (3, 5, (1, 2))]), 3, 2),
        (_project([(2, 3, (1,)), (3, 5, (2,))]), 3, 2),
        # Full DOF on the far side does not help: the middle node keeps DOF.
        (_project([(2, 3, (1, 2)), (3, 5, ALL_3D)]), 3, 2),
        (_project([(2, 3, ALL_3D), (3, 5, (1, 2)), (5, 7, (1,))]), 5, 3),
        (_project([(2, 3, (1, 2))], [("beam", 3, 5)]), 3, 2),
        (_project([(3, 5, (1,))], [("beam", 2, 3)]), 3, 2),
        (_project([(3, 5, ALL_3D)], [("beam", 2, 3)]), 3, 2),
        (_project([], [("beam", 2, 3), ("beam", 3, 5)]), 3, 2),
        (_project([], [("bar", 2, 3), ("bar", 3, 5)]), 3, 2),
        (_project([(2, 3, (1, 2)), (3, 5, (1, 2))], ndm=2, ndf=3), 3, 2),
    ],
)
def test_a_chain_is_refused_with_a_remedy(project: Project, middle: int, retained: int) -> None:
    text = _refused(project)
    assert f"Node {middle} is the constrained node of" in text
    assert "cannot chain" in text
    assert f"to node {retained} directly" in text
    assert f"equalDOF of every DOF (1-{project.ndf})" in text


def test_a_chain_names_both_constraints() -> None:
    project = _project([(2, 3, (1, 2))], [("beam", 3, 5)])
    (problem,) = constraint_chain_problems(project)
    assert "equalDOF 2->3 (DOF 1, 2)" in problem
    assert "rigid link (beam) 3->5" in problem


@pytest.mark.parametrize(
    "project",
    [
        _project([(2, 3, (1,)), (5, 3, (2,))]),
        _project([(2, 3, (1,)), (2, 3, (2,))]),
        _project([(2, 3, ALL_3D)], [("beam", 5, 3)]),
    ],
)
def test_a_node_constrained_twice_is_refused(project: Project) -> None:
    text = _refused(project)
    assert "Node 3 is the constrained node of 2 constraints" in text
    assert "Merge them into one equalDOF" in text


def test_a_loop_of_full_dof_equal_dofs_is_refused() -> None:
    (problem,) = constraint_chain_problems(
        _project([(2, 3, ALL_3D), (3, 5, ALL_3D), (5, 2, ALL_3D)])
    )
    assert "form a loop" in problem
    assert "2->3->5->2" in problem


def test_a_loop_through_a_partial_constraint_is_reported_as_a_chain_only() -> None:
    problems = constraint_chain_problems(_project([(2, 3, ALL_3D), (3, 2, (1,))]))
    assert len(problems) == 1
    assert "Node 2 is the constrained node of equalDOF 3->2" in problems[0]


def test_an_equal_dof_of_a_node_to_itself_is_refused() -> None:
    assert "ties node 3 to itself" in _refused(_project([(3, 3, (1,))]))
