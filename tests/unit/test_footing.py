"""Isolated footings (core.design.footing): soil pressure and ACI 318-19 checks.

The concentric case is worked by hand below (N, mm, MPa): a 2.5 m square,
600 mm thick footing under a 400 mm column, 16 mm bars at 150 mm, f'c 21 MPa.
"""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.footing import (
    Footing,
    FootingDesign,
    FootingLoad,
    base_actions,
    check_footing,
    development_length,
    flexural_strength,
    required_steel,
    size_effect,
    size_footing,
    soil_pressure,
)


def _footing(**kw: float) -> Footing:
    data: dict[str, float] = dict(
        length_x=2500.0, width_y=2500.0, thickness=600.0, cx=400.0, cy=400.0,
        bar_x_spacing=150.0, bar_y_spacing=150.0,
    )  # fmt: skip
    data.update(kw)
    return Footing(**data)  # type: ignore[arg-type]


def _check(name: str, footing: Footing, service=(), strength=()):  # type: ignore[no-untyped-def]
    result = check_footing(footing, list(service), list(strength))
    (found,) = [c for c in result.checks if c.name == name]
    return found


def test_pressure_inside_the_kern_is_the_linear_formula() -> None:
    p = soil_pressure(2000.0, 1500.0, 1.0e6, 200.0, 100.0)
    assert p is not None
    q = 1.0e6 / 3.0e6 * (1 + 6 * 200 / 2000 + 6 * 100 / 1500)
    assert p.q_max == pytest.approx(q)
    assert p.contact() == 1.0


def test_one_way_eccentricity_outside_the_kern_has_the_closed_form() -> None:
    p = soil_pressure(2000.0, 1500.0, 1.0e6, 500.0, 0.0)
    assert p is not None
    assert p.q_max == pytest.approx(2.0e6 / (3.0 * 1500.0 * 500.0))
    assert p.contact() == pytest.approx(0.75, abs=0.01)


@pytest.mark.parametrize(("ex", "ey"), [(500.0, 300.0), (-600.0, 200.0), (300.0, -450.0)])
def test_two_way_partial_contact_is_in_equilibrium(ex: float, ey: float) -> None:
    n = 1.0e6
    p = soil_pressure(2000.0, 1500.0, n, ex, ey)
    assert p is not None
    x, y, q, da = p.region(-1000.0, 1000.0, -750.0, 750.0, n=400)
    assert (q.sum() * da) == pytest.approx(n, rel=1e-3)
    assert (q * x).sum() * da / n == pytest.approx(ex, rel=1e-2)
    assert (q * y).sum() * da / n == pytest.approx(ey, rel=1e-2)
    assert p.contact() < 1.0


def test_two_way_meets_one_way_as_one_eccentricity_vanishes() -> None:
    one = soil_pressure(2000.0, 1500.0, 1.0e6, 500.0, 0.0)
    two = soil_pressure(2000.0, 1500.0, 1.0e6, 500.0, 1.0)
    assert one is not None and two is not None
    assert two.q_max == pytest.approx(one.q_max, rel=1e-2)


def test_a_resultant_outside_the_footing_overturns() -> None:
    assert soil_pressure(2000.0, 1500.0, 1.0e6, 1000.0, 0.0) is None
    assert soil_pressure(2000.0, 1500.0, -1.0, 0.0, 0.0) is None


def test_reaction_moment_and_shear_move_the_resultant() -> None:
    footing = _footing(pedestal_height=500.0)
    # The support pushes the structure up 1000 kN and sideways +50 kN in X;
    # the structure pushes the footing down and -X at 1100 mm above its base.
    act = base_actions(footing, FootingLoad((50e3, 0.0, 1.0e6)), with_weight=False)
    assert act.n == pytest.approx(1.0e6)
    assert act.hx == pytest.approx(-50e3)
    assert act.my == pytest.approx(-50e3 * 1100.0)
    assert act.ex == pytest.approx(-55.0)


def test_concentric_footing_by_hand() -> None:
    footing = _footing()
    strength = [FootingLoad((0.0, 0.0, 1.5e6), label="U")]
    qu = 1.5e6 / 2500.0**2
    d = 600.0 - 75.0 - 8.0
    # One-way shear at d from the face: 2500 · (1250 - 200 - d) of pressure.
    shear = _check("One-way shear (X direction)", footing, strength=strength)
    vu = qu * 2500.0 * (1250.0 - 200.0 - d)
    As = math.pi * 16.0**2 / 4.0 * 2500.0 / 150.0
    vc = 0.66 * size_effect(d) * (As / (2500.0 * d)) ** (1 / 3) * math.sqrt(21.0) * 2500.0 * d
    assert shear.ratio == pytest.approx(vu / (0.75 * vc), rel=1e-3)
    # Flexure at the face: the 1050 mm cantilever.
    flexure = _check("Flexure (X bars)", footing, strength=strength)
    mu = qu * 2500.0 * 1050.0**2 / 2.0
    phi_mn, phi = flexural_strength(As, 2500.0, d, 21.0, 420.0)
    assert phi == 0.90
    assert flexure.ratio == pytest.approx(mu / phi_mn, rel=1e-3)
    # Punching at d/2 around the column (average d of the two layers).
    davg = (d + (600.0 - 75.0 - 16.0 - 8.0)) / 2.0
    b = 400.0 + davg
    punch = _check("Two-way shear (punching)", footing, strength=strength)
    vu2 = (1.5e6 - qu * b * b) / (4.0 * b * davg)
    vc2 = min(0.33, 0.17 * 3.0, 0.083 * (2.0 + 40.0 * davg / (4.0 * b)))
    vc2 *= size_effect(davg) * math.sqrt(21.0)
    assert punch.ratio == pytest.approx(vu2 / (0.75 * vc2), rel=2e-3)


def test_service_soil_checks() -> None:
    footing = _footing(soil_cover=1000.0)
    service = [FootingLoad((0.0, 0.0, 1.0e6), label="S")]
    weight = 2500.0**2 * 600.0 * 23.6e-6 + (2500.0**2 - 400.0**2) * 1000.0 * 18.0e-6
    bearing = _check("Soil bearing", footing, service=service)
    assert bearing.ratio == pytest.approx((1.0e6 + weight) / 2500.0**2 / 0.15)
    sliding = _check("Sliding", footing, service=[FootingLoad((100e3, 0.0, 1.0e6))])
    assert sliding.ratio == pytest.approx(1.5 / (0.45 * (1.0e6 + weight) / 100e3))


def test_uplift_of_the_whole_footing_fails() -> None:
    result = check_footing(_footing(), [FootingLoad((0.0, 0.0, -2.0e6))], [])
    assert result.governing is not None and result.governing.ratio == math.inf


def test_strength_uplift_requires_verification() -> None:
    result = check_footing(_footing(), [], [FootingLoad((0.0, 0.0, -1.0e5))])
    assert result.requires_verification


def test_rectangular_footing_checks_the_short_direction_band() -> None:
    footing = _footing(length_x=3000.0, width_y=2000.0)
    names = {c.name for c in check_footing(footing, [], [FootingLoad((0, 0, 1e6))]).checks}
    assert "Short-direction band (Y bars)" in names


def test_minimum_depth_and_development() -> None:
    thin = _footing(thickness=200.0)
    assert _check("Minimum depth", thin).ratio > 1.0
    assert development_length(16.0, 21.0, 420.0) == pytest.approx(
        420.0 / (2.1 * math.sqrt(21.0)) * 16.0
    )
    assert development_length(8.0, 69.0, 420.0) == 300.0


def test_required_steel_inverts_the_strength() -> None:
    As = required_steel(300e6, 2500.0, 500.0, 21.0, 420.0)
    phi_mn, _phi = flexural_strength(As, 2500.0, 500.0, 21.0, 420.0)
    assert phi_mn == pytest.approx(300e6, rel=1e-6)


def test_moment_transfer_raises_punching() -> None:
    plain = _check("Two-way shear (punching)", _footing(), strength=[FootingLoad((0, 0, 1.5e6))])
    bent = _check(
        "Two-way shear (punching)",
        _footing(),
        strength=[FootingLoad((0, 0, 1.5e6), (0.0, 100e6, 0.0))],
    )
    assert bent.ratio > plain.ratio


def test_sizing_finds_a_passing_footing() -> None:
    service = [FootingLoad((0.0, 0.0, 800e3), label="S")]
    strength = [FootingLoad((0.0, 0.0, 1.2e6), (0.0, 50e6, 0.0), label="U")]
    sized = size_footing(_footing(length_x=1000.0, width_y=1000.0), service, strength)
    assert sized is not None
    result = check_footing(sized, service, strength)
    assert result.governing is not None and result.governing.ratio <= 1.0
    smaller = check_footing(
        _footing(length_x=sized.length_x - 50.0, width_y=sized.width_y - 50.0), service, []
    )
    assert smaller.ratio("Soil bearing") > 1.0 or smaller.ratio("Soil contact") > 1.0


def test_plate_support_area() -> None:
    common = dict(
        node_id=1, length_x=2.0, width_y=1.5, thickness=0.5, column_x=0.5, column_y=0.6,
        fc=21e6, fy=420e6, cover=0.075, bar_x_diameter=0.016, bar_x_spacing=0.2,
        bar_y_diameter=0.016, bar_y_spacing=0.2, concrete_weight=23.6e3, soil_weight=18e3,
        bearing_allowable=150e3,
    )  # fmt: skip
    assert FootingDesign(**common).plate_support_area() == pytest.approx(3.0)  # type: ignore[arg-type]
    with_pedestal = FootingDesign(**common, pedestal_height=0.8)  # type: ignore[arg-type]
    assert with_pedestal.plate_support_area() == pytest.approx(0.3)
