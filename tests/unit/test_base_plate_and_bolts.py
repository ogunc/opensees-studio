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


# ── Uplift with and without a moment: rod rows and unilateral bearing ─────────
# The case of the correction plan (2026-11-19), in N, mm, MPa: a 500 x 500 x 25 mm
# plate under a 300 x 300 mm column, four 25 mm rods (two per row at f = 200 mm),
# Fy 250 MPa, f'c 28 MPa, futa 517 MPa, no shear and no embedment.
PLAN_PLATE = BasePlate(
    d=300.0,
    bf=300.0,
    n_length=500.0,
    b_width=500.0,
    tp=25.0,
    fy=250.0,
    fc=28.0,
    rods_tension=2,
    rods_total=4,
    rod_diameter=25.0,
    rod_futa=517.0,
    rod_offset=200.0,
    rod_spacing=400.0,
    mpa=1.0,
    mm=1.0,
    newton=1.0,
)
Q_MAX = 0.65 * 0.85 * 28.0 * 500.0  # N/mm, A2 = A1
F, N = 200.0, 500.0


def _by_hand(uplift: float, moment: float) -> tuple[float, float, float]:
    """Independent statics: (near row T, far row T, bearing C) for |moment|."""
    m = abs(moment)
    if m <= uplift * F:  # both rows in tension, no contact
        return uplift / 2 + m / (2 * F), uplift / 2 - m / (2 * F), 0.0
    # far row slack, block at q,max: T - C = U and T f + C (N/2 - Y/2) = M
    y = (F + N / 2) - math.sqrt((F + N / 2) ** 2 - 2 * (m - uplift * F) / Q_MAX)
    c = Q_MAX * y
    return c + uplift, 0.0, c


def _assert_equilibrium(result, uplift: float, moment: float) -> None:  # type: ignore[no-untyped-def]
    plus, minus = result.row_tension
    c = result.bearing_force
    y = result.bearing_length
    assert plus + minus - c == pytest.approx(uplift, abs=1e-6 * max(uplift, 1.0))
    # Bearing sits on the side opposite the pulled row; moment about the centre.
    arm = N / 2 - y / 2 if c else 0.0
    side = 1.0 if moment >= 0 else -1.0
    assert (plus - minus) * F + side * c * arm == pytest.approx(moment, rel=1e-9, abs=1e-3)


def test_pure_uplift_shares_the_rods_equally() -> None:
    result = check_base_plate(PLAN_PLATE, pu=-50e3, mu=0.0)
    assert not result.requires_verification
    assert result.row_tension == pytest.approx((25e3, 25e3))
    assert result.anchor_tension == pytest.approx(25e3)
    ase = 0.75 * math.pi * 25.0**2 / 4.0
    steel = next(c for c in result.checks if c.name == "Anchor rod steel in tension")
    assert steel.ratio == pytest.approx(12.5e3 / (0.75 * ase * 517.0))
    _assert_equilibrium(result, 50e3, 0.0)


@pytest.mark.parametrize(
    ("uplift", "moment"),
    [
        (50e3, 50e6),
        (50e3, -50e6),
        (0.0, 50e6),
        (0.0, -50e6),
        (50e3, 5e6),
        (50e3, -5e6),
        (50e3, 10e6),
    ],
    ids=["U+M", "U-M", "M+", "M-", "U+small M", "U-small M", "U at the limit"],
)
def test_uplift_with_moment_matches_statics(uplift: float, moment: float) -> None:
    result = check_base_plate(PLAN_PLATE, pu=-uplift, mu=moment)
    near, far, c = _by_hand(uplift, moment)

    assert not result.requires_verification
    expected = (near, far) if moment >= 0 else (far, near)
    assert result.row_tension == pytest.approx(expected, rel=1e-9, abs=1e-6)
    assert result.anchor_tension == pytest.approx(near, rel=1e-9)
    assert result.bearing_force == pytest.approx(c, rel=1e-9, abs=1e-6)
    _assert_equilibrium(result, uplift, moment)
    rods = next(ch for ch in result.checks if ch.name == "Anchor rod steel in tension")
    ase = 0.75 * math.pi * 25.0**2 / 4.0
    assert rods.ratio == pytest.approx(near / 2 / (0.75 * ase * 517.0), rel=1e-9)


def test_the_plan_cases_give_their_hand_values() -> None:
    # Uplift 50 kN with 50 kN·m: Y = 11.64 mm, C = 90.05 kN, T = 140.05 kN.
    result = check_base_plate(PLAN_PLATE, pu=-50e3, mu=50e6)
    assert result.bearing_length == pytest.approx(11.642, abs=1e-3)
    assert result.anchor_tension == pytest.approx(140.05e3, rel=1e-4)
    # 50 kN·m with no axial force: T = C = 112.94 kN.
    result = check_base_plate(PLAN_PLATE, pu=0.0, mu=50e6)
    assert result.anchor_tension == pytest.approx(112.94e3, rel=1e-4)
    assert result.bearing_force == pytest.approx(result.anchor_tension)


def test_the_large_moment_branch_is_continuous_with_dg1_under_compression() -> None:
    below = check_base_plate(PLAN_PLATE, pu=-1e-3, mu=50e6)
    above = check_base_plate(PLAN_PLATE, pu=1e-3, mu=50e6)
    assert below.anchor_tension == pytest.approx(above.anchor_tension, rel=1e-6)
    assert below.bearing_length == pytest.approx(above.bearing_length, rel=1e-6)


def test_moment_under_compression_is_unchanged() -> None:
    result = check_base_plate(PLAN_PLATE, pu=500e3, mu=50e6)
    assert result.row_tension == (0.0, 0.0)
    assert result.governing is not None


def test_rounding_noise_in_the_moment_is_not_a_moment() -> None:
    result = check_base_plate(PLAN_PLATE, pu=-50e3, mu=1e-6)
    assert result.row_tension == pytest.approx((25e3, 25e3))


def test_both_rows_in_tension_check_their_breakout_as_one_group() -> None:
    plate = BasePlate(**{**PLAN_PLATE.__dict__, "embedment": 300.0, "edge_distance": 450.0})
    result = check_base_plate(plate, pu=-50e3, mu=5e6)
    group = next(c for c in result.checks if "group" in c.name)
    hef = 300.0
    nb = 10.0 * math.sqrt(28.0) * hef**1.5
    anc = min((2 * 1.5 * hef + 400.0) * (2 * 1.5 * hef + 2 * 200.0), 4 * 9 * hef**2)
    assert group.ratio == pytest.approx(50e3 / (0.70 * anc / (9 * hef**2) * nb), rel=1e-9)


def test_tension_without_rod_data_requires_verification() -> None:
    plate = BasePlate(**{**PLAN_PLATE.__dict__, "rod_diameter": 0.0})
    result = check_base_plate(plate, pu=-50e3, mu=50e6)
    assert result.requires_verification
    assert "Requires verification" in " ".join(result.notes)


def test_a_too_small_plate_cannot_bear_the_moment() -> None:
    result = check_base_plate(PLAN_PLATE, pu=0.0, mu=5e9)
    assert result.governing is not None and result.governing.ratio == math.inf
