"""Base plates (AISC DG1, ACI 318 Ch. 17) and bolted connections, by hand."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.base_plate import BasePlate, bearing_limit, check_base_plate
from opensees_studio.core.design.bolt_groups import eccentric_bolt_group, prying_action

# SI (m, N, Pa): W310x97-ish column on a 450 x 400 x 25 mm plate, f'c = 25 MPa.
PLATE = BasePlate(
    d=0.308,
    bf=0.305,
    n_length=0.45,
    b_width=0.40,
    tp=0.025,
    fy=250e6,
    fc=25e6,
    a2=4 * 0.45 * 0.40,
    rods_tension=2,
    rods_total=4,
    rod_diameter=0.024,
    rod_futa=400e6,
    rod_offset=0.17,
    rod_spacing=0.25,
    edge_distance=0.3,
    embedment=0.4,
)


def test_bearing_limit_doubles_with_a2_four_times_a1() -> None:
    assert bearing_limit(PLATE) == pytest.approx(0.65 * min(0.85 * 25e6 * 2.0, 1.7 * 25e6))


def test_concentric_load_by_hand() -> None:
    pu = 2.0e6
    result = check_base_plate(PLATE, pu=pu)
    fp = pu / (0.45 * 0.40)
    checks = {c.name: c.ratio for c in result.checks}
    assert checks["Concrete bearing"] == pytest.approx(fp / bearing_limit(PLATE))
    m = (0.45 - 0.95 * 0.308) / 2
    n = (0.40 - 0.8 * 0.305) / 2
    x = 4 * 0.308 * 0.305 / (0.308 + 0.305) ** 2 * fp / bearing_limit(PLATE)
    lam = min(1.0, 2 * math.sqrt(x) / (1 + math.sqrt(1 - x)))
    length = max(m, n, lam * math.sqrt(0.308 * 0.305) / 4)
    t_req = length * math.sqrt(2 * pu / (0.9 * 250e6 * 0.40 * 0.45))
    assert checks["Plate thickness (bearing)"] == pytest.approx(t_req / 0.025)


def test_small_eccentricity_keeps_the_rods_out_of_tension() -> None:
    result = check_base_plate(PLATE, pu=1.0e6, mu=0.02e6)  # e = 20 mm
    assert result.eccentricity == pytest.approx(0.02)
    assert result.bearing_length == pytest.approx(0.45 - 0.04)
    assert result.anchor_tension == 0.0


def test_large_eccentricity_puts_the_rods_in_tension_by_hand() -> None:
    pu, mu = 0.5e6, 0.20e6  # e = 0.4 m
    result = check_base_plate(PLATE, pu=pu, mu=mu)
    q_max = bearing_limit(PLATE) * 0.40
    f, n_half = 0.17, 0.225
    y = (f + n_half) - math.sqrt((f + n_half) ** 2 - 2 * pu * (0.4 + f) / q_max)
    assert result.bearing_length == pytest.approx(y)
    assert result.anchor_tension == pytest.approx(q_max * y - pu)
    names = {c.name for c in result.checks}
    assert {"Anchor rod steel in tension", "Concrete breakout of the rods in tension"} <= names


def test_shear_takes_the_larger_of_friction_and_rods() -> None:
    result = check_base_plate(PLATE, pu=1.0e6, vu=0.2e6)
    shear = next(c for c in result.checks if c.name.startswith("Shear"))
    friction = 0.75 * 0.55 * 1.0e6
    rods = 4 * 0.65 * 0.6 * 0.75 * math.pi * 0.024**2 / 4 * 400e6
    assert shear.ratio == pytest.approx(0.2e6 / max(friction, rods))


def test_a_thick_flange_has_no_prying() -> None:
    thick = prying_action(
        t=0.05,
        fu=450e6,
        b=0.04,
        a=0.04,
        db=0.02,
        hole=0.022,
        pitch=0.08,
        bolt_tension=150e3,
        demand=100e3,
    )
    assert thick.q == 1.0 and thick.available == pytest.approx(150e3)


def test_a_thin_flange_loses_tension_to_prying_by_hand() -> None:
    t, fu, b, a, db, hole, p, bolt = 0.012, 450e6, 0.04, 0.04, 0.02, 0.022, 0.08, 150e3
    thin = prying_action(
        t=t, fu=fu, b=b, a=a, db=db, hole=hole, pitch=p, bolt_tension=bolt, demand=60e3
    )
    b_p = b - db / 2
    a_p = min(a, 1.25 * b) + db / 2
    rho, delta = b_p / a_p, 1 - hole / p
    tc = math.sqrt(4 * bolt * b_p / (0.9 * p * fu))
    alpha = min(max(((tc / t) ** 2 - 1) / (delta * (1 + rho)), 0.0), 1.0)
    assert thin.q == pytest.approx(min(1.0, (t / tc) ** 2 * (1 + delta * alpha)))
    assert thin.available < bolt


def test_eccentric_bolt_group_elastic_method_by_hand() -> None:
    # Four bolts at the corners of a 100 x 100 square, a vertical load 200 to the right.
    bolts = [(0.0, 0.0), (0.1, 0.0), (0.0, 0.1), (0.1, 0.1)]
    result = eccentric_bolt_group(bolts, px=0.0, py=100e3, ex=0.25, ey=0.05)
    moment = 100e3 * (0.25 - 0.05)
    ip = 4 * (0.05**2 + 0.05**2)
    # Right-hand bolts: direct 25 kN plus torsion.
    rx = moment * 0.05 / ip
    ry = 25e3 + moment * 0.05 / ip
    assert result.max_force == pytest.approx(math.hypot(rx, ry))
    assert bolts[result.governing][0] == 0.1
