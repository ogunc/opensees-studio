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

A992 = Steel(Fy=50.0, E=29000.0, G=11200.0, Fu=65.0)
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


def test_p_delta_amplifies_the_moments_of_a_member_in_compression() -> None:
    """C2.1b / A-8-3: B1 on the moments, Pe1 on 0.8 EI, Cm = 1.0."""
    shape = _shape("W14X99")
    demand = Demand(-400.0, 250 * FT, 80 * FT, 20.0, 5.0)
    plain = check_member(
        shape, A992, "LRFD", demand, length_x=14 * FT, length_y=14 * FT, length_ltb=14 * FT
    )
    amplified = check_member(
        shape,
        A992,
        "LRFD",
        demand,
        length_x=14 * FT,
        length_y=14 * FT,
        length_ltb=14 * FT,
        p_delta=True,
    )
    pe_major = math.pi**2 * 0.8 * A992.E * shape.Ix / (14 * FT) ** 2
    b_major = 1.0 / (1.0 - 400.0 / pe_major)
    assert b_major > 1.0
    assert amplified.ratios["Major flexure"] == pytest.approx(
        plain.ratios["Major flexure"] * b_major, rel=1e-9
    )
    assert amplified.ratios["P-M interaction"] > plain.ratios["P-M interaction"]
    assert any("B1" in note for note in amplified.notes)
    # The compression-only and shear ratios do not depend on B1.
    assert amplified.ratios["Compression"] == pytest.approx(plain.ratios["Compression"])
    assert amplified.ratios["Major shear"] == pytest.approx(plain.ratios["Major shear"])


def test_p_delta_uses_tau_b_above_half_the_squash_load() -> None:
    """C2.3: Pe1 takes ``0.8 tau_b EI``, so a heavily loaded member amplifies more."""
    shape = _shape("W14X99")
    pr = 0.75 * A992.Fy * shape.A
    demand = Demand(-pr, 100 * FT, 0.0, 0.0, 0.0)
    check = check_member(
        shape,
        A992,
        "LRFD",
        demand,
        length_x=14 * FT,
        length_y=14 * FT,
        length_ltb=14 * FT,
        p_delta=True,
    )
    tau = 4.0 * 0.75 * (1.0 - 0.75)
    pe = math.pi**2 * 0.8 * tau * A992.E * shape.Ix / (14 * FT) ** 2
    expected = 1.0 / (1.0 - pr / pe)
    assert expected == pytest.approx(1.19, abs=0.01)
    plain = check_member(
        shape,
        A992,
        "LRFD",
        Demand(-pr, 100 * FT, 0.0, 0.0, 0.0),
        length_x=14 * FT,
        length_y=14 * FT,
        length_ltb=14 * FT,
    )
    assert check.ratios["Major flexure"] == pytest.approx(
        plain.ratios["Major flexure"] * expected, rel=1e-9
    )


def test_p_delta_leaves_a_member_in_tension_alone() -> None:
    shape = _shape("W14X99")
    demand = Demand(400.0, 250 * FT, 80 * FT, 20.0, 5.0)
    plain = check_member(
        shape, A992, "LRFD", demand, length_x=14 * FT, length_y=14 * FT, length_ltb=14 * FT
    )
    amplified = check_member(
        shape,
        A992,
        "LRFD",
        demand,
        length_x=14 * FT,
        length_y=14 * FT,
        length_ltb=14 * FT,
        p_delta=True,
    )
    assert amplified.ratios == pytest.approx(plain.ratios)
    assert not any("B1" in note for note in amplified.notes)


def test_d2_2_tension_rupture_governs_when_ae_is_small() -> None:
    """D2-2: Fy 50 ksi, Fu 65 ksi, An 20 in2, U 0.9 -> 0.75 * 65 * 18 = 877.5 kip."""
    shape = _shape("W14X99")
    strength = tension(shape, A992, "LRFD", net_area=20.0, shear_lag=0.9)
    assert strength.equation == "D2-2 rupture"
    assert strength.nominal == pytest.approx(65.0 * 18.0)
    assert strength.available == pytest.approx(0.75 * 65.0 * 18.0)
    assert [step.label for step in strength.steps] == ["Effective net area", "D2-2 rupture"]
    assert tension(shape, A992, "ASD", net_area=20.0, shear_lag=0.9).available == pytest.approx(
        65.0 * 18.0 / 2.0
    )


def test_d2_1_yielding_governs_when_the_net_area_is_large() -> None:
    shape = _shape("W14X99")
    strength = tension(shape, A992, "LRFD", net_area=30.0, shear_lag=0.9)
    assert strength.equation == "D2-1 yielding"
    assert strength.available == pytest.approx(0.9 * 50.0 * shape.A)


def test_check_member_uses_the_net_area_for_d2_2() -> None:
    shape = _shape("W14X99")
    check = check_member(
        shape,
        A992,
        "LRFD",
        Demand(
            axial=1000.0,
            moment_major=0.0,
            moment_minor=0.0,
            shear_major=0.0,
            shear_minor=0.0,
        ),
        length_x=14 * FT,
        length_y=14 * FT,
        length_ltb=14 * FT,
        net_area=20.0,
        shear_lag=0.9,
    )
    assert check.equations["Tension"] == "D2-2 rupture"
    assert check.ratios["Tension"] == pytest.approx(1000.0 / (0.75 * 65.0 * 18.0))


def test_f4_noncompact_web_and_flange() -> None:
    """W10X12 at Fy = 200 ksi: h/tw 49.7 is noncompact, the flange is noncompact."""
    shape = _shape("W10X12")
    steel = Steel(Fy=200.0, E=29000.0, G=11200.0)
    classes = slenderness(shape, steel)
    assert classes.web_class == "noncompact"
    strength = flexure_major(shape, steel, "LRFD", unbraced=0.0)
    assert strength.equation.startswith("F4")
    # The compression-flange local buckling equation governs here.
    my = 200.0 * shape.Sx
    mp = min(200.0 * shape.Zx, 1.6 * my)
    fl = 0.7 * 200.0
    mp_my = mp / my
    rpc = min(
        mp_my
        - (mp_my - 1.0)
        * (classes.web - classes.web_compact)
        / (classes.web_noncompact - classes.web_compact),
        mp_my,
    )
    cflb = rpc * my - (rpc * my - fl * shape.Sx) * (
        (classes.flange - classes.flange_compact)
        / (classes.flange_noncompact - classes.flange_compact)
    )
    assert strength.nominal == pytest.approx(cflb)
    labels = [step.label for step in strength.steps]
    assert "Web plastification" in labels and "Lp" in labels and "Lr" in labels
    assert flexure_major(shape, steel, "ASD", unbraced=0.0).available == pytest.approx(
        strength.nominal / 1.67
    )


def test_f5_slender_web() -> None:
    """W10X12 at Fy = 500 ksi: h/tw 49.7 is slender."""
    shape = _shape("W10X12")
    steel = Steel(Fy=500.0, E=29000.0, G=11200.0)
    assert slenderness(shape, steel).web_class == "slender"
    strength = flexure_major(shape, steel, "LRFD", unbraced=0.0)
    assert strength.equation.startswith("F5")
    assert strength.nominal > 0.0
    labels = [step.label for step in strength.steps]
    assert "Web bending factor" in labels and "Lp" in labels and "Lr" in labels
    assert flexure_major(shape, steel, "ASD", unbraced=0.0).available == pytest.approx(
        strength.nominal / 1.67
    )


def test_f4_and_f5_switch_to_elastic_ltb_beyond_lr() -> None:
    shape = _shape("W10X12")
    f4 = flexure_major(shape, Steel(Fy=200.0, E=29000.0, G=11200.0), "LRFD", unbraced=5 * FT)
    assert f4.equation == "F4-3 elastic lateral-torsional buckling"
    f5 = flexure_major(shape, Steel(Fy=500.0, E=29000.0, G=11200.0), "LRFD", unbraced=5 * FT)
    assert f5.equation == "F5-2 lateral-torsional buckling"


def test_check_member_keeps_a_structured_calculation_record() -> None:
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
    assert {c.name for c in check.checks} == {
        "Compression",
        "Major flexure",
        "Minor flexure",
        "Major shear",
        "Minor shear",
        "P-M interaction",
    }
    compression = next(c for c in check.checks if c.name == "Compression")
    assert compression.equation.startswith("E3")
    assert compression.capacity == pytest.approx(
        shape.compression(A992, "LRFD", length_x=14 * FT, length_y=14 * FT).available
    )
    assert compression.steps[-2].label == "Nominal strength"
    assert compression.steps[-1].label == "Available strength"
    assert compression.steps[-1].value == pytest.approx(compression.capacity)
    assert compression.ratio == pytest.approx(400.0 / compression.capacity)
    labels = [step.label for step in compression.steps]
    assert "Elastic buckling" in labels and "Critical stress" in labels
    flexure = next(c for c in check.checks if c.name == "Major flexure")
    flexure_labels = [step.label for step in flexure.steps]
    assert "Lp" in flexure_labels and "Lr" in flexure_labels
    shear = next(c for c in check.checks if c.name == "Major shear")
    assert "Web area" in [step.label for step in shear.steps]
