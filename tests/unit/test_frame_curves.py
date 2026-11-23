"""Shape functions of the bent members a deformed shape draws."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project, TrussElement
from opensees_studio.services.frame_curves import frame_curves_from_dofs, transverse_shape

XI = np.linspace(0.0, 1.0, 5)


def test_fixed_ends_follow_the_hermite_cubic() -> None:
    # Unit slope at a, nothing else: L t (1 - t)^2.
    v = transverse_shape(XI, 0.0, 0.0, 1.0, 0.0)
    assert v == pytest.approx(XI * (1.0 - XI) ** 2)


def test_a_released_end_has_no_curvature_and_ignores_its_slope() -> None:
    # Fixed at b with zero slope, released at a: the cantilever shape of a tip deflection.
    v = transverse_shape(XI, 1.0, 0.0, 123.0, 0.0, free_a=True)
    s = 1.0 - XI
    assert v == pytest.approx((3 * s**2 - s**3) / 2.0)
    curvature = np.gradient(
        np.gradient(transverse_shape(np.linspace(0, 1, 201), 1.0, 0.0, 9.0, 0.0, True))
    )
    assert abs(curvature[1]) < 1e-6


def test_both_ends_released_is_the_chord() -> None:
    v = transverse_shape(XI, 1.0, 3.0, 5.0, -7.0, free_a=True, free_b=True)
    assert v == pytest.approx(1.0 + 2.0 * XI)


def test_arrays_of_members_give_one_row_each() -> None:
    v = transverse_shape(XI, np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.zeros(2), np.zeros(2))
    assert v.shape == (2, len(XI))
    assert v[1] == pytest.approx(np.ones(len(XI)))


def test_a_2d_mode_shape_bends_the_beams_and_not_the_trusses() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(4.0, 0.0, 0.0)),
            Node(id=3, coords=(4.0, 0.0, 3.0)),
        ],
        sections=[ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            TrussElement(id=2, nodes=(2, 3), area=1.0, material_id=1),
        ],
    )
    # OpenSees order (Ux, Uz, Ry) with the global sign: a rotation at node 1 only.
    curves = frame_curves_from_dofs(project, {1: [0.0, 0.0, 0.1], 2: [0.0, 0.0, 0.0]})
    assert curves.element_ids.tolist() == [1]
    mid = len(curves.stations) // 2
    # A positive Ry turns +X into -Z: the beam dips near node 1.
    assert curves.offsets[0, mid, 2] == pytest.approx(-0.1 * 4.0 / 8.0)
    assert curves.offsets[0, :, 1] == pytest.approx(0.0)
    assert curves.offsets[0, [0, -1]] == pytest.approx(0.0)


def test_a_model_without_rotations_draws_no_curves() -> None:
    project = Project(
        ndm=3, ndf=3, nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))]
    )
    assert len(frame_curves_from_dofs(project, {1: [0, 0, 0], 2: [0, 0, 1]})) == 0
