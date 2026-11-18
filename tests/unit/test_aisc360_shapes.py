"""AISC 360-16 strengths of channels, tees, angles and HSS, against hand calculations.

Each test writes the Specification's equation out with the shape's tabulated
values (kip and inch, Fy = 50 ksi, E = 29 000 ksi, G = 11 200 ksi), so a wrong
branch or a wrong constant in the module shows up as a different number. Where
the AISC Manual tabulates the result, the test says so.
"""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.aisc360 import Demand, Steel, check_member
from opensees_studio.core.design.aisc360_shapes import (
    Channel,
    EqualLegAngle,
    RectHSS,
    RoundHSS,
    Tee,
)
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.steel_design import shape_in_units, shape_name

STEEL = Steel(Fy=50.0, E=29000.0, G=11200.0)
FT = 12.0
KIP_IN = UnitSystem.US_IN_KIP


def _fcr(fy: float, fe: float) -> float:
    return 0.658 ** (fy / fe) * fy if fy / fe <= 2.25 else 0.877 * fe


def test_names_resolve_whatever_the_spelling() -> None:
    assert shape_name("c12x20.7") == "C12X20_7"
    assert shape_name("HSS8x8x1/2") == "HSS8X8X1_2"
    assert shape_name("pipe10std") == "Pipe10STD"
    assert shape_name("W 14 x 90") == "W14X90"


def test_each_family_gets_its_class() -> None:
    kinds = {
        "C12X20.7": Channel,
        "MC10X22": Channel,
        "WT9X17.5": Tee,
        "L4X4X1/2": EqualLegAngle,
        "HSS12X6X1/2": RectHSS,
        "HSS10.000X0.500": RoundHSS,
        "Pipe10STD": RoundHSS,
    }
    for name, kind in kinds.items():
        assert isinstance(shape_in_units(name, KIP_IN), kind), name


def test_unequal_leg_angles_are_refused() -> None:
    with pytest.raises(ValueError, match="unequal legs"):
        shape_in_units("L4X3X1/2", KIP_IN)


def test_shapes_scale_to_si() -> None:
    hss = shape_in_units("HSS8X8X1/2", UnitSystem.SI_M_N)
    assert isinstance(hss, RectHSS)
    assert pytest.approx(8 * 0.0254) == hss.H
    assert hss.Zx == pytest.approx(37.5 * 0.0254**3, rel=1e-3)


# ──────────────────────────── rectangular HSS ────────────────────────────
def test_square_hss_flexure_is_the_plastic_moment() -> None:
    """HSS8X8X1/2: compact walls, φMn = 0.9 Fy Zx = 140.6 kip-ft."""
    hss = shape_in_units("HSS8X8X1/2", KIP_IN)
    strength = hss.flexure_major(STEEL, "LRFD", unbraced=20 * FT)
    assert strength.equation == "F7-1 yielding"
    assert strength.available / FT == pytest.approx(0.9 * 50 * 37.5 / FT, rel=1e-9)


def test_slender_hss_flange_uses_the_effective_section_modulus() -> None:
    """HSS8X8X3/16: b/t above 1.40 sqrt(E/Fy), so F7-3 with the effective width F7-4."""
    hss = shape_in_units("HSS8X8X3/16", KIP_IN)
    assert isinstance(hss, RectHSS)
    t = 0.93 * 0.1875
    b = 8.0 - 3 * t
    root = math.sqrt(29000 / 50)
    assert b / t > 1.40 * root
    be = 1.92 * t * root * (1 - 0.38 / (b / t) * root)
    lost = (b - be) * t
    arm = (8.0 - t) / 2
    shift = lost * arm / (hss.A - lost)
    se = (hss.Ix - lost * arm**2 - (hss.A - lost) * shift**2) / (4.0 + shift)
    strength = hss.flexure_major(STEEL, "LRFD", unbraced=0.0)
    assert strength.equation == "F7-3 flange local buckling"
    assert strength.nominal == pytest.approx(50 * se, rel=1e-9)
    assert se < hss.Sx


def test_hss_shear_on_the_two_webs() -> None:
    """G4: h = H - 3t, Aw = 2 h t, Cv2 = 1 for a stocky web."""
    hss = shape_in_units("HSS12X6X1/2", KIP_IN)
    t = 0.93 * 0.5
    expected = 0.9 * 0.6 * 50 * 2 * (12 - 3 * t) * t
    assert hss.shear_major(STEEL, "LRFD", length=10 * FT).available == pytest.approx(expected)
    expected_minor = 0.9 * 0.6 * 50 * 2 * (6 - 3 * t) * t
    assert hss.shear_minor(STEEL, "LRFD", length=10 * FT).available == pytest.approx(expected_minor)


def test_hss_column_buckles_about_its_weak_axis() -> None:
    hss = shape_in_units("HSS12X6X1/2", KIP_IN)
    assert isinstance(hss, RectHSS)
    fe = math.pi**2 * 29000 / (15 * FT / hss.ry) ** 2
    strength = hss.compression(STEEL, "LRFD", length_x=15 * FT, length_y=15 * FT)
    assert strength.equation == "E3-1 (E3-4 about y)"
    assert strength.available == pytest.approx(0.9 * _fcr(50, fe) * hss.A)


def test_deep_hss_loses_strength_to_lateral_torsional_buckling() -> None:
    """F7-10 / F7-11 apply only to a rectangular HSS bent about its major axis."""
    hss = shape_in_units("HSS12X4X3/16", KIP_IN)
    assert isinstance(hss, RectHSS)
    mp = 50 * hss.Zx
    root_ja = math.sqrt(hss.J * hss.A)
    lp = 0.13 * 29000 * hss.ry * root_ja / mp
    lr = 2 * 29000 * hss.ry * root_ja / (0.7 * 50 * hss.Sx)
    long = 1.5 * lr
    strength = hss.flexure_major(STEEL, "LRFD", unbraced=long)
    elastic = min(2 * 29000 * root_ja / (long / hss.ry), mp)
    assert strength.nominal <= elastic + 1e-9
    assert lp < lr
    assert hss.flexure_minor(STEEL, "LRFD", unbraced=long).equation != "F7-11 LTB"


# ──────────────────────────── round HSS and pipe ────────────────────────────
def test_compact_pipe_reaches_its_plastic_moment() -> None:
    pipe = shape_in_units("Pipe10STD", KIP_IN)
    assert isinstance(pipe, RoundHSS)
    assert pipe.slenderness <= 0.07 * 29000 / 50
    strength = pipe.flexure_major(STEEL, "LRFD", unbraced=30 * FT)
    assert strength.equation == "F8-1 yielding"
    assert strength.available == pytest.approx(0.9 * 50 * 36.9)


def test_thin_round_hss_flexure_and_compression() -> None:
    """HSS20.000X0.250: D/t = 86 — noncompact in flexure (F8-2), slender in compression (E7-6)."""
    hss = shape_in_units("HSS20.000X0.250", KIP_IN)
    assert isinstance(hss, RoundHSS)
    ratio = 20.0 / (0.93 * 0.25)
    assert 0.07 * 580 < ratio <= 0.31 * 580
    flexure = hss.flexure_major(STEEL, "LRFD", unbraced=0.0)
    assert flexure.equation == "F8-2 local buckling"
    assert flexure.nominal == pytest.approx((0.021 * 29000 / ratio + 50) * hss.S)
    stub = hss.compression(STEEL, "LRFD", length_x=0.0, length_y=0.0)
    ae = (0.038 * 29000 / (50 * ratio) + 2 / 3) * hss.A
    assert stub.nominal == pytest.approx(50 * ae)
    assert stub.equation.startswith("E7-1")


def test_round_hss_shear_is_capped_at_0_6_fy() -> None:
    hss = shape_in_units("HSS10.000X0.500", KIP_IN)
    strength = hss.shear_major(STEEL, "LRFD", length=10 * FT)
    assert strength.nominal == pytest.approx(0.6 * 50 * hss.A / 2)


# ──────────────────────────── channels ────────────────────────────
def test_channel_lateral_torsional_buckling_uses_c_of_f2_8b() -> None:
    channel = shape_in_units("C12X20.7", KIP_IN)
    assert isinstance(channel, Channel)
    c = (12.0 - 0.501) / 2 * math.sqrt(3.86 / 112.0)
    assert channel.c == pytest.approx(c)
    rts = math.sqrt(math.sqrt(3.86 * 112.0) / 21.5)
    lb = 10 * FT
    jc = 0.369 * c / (21.5 * (12.0 - 0.501))
    fcr = math.pi**2 * 29000 / (lb / rts) ** 2 * math.sqrt(1 + 0.078 * jc * (lb / rts) ** 2)
    strength = channel.flexure_major(STEEL, "LRFD", unbraced=lb)
    assert strength.equation == "F2-3 elastic LTB"
    assert strength.nominal == pytest.approx(min(fcr * 21.5, 50 * 25.6))


def test_channel_flexural_torsional_buckling() -> None:
    """E4-5 about the axis of symmetry (x) governs a channel braced about y; the
    web (h/tw = 39 > 1.49 sqrt(E/Fy)) is slender, so E7 trims it at Fcr."""
    channel = shape_in_units("C12X20.7", KIP_IN)
    assert isinstance(channel, Channel)
    lcx, lcy = 10 * FT, 2 * FT
    xo = channel.xo
    ro2 = xo**2 + (129.0 + 3.86) / 6.08
    h = 1 - xo**2 / ro2
    fex = math.pi**2 * 29000 / (lcx / 4.61) ** 2
    fez = (math.pi**2 * 29000 * 112.0 / lcy**2 + 11200 * 0.369) / (6.08 * ro2)
    fe = (fex + fez) / (2 * h) * (1 - math.sqrt(1 - 4 * fex * fez * h / (fex + fez) ** 2))
    fcr = _fcr(50, fe)
    web, limit = (12.0 - 2 * 0.501) / 0.282, 1.49 * math.sqrt(29000 / 50)
    assert web > limit * math.sqrt(50 / fcr)
    fel = (1.31 * limit / web) ** 2 * 50
    he = (12.0 - 2 * 0.501) * (1 - 0.18 * math.sqrt(fel / fcr)) * math.sqrt(fel / fcr)
    effective = 6.08 - (12.0 - 2 * 0.501 - he) * 0.282
    strength = channel.compression(STEEL, "LRFD", length_x=lcx, length_y=lcy)
    assert strength.equation == "E7-1 (E4-5 flexural-torsional, effective area)"
    assert strength.nominal == pytest.approx(fcr * effective)


def test_channel_shear() -> None:
    channel = shape_in_units("C12X20.7", KIP_IN)
    major = channel.shear_major(STEEL, "LRFD", length=10 * FT)
    assert major.available == pytest.approx(0.9 * 0.6 * 50 * 12.0 * 0.282)
    minor = channel.shear_minor(STEEL, "LRFD", length=10 * FT)
    assert minor.available == pytest.approx(0.9 * 0.6 * 50 * 2 * 2.94 * 0.501)


# ──────────────────────────── tees ────────────────────────────
def test_tee_flexure_takes_the_stem_in_compression_when_it_is_weaker() -> None:
    """WT9X17.5: d/tw = 29.5, between 0.84 and 1.52 sqrt(E/Fy) — F9-17 stem buckling."""
    tee = shape_in_units("WT9X17.5", KIP_IN)
    assert isinstance(tee, Tee)
    ratio = 8.85 / 0.3
    fcr = (1.43 - 0.515 * ratio * math.sqrt(50 / 29000)) * 50
    strength = tee.flexure_major(STEEL, "LRFD", unbraced=0.0)
    assert strength.equation == "F9-16 stem local buckling"
    assert strength.nominal == pytest.approx(fcr * 6.21)


def test_tee_lateral_torsional_buckling_stem_in_compression() -> None:
    tee = shape_in_units("WT9X17.5", KIP_IN)
    lb = 20 * FT
    b = -2.3 * (8.85 / lb) * math.sqrt(7.67 / 0.252)
    mcr = 1.95 * 29000 / lb * math.sqrt(7.67 * 0.252) * (b + math.sqrt(1 + b * b))
    strength = tee.flexure_major(STEEL, "LRFD", unbraced=lb)
    assert strength.nominal == pytest.approx(mcr)
    assert strength.equation == "F9-7 LTB, stem in compression"


def test_tee_centroid_from_the_table() -> None:
    tee = shape_in_units("WT9X17.5", KIP_IN)
    assert isinstance(tee, Tee)
    assert tee.y_bar == pytest.approx(8.85 - 40.1 / 6.21)
    assert tee.Sxc == pytest.approx(40.1 / tee.y_bar)


# ──────────────────────────── angles ────────────────────────────
def test_angle_principal_axes() -> None:
    """L4X4X1/2: x̄ = 1.18 in, rz = 0.776 in (Manual Table 1-7)."""
    angle = shape_in_units("L4X4X1/2", KIP_IN)
    assert isinstance(angle, EqualLegAngle)
    assert angle.x_bar == pytest.approx(1.18, abs=0.01)
    assert angle.rz == pytest.approx(0.776, abs=0.003)
    assert angle.Iw + angle.Iz == pytest.approx(angle.Ix + angle.Iy)


def test_angle_compression_about_z() -> None:
    angle = shape_in_units("L4X4X1/2", KIP_IN)
    assert isinstance(angle, EqualLegAngle)
    lc = 10 * FT
    fe = math.pi**2 * 29000 / (lc / angle.rz) ** 2
    strength = angle.compression(STEEL, "LRFD", length_x=lc, length_y=lc)
    assert strength.equation == "E3-1 (E3-4 about z)"
    assert strength.available == pytest.approx(0.9 * _fcr(50, fe) * angle.A)


def test_angle_flexure_f10() -> None:
    """Geometric-axis bending, no restraint: My = 0.8 Fy Sx, toe in compression."""
    angle = shape_in_units("L4X4X1/2", KIP_IN)
    lb = 10 * FT
    my = 0.8 * 50 * 1.96
    mcr = 0.58 * 29000 * 4.0**4 * 0.5 / lb**2 * (math.sqrt(1 + 0.88 * (lb * 0.5 / 4.0**2) ** 2) - 1)
    expected = (
        min((1.92 - 1.17 * math.sqrt(my / mcr)) * my, 1.5 * my)
        if my / mcr <= 1
        else (0.92 - 0.17 * mcr / my) * mcr
    )
    strength = angle.flexure_major(STEEL, "LRFD", unbraced=lb)
    assert strength.nominal == pytest.approx(min(expected, 1.5 * my))
    assert angle.shear_major(STEEL, "LRFD", length=lb).available == pytest.approx(
        0.9 * 0.6 * 50 * 4.0 * 0.5
    )


def test_a_member_check_runs_on_every_family() -> None:
    demand = Demand(
        axial=-20.0, moment_major=100.0, moment_minor=10.0, shear_major=5.0, shear_minor=1.0
    )
    for name in ("C12X20.7", "WT9X17.5", "L4X4X1/2", "HSS8X8X1/2", "Pipe10STD"):
        check = check_member(
            shape_in_units(name, KIP_IN),
            STEEL,
            "LRFD",
            demand,
            length_x=10 * FT,
            length_y=10 * FT,
            length_ltb=10 * FT,
        )
        assert set(check.ratios) >= {"Compression", "Major flexure", "P-M interaction"}
        assert check.governing[1] > 0
