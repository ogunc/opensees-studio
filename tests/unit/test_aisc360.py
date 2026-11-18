"""AISC 360-16 available strengths against the AISC *Design Examples* (v16.0).

Shapes come from the bundled v16 table in kip and inch, the units of the
examples; Fy = 50 ksi, E = 29 000 ksi, G = 11 200 ksi throughout.
"""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.aisc import get_shape
from opensees_studio.core.design.aisc360 import (
    Demand,
    IShape,
    Steel,
    cb_from_moments,
    check_member,
    compression,
    flexure_major,
    flexure_minor,
    interaction,
    lp_lr,
    shear_major,
    slenderness,
    tension,
)

A992 = Steel(Fy=50.0, E=29000.0, G=11200.0)
FT = 12.0  # in


def _shape(name: str) -> IShape:
    s = get_shape(name)
    assert None not in (s.d, s.bf, s.tw, s.tf, s.zx, s.zy, s.sx, s.sy, s.rx, s.ry, s.iy, s.j, s.cw)
    return IShape(
        name,
        s.area,
        s.d,
        s.bf,
        s.tw,
        s.tf,
        s.ix,
        s.iy,
        s.zx,
        s.zy,
        s.sx,
        s.sy,
        s.rx,
        s.ry,
        s.j,
        s.cw,
    )  # type: ignore[arg-type]


def test_e1a_column_with_pinned_ends() -> None:
    """Example E.1A: W14X132, Lc = 30 ft about both axes: φcPn = 892 kips (Table 4-1a)."""
    strength = compression(_shape("W14X132"), A992, "LRFD", length_x=30 * FT, length_y=30 * FT)
    assert strength.available == pytest.approx(892.0, rel=2e-3)
    assert "about y" in strength.equation  # minor-axis buckling governs
    asd = compression(_shape("W14X132"), A992, "ASD", length_x=30 * FT, length_y=30 * FT)
    assert asd.available == pytest.approx(strength.nominal / 1.67)


def test_f1_1a_braced_beam_is_plastic() -> None:
    """Example F.1-1A: W18X50, continuously braced: φbMn = 379 kip-ft."""
    strength = flexure_major(_shape("W18X50"), A992, "LRFD", unbraced=0.0)
    assert strength.available / FT == pytest.approx(379.0, rel=1e-3)
    assert strength.equation == "F2-1 yielding"


def test_f1_2a_beam_braced_at_third_points() -> None:
    """Example F.1-2A: W18X50, Lb = 11.67 ft, Cb = 1.01: φbMn = 306 kip-ft."""
    lp, lr = lp_lr(_shape("W18X50"), A992)
    assert lp / FT == pytest.approx(5.83, abs=0.01)  # Table 3-2
    assert lr / FT == pytest.approx(16.9, abs=0.1)
    strength = flexure_major(_shape("W18X50"), A992, "LRFD", unbraced=11.67 * FT, cb=1.01)
    assert strength.available / FT == pytest.approx(306.0, rel=3e-3)
    assert strength.equation == "F2-2 inelastic LTB"


def test_elastic_ltb_beyond_lr() -> None:
    shape = _shape("W18X50")
    _, lr = lp_lr(shape, A992)
    strength = flexure_major(shape, A992, "LRFD", unbraced=1.5 * lr)
    assert strength.equation == "F2-3 elastic LTB"
    # F2-4 by hand at Lb = 1.5 Lr.
    rts, ho = shape.rts, shape.ho
    ratio = 1.5 * lr / rts
    fcr = (
        math.pi**2 * A992.E / ratio**2 * math.sqrt(1 + 0.078 * shape.J / (shape.Sx * ho) * ratio**2)
    )
    assert strength.nominal == pytest.approx(fcr * shape.Sx)


def test_g1a_rolled_web_shear() -> None:
    """Example G.1A: W24X62: φvVn = 306 kips with φv = 1.00 (G2.1(a))."""
    strength = shear_major(_shape("W24X62"), A992, "LRFD")
    assert strength.available == pytest.approx(306.0, rel=2e-3)
    assert "Cv1 = 1" in strength.equation
    assert shear_major(_shape("W24X62"), A992, "ASD").available == pytest.approx(
        strength.nominal / 1.50
    )


def test_h1a_capacities_and_interaction() -> None:
    """Example H.1A: W14X99, Lc = Lb = 14 ft: φcPn = 1130 kips, φbMnx = 642, φbMny = 311 kip-ft."""
    shape = _shape("W14X99")
    pc = compression(shape, A992, "LRFD", length_x=14 * FT, length_y=14 * FT).available
    mcx = flexure_major(shape, A992, "LRFD", unbraced=14 * FT).available
    mcy = flexure_minor(shape, A992, "LRFD").available
    assert pc == pytest.approx(1130.0, rel=3e-3)
    assert mcx / FT == pytest.approx(642.0, rel=2e-3)
    assert mcy / FT == pytest.approx(311.0, rel=2e-3)
    # Pr = 400 kips, Mrx = 250 kip-ft, Mry = 80 kip-ft → 0.354 + 8/9 (0.389 + 0.257) = 0.928.
    ratio, equation = interaction(-400.0, pc, 250 * FT, mcx, 80 * FT, mcy)
    assert equation == "H1-1a"
    assert ratio == pytest.approx(0.928, abs=2e-3)


def test_interaction_below_point_two() -> None:
    ratio, equation = interaction(10.0, 100.0, 50.0, 100.0, 0.0, 100.0)
    assert equation == "H1-1b"
    assert ratio == pytest.approx(0.05 + 0.5)


def test_tension_yield() -> None:
    strength = tension(_shape("W14X99"), A992, "LRFD")
    assert strength.available == pytest.approx(0.9 * 50.0 * 29.1)
    assert strength.notes  # rupture is left to the engineer


def test_slender_web_uses_the_effective_area() -> None:
    shape = _shape("W16X26")  # h/tw = 56.8 > 35.9: slender in compression at Fy = 50
    assert slenderness(shape, A992).slender_in_compression
    short = compression(shape, A992, "LRFD", length_x=1.0, length_y=1.0)
    assert "E7" in short.equation
    assert short.nominal < A992.Fy * shape.A


def test_noncompact_flange_reduces_the_plastic_moment() -> None:
    shape = _shape("W6X15")  # bf/2tf = 11.5 > 0.38 √(E/Fy) = 9.15
    assert slenderness(shape, A992).flange_class == "noncompact"
    strength = flexure_major(shape, A992, "LRFD", unbraced=0.0)
    assert strength.equation == "F3-1 flange local buckling"
    assert strength.nominal < A992.Fy * shape.Zx


def test_cb_of_a_uniformly_loaded_span_is_1_14() -> None:
    # M(x) = 4 x (1 - x) for a simply supported span: MA = MC = 0.75, MB = Mmax = 1.
    assert cb_from_moments(1.0, 0.75, 1.0, 0.75) == pytest.approx(1.136, abs=1e-3)
    assert cb_from_moments(0.0, 0.0, 0.0, 0.0) == 1.0


def test_check_member_picks_the_governing_ratio() -> None:
    shape = _shape("W14X99")
    check = check_member(
        shape,
        A992,
        "LRFD",
        Demand(
            axial=-400.0,
            moment_major=250 * FT,
            moment_minor=80 * FT,
            shear_major=20.0,
            shear_minor=5.0,
        ),
        length_x=14 * FT,
        length_y=14 * FT,
        length_ltb=14 * FT,
    )
    key, ratio = check.governing
    assert key == "P-M interaction"
    assert ratio == pytest.approx(0.928, abs=2e-3)
    assert set(check.ratios) == {
        "Compression",
        "Major flexure",
        "Minor flexure",
        "Major shear",
        "Minor shear",
        "P-M interaction",
    }
