"""Pile soil springs: the published formulas by hand, and what the generator builds."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project
from opensees_studio.core.piles import (
    PileSpec,
    SoilLayer,
    api_alpha,
    api_nq,
    api_sand_pu,
    matlock_pu,
    pile_springs,
)

D = 0.6
CLAY = SoilLayer(top=0.0, bottom=20.0, kind="clay", unit_weight=8e3, su=40e3)
SAND = SoilLayer(top=0.0, bottom=20.0, kind="sand", unit_weight=10e3, phi=35.0, k=24e6)


def test_matlock_by_hand() -> None:
    shallow = (3 + 8e3 * 2.0 / 40e3 + 0.5 * 2.0 / D) * 40e3 * D
    assert matlock_pu(CLAY, 2.0, D) == pytest.approx(shallow)
    assert matlock_pu(CLAY, 15.0, D) == pytest.approx(9 * 40e3 * D)


def test_api_sand_coefficients_at_35_degrees() -> None:
    """API RP 2A Fig. 6.8.6-1 at 35°: C1 ≈ 3.0, C2 ≈ 3.4, C3 ≈ 55."""
    sigma = 10e3 * 1.0
    shallow = api_sand_pu(SAND, 1.0, 1.0, sigma)  # (C1 + C2) * sigma at z = D = 1
    deep = api_sand_pu(SAND, 1000.0, 1.0, sigma)  # C3 * D * sigma
    assert shallow / sigma == pytest.approx(3.0 + 3.4, rel=0.06)
    assert deep / sigma == pytest.approx(55.0, rel=0.06)


def test_api_alpha_and_nq() -> None:
    assert api_alpha(40.0, 160.0) == pytest.approx(0.5 * 0.25**-0.5)  # psi 0.25
    assert api_alpha(40.0, 20.0) == pytest.approx(min(1.0, 0.5 * 2.0**-0.25))
    assert api_nq(30.0) == 20.0
    assert api_nq(32.5) == pytest.approx(30.0)
    assert api_nq(45.0) == 50.0


def _pile(ndm: int = 2) -> Project:
    nodes = [Node(id=k + 1, coords=(0.0, 0.0, 2.0 - k * 2.0)) for k in range(7)]  # +2 .. -10
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=30e9, A=0.28, Iz=6.4e-3, Iy=6.4e-3, G=12e9, J=1e-2)],
        elements=[
            ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1) for k in range(6)
        ],
    )


def test_springs_cover_the_embedded_length_and_the_tip() -> None:
    spec = PileSpec(diameter=D, ground_level=0.0, layers=(CLAY,), stress_unit=1e3)
    springs = pile_springs(
        _pile(),
        {1, 2, 3, 4, 5, 6},
        spec,
        first_node_id=100,
        first_material_id=10,
        first_element_id=50,
    )
    # Joints at 0, -2, ..., -10, each with half of the members next to it in the soil.
    assert len(springs.nodes) == 6
    tult = [m for m in springs.materials if m.type == "TzSimple1"]
    sigma = lambda z: 8e3 * max(z, 1e-9)  # noqa: E731  (API: no adhesion at the surface)
    expected_shaft = sum(
        api_alpha(40e3, sigma(z)) * 40e3 * math.pi * D * trib
        for z, trib in ((0.0, 1.0), (2.0, 2.0), (4.0, 2.0), (6.0, 2.0), (8.0, 2.0), (10.0, 1.0))
    )
    assert sum(m.tult for m in tult) == pytest.approx(expected_shaft)
    tip = [m for m in springs.materials if m.type == "QzSimple1"]
    assert len(tip) == 1 and tip[0].qult == pytest.approx(9 * 40e3 * math.pi * D**2 / 4)
    assert all(e.dofs[-1] == 2 for e in springs.elements)  # 2D: vertical is OpenSees dof 2


def test_a_3d_pile_gets_p_y_both_ways() -> None:
    spec = PileSpec(diameter=D, ground_level=0.0, layers=(SAND,), stress_unit=1e3)
    springs = pile_springs(
        _pile(3),
        {1, 2, 3, 4, 5, 6},
        spec,
        first_node_id=100,
        first_material_id=10,
        first_element_id=50,
    )
    shaft = [e for e in springs.elements if len(e.dofs) == 3]
    assert shaft and all(e.dofs == (1, 2, 3) for e in shaft)


def test_a_pile_above_the_ground_is_refused() -> None:
    spec = PileSpec(diameter=D, ground_level=-50.0, layers=(CLAY,))
    with pytest.raises(ValueError, match="below the ground"):
        pile_springs(_pile(), {1}, spec, first_node_id=1, first_material_id=1, first_element_id=1)
