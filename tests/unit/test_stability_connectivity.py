"""Connectivity precheck: warnings only, never a stability verdict."""

from __future__ import annotations

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EqualDOFConstraint,
    Node,
    Project,
)
from opensees_studio.services.stability import _connectivity_warnings

FIXED_2D = (True, False, True, False, False, False)


def _beam(*, first_fixed: bool = True, second_fixed: bool = True) -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIXED_2D if first_fixed else (False,) * 6),
            Node(
                id=2,
                coords=(4.0, 0.0, 0.0),
                restraint=FIXED_2D if second_fixed else (False,) * 6,
            ),
        ],
        sections=[ElasticSection(id=1, E=2e8, A=0.01, Iz=1e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )


def test_a_free_component_warns_but_is_not_declared_unstable() -> None:
    warnings = _connectivity_warnings(_beam(first_fixed=False, second_fixed=False))
    assert any("no restraint or grounded spring" in warning for warning in warnings)


def test_a_supported_component_does_not_warn() -> None:
    assert _connectivity_warnings(_beam()) == []


def test_two_independently_supported_components_do_not_warn() -> None:
    project = _beam()
    project.nodes.extend(
        [
            Node(id=3, coords=(10.0, 0.0, 0.0), restraint=FIXED_2D),
            Node(id=4, coords=(14.0, 0.0, 0.0), restraint=FIXED_2D),
        ]
    )
    project.elements.append(ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1))
    assert _connectivity_warnings(project) == []


def test_an_equal_dof_connects_a_free_component_to_a_supported_one() -> None:
    project = _beam()
    project.nodes.append(Node(id=3, coords=(10.0, 0.0, 0.0)))
    # No element joins node 3: the explicit equalDOF is the only path to the
    # supported component. Coincident coordinates alone must not count.
    project.mp_constraints = [EqualDOFConstraint(retained_node=2, constrained_node=3, dofs=(1, 3))]
    assert _connectivity_warnings(project) == []
