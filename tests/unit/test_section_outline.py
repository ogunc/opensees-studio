"""The cross sections View → Show Extruded Sections sweeps along each member."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import (
    AggregatorDOF,
    CircularPatch,
    CorotTrussElement,
    ElasticBeamColumn,
    ElasticSection,
    FiberSection,
    Node,
    Project,
    RectangularPatch,
    SectionAggregator,
)
from opensees_studio.core.aisc import get_shape, shape_to_elastic_section
from opensees_studio.core.section_outline import member_regions
from opensees_studio.core.sections import PipeShape, TubeShape
from opensees_studio.core.sections.geometry import (
    CircleRegion,
    PolygonRegion,
    Region,
    outline,
    section_properties,
)
from opensees_studio.core.units import UnitSystem


def _project(section, *, ndm: int = 3, element=None) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(6.0, 0.0, 0.0))],
        sections=[section] if section is not None else [],
        elements=[element or ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )


def _regions(project: Project) -> list[Region]:
    return member_regions(project, project.elements[0])


def _span(regions: list[Region]) -> tuple[float, float]:
    """Extent of the regions along local y and along local z."""
    points = [p for r in regions for p in outline(r)]
    ys, zs = [p[0] for p in points], [p[1] for p in points]
    return max(ys) - min(ys), max(zs) - min(zs)


def _w14(ndm: int) -> ElasticSection:
    return shape_to_elastic_section(
        get_shape("W14X90"), elastic_modulus=29000.0, units=UnitSystem.US_IN_KIP, ndm=ndm
    )


@pytest.mark.parametrize("ndm", [2, 3])
def test_a_wide_flange_is_drawn_as_an_i_that_bends_like_the_section(ndm: int) -> None:
    section = _w14(ndm)
    regions = _regions(_project(section, ndm=ndm))
    shape = get_shape("W14X90")

    assert len(regions) == 1 and len(outline(regions[0])) == 12
    depth, width = (shape.d, shape.bf) if ndm == 2 else (shape.bf, shape.d)
    assert _span(regions) == pytest.approx((depth, width))
    props = section_properties(regions, plastic=False)
    # The outline (no fillets) bends about the same axis as the section, to a few per cent.
    assert props.Iz == pytest.approx(section.Iz, rel=0.05)
    assert props.Iy == pytest.approx(section.Iy, rel=0.05)
    assert (props.y_c, props.z_c) == pytest.approx((0.0, 0.0), abs=1e-9)


def test_tubes_and_pipes_are_hollow() -> None:
    pipe = ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, shape=PipeShape(od=0.3, t=0.01))
    regions = _regions(_project(pipe))
    assert [type(r) for r in regions] == [CircleRegion, CircleRegion]
    assert [r.hole for r in regions] == [False, True]

    tube = ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, shape=TubeShape(d=0.3, b=0.2, t=0.01))
    regions = _regions(_project(tube))
    assert [r.hole for r in regions] == [False, True]
    assert _span(regions) == pytest.approx((0.2, 0.3))  # 3D: the depth along local z


def test_a_fibre_section_draws_its_patches() -> None:
    section = FiberSection(
        id=1,
        patches=[
            RectangularPatch(
                material_id=1, n_fib_y=4, n_fib_z=2, y_i=-0.3, z_i=-0.2, y_j=0.3, z_j=0.2
            ),
            CircularPatch(
                material_id=1, n_fib_circ=8, n_fib_rad=2, r_inner=0.1, r_outer=0.2, end_angle=90.0
            ),
        ],
    )
    regions = _regions(_project(section))
    assert isinstance(regions[0], PolygonRegion) and _span(regions[:1]) == pytest.approx((0.6, 0.4))
    sector = regions[1]
    area = section_properties([sector], plastic=False).A
    assert area == pytest.approx(math.pi * (0.2**2 - 0.1**2) / 4.0, rel=0.01)


def test_an_aggregator_draws_its_base_section() -> None:
    base = _w14(3)
    aggregator = SectionAggregator(
        id=2, section_id=1, pairings=[AggregatorDOF(material_id=1, dof="T")]
    )
    project = _project(base)
    project = project.model_copy(
        update={
            "sections": [base, aggregator],
            "elements": [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=2)],
        }
    )
    assert len(outline(_regions(project)[0])) == 12


def test_without_a_hint_the_equivalent_rectangle_is_drawn() -> None:
    section = ElasticSection(id=1, E=1.0, A=0.06, Iz=0.06 * 0.3**2 / 12, Iy=0.06 * 0.2**2 / 12)
    assert _span(_regions(_project(section))) == pytest.approx((0.3, 0.2))


def test_a_truss_is_the_round_bar_of_its_area() -> None:
    truss = CorotTrussElement(id=1, nodes=(1, 2), material_id=1, area=0.01)
    (bar,) = _regions(_project(None, element=truss))
    assert isinstance(bar, CircleRegion) and math.pi * bar.radius**2 == pytest.approx(0.01)


def test_nothing_is_drawn_for_an_unknown_section() -> None:
    project = _project(None)
    assert _regions(project) == []
