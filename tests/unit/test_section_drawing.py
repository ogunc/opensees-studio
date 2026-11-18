"""The Section Designer's commands and the sections they become."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.sections import ElasticSection, FiberSection
from opensees_studio.core.sections.drawing import (
    CommandError,
    elastic_section,
    fiber_section,
    run_command,
)
from opensees_studio.core.sections.geometry import CircleRegion, section_properties


def _draw(*commands: str):  # type: ignore[no-untyped-def]
    regions: list = []
    for command in commands:
        regions = run_command(command, regions).regions
    return regions


def test_shapes_have_their_textbook_areas() -> None:
    assert pytest.approx(0.15) == section_properties(_draw("rect 0.3 0.5")).A
    assert pytest.approx(math.pi * 0.04) == section_properties(_draw("circle 0.4")).A
    i_area = 2 * 0.15 * 0.012 + (0.3 - 0.024) * 0.008
    assert pytest.approx(i_area) == section_properties(_draw("ishape 0.3 0.15 0.012 0.008")).A
    assert (
        pytest.approx(2 * 0.1 * 0.012 + (0.3 - 0.024) * 0.008)
        == section_properties(_draw("channel 0.3 0.1 0.012 0.008")).A
    )
    assert (
        pytest.approx(0.2 * 0.015 + 0.285 * 0.01)
        == section_properties(_draw("tee 0.3 0.2 0.015 0.01")).A
    )
    assert pytest.approx(0.01 * 0.19) == section_properties(_draw("angle 0.1 0.1 0.01")).A
    assert pytest.approx(0.06 - 0.18 * 0.28) == section_properties(_draw("tube 0.2 0.3 0.01")).A
    assert (
        pytest.approx(math.pi * (0.15**2 - 0.14**2)) == section_properties(_draw("pipe 0.3 0.01")).A
    )


def test_ishape_inertia() -> None:
    props = section_properties(_draw("ishape 0.3 0.15 0.012 0.008"))
    expected = 0.15 * 0.3**3 / 12 - (0.15 - 0.008) * (0.3 - 0.024) ** 3 / 12
    assert props.Iz == pytest.approx(expected)
    assert props.y_c == pytest.approx(0.0, abs=1e-12)


def test_position_hole_move_delete_center_clear() -> None:
    regions = _draw("rect 0.4 0.4 1 2", "hole circle 0.1 1 2")
    assert regions[1].hole and isinstance(regions[1], CircleRegion)
    props = section_properties(regions)
    assert (props.y_c, props.z_c) == pytest.approx((1.0, 2.0))
    regions = run_command("center", regions).regions
    props = section_properties(regions)
    assert (props.y_c, props.z_c) == pytest.approx((0.0, 0.0), abs=1e-12)
    regions = run_command("move last 0.1 0", regions).regions
    assert regions[1].y == pytest.approx(0.1)  # type: ignore[union-attr]
    regions = run_command("delete 2", regions).regions
    assert len(regions) == 1
    assert run_command("clear", regions).regions == []


def test_polygon_vertices() -> None:
    regions = _draw("poly 0,0 0,3 4,0")
    assert pytest.approx(6.0) == section_properties(regions).A


@pytest.mark.parametrize(
    "command",
    [
        "",
        "triangle 1 2",
        "rect 1",
        "rect -1 2",
        "rect a b",
        "poly 0,0 1,1",
        "poly 0;0 1,1 2,0",
        "ishape 0.3 0.15 0.2 0.008",
        "tube 0.2 0.3 0.2",
        "pipe 0.3 0.2",
        "angle 0.1 0.1 0.2",
        "delete 1",
        "move 3 0 0",
        "center",
        "hole",
    ],
)
def test_bad_commands_say_why(command: str) -> None:
    with pytest.raises(CommandError):
        run_command(command, [])


def test_sections_from_regions() -> None:
    regions = _draw("ishape 0.3 0.15 0.012 0.008")
    props = section_properties(regions)
    elastic = elastic_section(regions, section_id=4, name="I", modulus=200e9, poisson=0.3)
    assert isinstance(elastic, ElasticSection)
    assert (elastic.A, elastic.Iz, elastic.Iy) == pytest.approx((props.A, props.Iz, props.Iy))
    assert pytest.approx(200e9 / 2.6) == elastic.G
    assert pytest.approx((2 * 0.15 * 0.012**3 + 0.276 * 0.008**3) / 3, rel=0.06) == elastic.J
    assert elastic_section(regions, section_id=4, name="I", modulus=1.0, torsion=7.0).J == 7.0
    fiber = fiber_section(
        _draw("rect 0.3 0.5 2 3"), section_id=5, name="F", material_id=2, cells=20
    )
    assert isinstance(fiber, FiberSection)
    assert sum(f.area for f in fiber.fibres) == pytest.approx(0.15)
    # Measured from the centroid, wherever the drawing put it.
    assert sum(f.area * f.y for f in fiber.fibres) == pytest.approx(0.0, abs=1e-12)
    assert sum(f.area * f.y**2 for f in fiber.fibres) == pytest.approx(0.3 * 0.5**3 / 12, rel=5e-3)
    assert {f.material_id for f in fiber.fibres} == {2}
