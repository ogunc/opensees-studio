"""Mechanism vectors expanded from independent DOFs to physical node DOFs."""

from __future__ import annotations

import numpy as np

from opensees_studio.core import EqualDOFConstraint, Node, Project, RigidDiaphragm, RigidLink
from opensees_studio.services.stability import _MotionExpander


class _Ops:
    def __init__(self, dofs: dict[int, tuple[int, ...]]) -> None:
        self._dofs = dofs

    def nodeDOFs(self, tag: int) -> tuple[int, ...]:
        return self._dofs[tag]


def _movers(project: Project, dofs: dict[int, tuple[int, ...]], vector: list[float]):
    expander = _MotionExpander(project, _Ops(dofs))
    return {(mover.node, mover.dof): mover.amplitude for mover in expander.movers(np.array(vector))}


def test_equaldof_motion_is_copied_to_the_slave_node() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
        ],
        mp_constraints=[EqualDOFConstraint(retained_node=1, constrained_node=2, dofs=(1,))],
    )
    movers = _movers(project, {1: (0, 1, 2), 2: (-1, -1, -1)}, [2.0, 0.0, 0.0])
    assert movers[(1, "Ux")] == 1.0
    assert movers[(2, "Ux")] == 1.0


def test_rigid_beam_link_adds_the_lever_arm_translation() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(2.0, 0.0, 0.0)),
        ],
        rigid_links=[RigidLink(kind="beam", retained_node=1, constrained_node=2)],
    )
    # OpenSees rz = 1; node 2 is 2 m along +X, so it moves +2 in the global Uz.
    movers = _movers(project, {1: (0, 1, 2), 2: (-1, -1, -1)}, [0.0, 0.0, 1.0])
    assert movers[(1, "Ry")] == -0.5
    assert movers[(2, "Uz")] == 1.0


def test_rigid_diaphragm_adds_the_in_plane_rotation_translation() -> None:
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(2.0, 0.0, 0.0)),
        ],
        diaphragms=[RigidDiaphragm(id=1, perp_dirn=3, retained_node=1, constrained_nodes=(2,))],
    )
    movers = _movers(
        project,
        {1: (0, 1, 2, 3, 4, 5), 2: (-1, -1, -1, -1, -1, -1)},
        [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    )
    assert movers[(1, "Rz")] == 0.5
    assert movers[(2, "Uy")] == 1.0
