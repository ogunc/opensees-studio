"""Self weight of fiber and aggregated sections, BeamWithHinges and trusses."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import (
    BeamWithHingesElement,
    CorotTrussElement,
    ElasticSection,
    FiberSection,
    ForceBeamColumn,
    Node,
    Project,
    TrussElement,
    total_self_weight,
)
from opensees_studio.core.sections import (
    AggregatorDOF,
    CircularPatch,
    Fibre,
    RectangularPatch,
    SectionAggregator,
    StraightLayer,
)
from opensees_studio.core.self_weight import (
    is_weighted,
    nodal_self_weight_loads,
    self_weight_loads,
    weight_per_length,
)


def _rc(unit_weight: float = 24.0) -> FiberSection:
    return FiberSection(
        id=1,
        unit_weight=unit_weight,
        patches=[
            RectangularPatch(
                material_id=1, n_fib_y=4, n_fib_z=4, y_i=-0.2, z_i=-0.1, y_j=0.2, z_j=0.1
            )
        ],
        layers=[
            StraightLayer(
                material_id=2, n_bars=2, bar_area=1e-4, y_start=0, z_start=0, y_end=0, z_end=0
            )
        ],
        fibres=[Fibre(y=0, z=0, area=5e-5, material_id=2)],
    )


def test_the_gross_area_of_a_fiber_section() -> None:
    assert _rc().gross_area == pytest.approx(0.08 + 2e-4 + 5e-5)
    ring = FiberSection(
        id=2,
        patches=[
            CircularPatch(
                material_id=1, n_fib_circ=8, n_fib_rad=2, r_inner=0.1, r_outer=0.2, end_angle=180.0
            )
        ],
    )
    assert ring.gross_area == pytest.approx(math.pi * (0.04 - 0.01) / 2)


def _project(*elements, sections=()) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(4, 0, 0))],
        sections=list(sections),
        elements=list(elements),
    )


def test_a_fiber_frame_and_an_aggregator_weigh_gamma_times_the_gross_area() -> None:
    wrapped = SectionAggregator(
        id=2, section_id=1, pairings=[AggregatorDOF(material_id=3, dof="T")]
    )
    project = _project(
        ForceBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ForceBeamColumn(id=2, nodes=(1, 2), section_id=2),
        sections=[_rc(), wrapped],
    )
    w = 24.0 * _rc().gross_area
    assert [weight_per_length(project, e) for e in project.elements] == pytest.approx([w, w])
    assert [load.wz for load in self_weight_loads(project)] == pytest.approx([-w, -w])


def test_an_aggregator_without_a_base_section_or_in_a_loop_weighs_nothing() -> None:
    alone = SectionAggregator(id=1, pairings=[AggregatorDOF(material_id=3, dof="T")])
    loop = SectionAggregator(id=2, section_id=2, pairings=[AggregatorDOF(material_id=3, dof="T")])
    project = _project(
        ForceBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ForceBeamColumn(id=2, nodes=(1, 2), section_id=2),
        sections=[alone, loop],
    )
    assert [weight_per_length(project, e) for e in project.elements] == [0.0, 0.0]


def test_a_beam_with_hinges_uses_its_own_unit_weight_and_area() -> None:
    member = BeamWithHingesElement(
        id=1,
        nodes=(1, 2),
        section_i_id=1,
        section_j_id=1,
        lp_i=0.2,
        lp_j=0.2,
        E=1.0,
        A=0.3,
        Iz=1.0,
        unit_weight=25.0,
    )
    project = _project(member, sections=[_rc(0.0)])
    assert weight_per_length(project, member) == pytest.approx(7.5)
    assert "unit_weight" not in member.model_copy(update={"unit_weight": 0.0}).model_dump()


@pytest.mark.parametrize("cls", [TrussElement, CorotTrussElement])
def test_a_truss_sends_half_its_weight_to_each_end(cls) -> None:  # type: ignore[no-untyped-def]
    bar = cls(id=1, nodes=(1, 2), area=0.01, material_id=1, unit_weight=77.0)
    project = _project(bar)
    loads = nodal_self_weight_loads(project, multiplier=2.0)
    half = 0.5 * 77.0 * 0.01 * 4.0 * 2.0
    assert list(loads[1]) == pytest.approx([0, 0, -half])
    assert list(loads[2]) == pytest.approx([0, 0, -half])
    assert self_weight_loads(project) == []  # a truss takes no element load
    assert is_weighted(project, bar)
    assert total_self_weight(project) == pytest.approx(77.0 * 0.01 * 4.0)


def test_unset_unit_weights_save_as_before() -> None:
    assert "unit_weight" not in TrussElement(id=1, nodes=(1, 2), area=1, material_id=1).model_dump()
    assert "unit_weight" not in _rc(0.0).model_dump()
    weightless = _project(TrussElement(id=1, nodes=(1, 2), area=1, material_id=1))
    assert nodal_self_weight_loads(weightless) == {}
    assert total_self_weight(weightless) == 0.0
    assert ElasticSection  # imported for the others
