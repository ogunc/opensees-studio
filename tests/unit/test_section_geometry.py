"""Section geometry: properties, torsion, fibres and the overlap check, against closed forms."""

from __future__ import annotations

import math

import numpy as np
import pytest

from opensees_studio.core.sections.geometry import (
    CircleRegion,
    PolygonRegion,
    rectangle,
    region_fibres,
    section_properties,
    torsion_constant,
)


def _rect_j(h: float, b: float) -> float:
    h, b = max(h, b), min(h, b)
    return h * b**3 * (1 / 3 - 0.21 * b / h * (1 - b**4 / (12 * h**4)))


def test_rectangle_properties() -> None:
    props = section_properties([rectangle(0.3, 0.5, 1.0, 2.0)])
    assert pytest.approx(0.15) == props.A
    assert (props.y_c, props.z_c) == pytest.approx((1.0, 2.0))
    assert props.Iz == pytest.approx(0.3 * 0.5**3 / 12)
    assert props.Iy == pytest.approx(0.5 * 0.3**3 / 12)
    assert props.Iyz == pytest.approx(0.0, abs=1e-15)
    assert props.Sz == pytest.approx(0.3 * 0.5**2 / 6)
    assert props.Zz == pytest.approx(0.3 * 0.5**2 / 4, rel=1e-3)
    assert props.Zy == pytest.approx(0.5 * 0.3**2 / 4, rel=1e-3)
    assert not props.notes


def test_orientation_does_not_matter() -> None:
    ccw = PolygonRegion(((0, 0), (0, 1), (2, 1), (2, 0)))
    cw = PolygonRegion(((0, 0), (2, 0), (2, 1), (0, 1)))
    assert section_properties([ccw]).A == pytest.approx(section_properties([cw]).A) == 2.0


def test_hollow_circle() -> None:
    props = section_properties([CircleRegion(0, 0, 0.25), CircleRegion(0, 0, 0.2, hole=True)])
    assert pytest.approx(math.pi * (0.25**2 - 0.2**2)) == props.A
    assert props.Iz == pytest.approx(math.pi * (0.25**4 - 0.2**4) / 4)
    assert props.Zz == pytest.approx(4 / 3 * (0.25**3 - 0.2**3), rel=2e-3)


def test_angle_principal_axes() -> None:
    """L 4 x 4 x 1/2 without fillets: principal axes at 45°, I1 + I2 = Iz + Iy."""
    angle = PolygonRegion(((0, 0), (0, 4), (0.5, 4), (0.5, 0.5), (4, 0.5), (4, 0)))
    props = section_properties([angle])
    assert pytest.approx(3.75) == props.A
    assert props.y_c == pytest.approx(1.1833, abs=1e-4)
    assert abs(props.angle) == pytest.approx(45.0)
    assert pytest.approx(props.Iz + props.Iy) == props.I1 + props.I2
    assert math.sqrt(props.I2 / props.A) == pytest.approx(0.782, abs=1e-3)
    assert props.notes and "Unsymmetric" in props.notes[0]


def test_overlaps_and_stray_holes_are_noted() -> None:
    overlapping = [rectangle(0.3, 0.5), rectangle(0.3, 0.5, 0.1, 0.0)]
    assert "overlap" in section_properties(overlapping).notes[0]
    stray_hole = [rectangle(0.3, 0.5), CircleRegion(0.0, 0.3, 0.1, hole=True)]
    assert "overlap" in section_properties(stray_hole).notes[0]
    touching = [rectangle(0.3, 0.5), rectangle(0.3, 0.5, 0.5, 0.0)]
    assert not section_properties(touching).notes


def test_holes_that_take_everything_are_refused() -> None:
    with pytest.raises(ValueError):
        section_properties([rectangle(1, 1, hole=True)])
    with pytest.raises(ValueError):
        section_properties([])


@pytest.mark.parametrize(
    ("regions", "exact", "tolerance"),
    [
        ([rectangle(0.3, 0.5)], _rect_j(0.5, 0.3), 1e-3),
        ([rectangle(0.3, 0.3)], 0.1406 * 0.3**4, 1e-3),
        ([CircleRegion(0, 0, 0.25)], math.pi * 0.25**4 / 2, 1e-3),
        (
            [CircleRegion(0, 0, 0.25), CircleRegion(0, 0, 0.23, hole=True)],
            math.pi * (0.25**4 - 0.23**4) / 2,
            2e-3,
        ),
        ([rectangle(1.0, 0.01)], _rect_j(1.0, 0.01), 1e-2),
    ],
)
def test_torsion_constant_against_closed_forms(regions, exact, tolerance) -> None:  # type: ignore[no-untyped-def]
    assert torsion_constant(regions) == pytest.approx(exact, rel=tolerance)


def test_torsion_of_a_thin_tube_follows_bredt() -> None:
    """A square tube 0.3 wide, wall 0.005: J ≈ 4 Am² t / s within a few per cent."""
    regions = [rectangle(0.3, 0.3), rectangle(0.29, 0.29, hole=True)]
    am, s = 0.295**2, 4 * 0.295
    assert torsion_constant(regions) == pytest.approx(4 * am**2 * 0.005 / s, rel=0.03)


def test_fibres_carry_the_area_and_nearly_the_inertia() -> None:
    regions = [CircleRegion(0, 0, 0.25), CircleRegion(0, 0, 0.15, hole=True)]
    grid = region_fibres(regions, 40, 40)
    props = section_properties(regions)
    assert grid.area.sum() == pytest.approx(props.A)
    assert float(np.sum(grid.area * grid.y**2)) == pytest.approx(props.Iz, rel=0.01)
    assert float(np.sum(grid.area * grid.y)) == pytest.approx(0.0, abs=1e-9)
