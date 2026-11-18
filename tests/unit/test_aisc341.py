"""AISC 341-22 Tables D1.1a and D1.1b: the width-to-thickness limits."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.aisc341 import (
    JointBeam,
    JointColumn,
    admissible,
    alpha_s,
    ca,
    continuity_plate_thickness,
    continuity_tlim,
    cpr,
    joint_scwb,
    limit,
    mbe_star,
    member_limits,
    mpc_star,
    mpr,
    panel_zone_demand,
    panel_zone_strength,
    scwb_exempt,
    scwb_ratio,
    system_ductility,
)

E, RY, FY = 29000.0, 1.1, 50.0
ROOT = math.sqrt(E / (RY * FY))


def test_alpha_s_is_the_lrfd_asd_pair() -> None:
    assert alpha_s("LRFD") == 1.0
    assert alpha_s("ASD") == 1.5
    with pytest.raises(ValueError, match="LRFD"):
        alpha_s("WSD")  # type: ignore[arg-type]


def test_ca_follows_the_footnote_b() -> None:
    # Ca = Pr / (alpha_s Ry Fy Ag)
    assert ca(1000.0, RY, FY, 20.0) == pytest.approx(1000.0 / (1.0 * RY * FY * 20.0))
    assert ca(1000.0, RY, FY, 20.0, method="ASD") == pytest.approx(1000.0 / (1.5 * RY * FY * 20.0))
    assert ca(-50.0, RY, FY, 20.0) == 0.0
    with pytest.raises(ValueError, match="positive"):
        ca(1.0, 0.0, FY, 20.0)


@pytest.mark.parametrize(
    ("case", "high", "moderate"),
    [
        (1, 0.30, 0.38),
        (2, 0.55, 0.64),
        (3, 0.038, 0.044),
        (4, 1.49, 1.49),
        (5, 1.40, 2.26),
        (6, 0.076, 0.15),
        (7, 0.30, 0.38),
        (8, 0.47, 0.54),
        (12, 0.55, 1.00),
        (14, 0.55, 0.64),
        (15, 0.064, 1.67),
        (16, 0.038, 0.070),
        (17, 1.40, 2.26),
        (18, 0.076, 0.15),
    ],
)
def test_simple_cases_are_coefficient_times_root(case: int, high: float, moderate: float) -> None:
    assert limit(case, E, RY, FY, ductility="high") == pytest.approx(high * ROOT)
    assert limit(case, E, RY, FY, ductility="moderate") == pytest.approx(moderate * ROOT)


def test_h_piles_have_only_a_moderately_ductile_limit() -> None:
    assert limit(9, E, RY, FY, ductility="moderate") == pytest.approx(0.45 * ROOT)
    assert limit(10, E, RY, FY, ductility="moderate") == pytest.approx(1.50 * ROOT)
    with pytest.raises(ValueError, match="no highly ductile limit"):
        limit(9, E, RY, FY, ductility="high")


def test_case_11_is_the_new_deep_column_expression() -> None:
    # lambda = 2.5 (1 - Ca)^2.3 sqrt(E/(RyFy)) and 5.4 for moderately ductile.
    assert limit(11, E, RY, FY, ca_value=0.0) == pytest.approx(2.5 * ROOT)
    assert limit(11, E, RY, FY, ca_value=0.5) == pytest.approx(2.5 * 0.5**2.3 * ROOT)
    assert limit(11, E, RY, FY, ductility="moderate", ca_value=0.5) == pytest.approx(
        5.4 * 0.5**2.3 * ROOT
    )
    # Ca above 1 never makes the limit negative.
    assert limit(11, E, RY, FY, ca_value=1.4) == pytest.approx(0.0)


def test_case_13_switches_at_0_113_and_has_a_floor() -> None:
    low_high = limit(13, E, RY, FY, ca_value=0.0)
    low_md = limit(13, E, RY, FY, ductility="moderate", ca_value=0.0)
    assert low_high == pytest.approx(2.45 * ROOT)
    assert low_md == pytest.approx(3.76 * ROOT)
    high_high = limit(13, E, RY, FY, ca_value=0.5)
    high_md = limit(13, E, RY, FY, ductility="moderate", ca_value=0.5)
    assert high_high == pytest.approx(2.26 * (1.0 - 0.38 * 0.5) * ROOT)
    assert high_md == pytest.approx(2.61 * (1.0 - 0.49 * 0.5) * ROOT)
    # The floor of 1.56 sqrt(E/(RyFy)) holds at both branches.
    assert limit(13, E, RY, FY, ca_value=0.0) >= 1.56 * ROOT
    assert limit(13, E, RY, FY, ca_value=2.0) == pytest.approx(1.56 * ROOT)


def test_the_case_11_limit_drops_fast_with_axial_load() -> None:
    ratios = [limit(11, E, RY, FY, ca_value=c) / ROOT for c in (0.0, 0.2, 0.5, 0.8)]
    assert ratios == sorted(ratios, reverse=True)
    assert ratios[1] == pytest.approx(2.5 * 0.8**2.3)


def test_admissible_compares_with_a_tiny_tolerance() -> None:
    cap = limit(7, E, RY, FY)
    assert admissible(cap, 7, E, RY, FY)
    assert not admissible(cap * 1.001, 7, E, RY, FY)


def test_unknown_cases_and_ductility_are_refused() -> None:
    with pytest.raises(ValueError, match="1 to 18"):
        limit(19, E, RY, FY)
    with pytest.raises(ValueError, match="ductility"):
        limit(7, E, RY, FY, ductility="low")  # type: ignore[arg-type]


def _shape(name: str):  # type: ignore[no-untyped-def]
    from opensees_studio.core import UnitSystem
    from opensees_studio.services.steel_design import shape_in_units

    return shape_in_units(name, UnitSystem.US_IN_KIP)


def test_every_system_maps_to_its_ductility_class() -> None:
    assert system_ductility("SMF") == "high"
    assert system_ductility("SCBF") == "high"
    assert system_ductility("IMF") == "moderate"
    assert system_ductility("OCBF") == "moderate"
    assert system_ductility("none") is None
    with pytest.raises(ValueError, match="Unknown seismic system"):
        system_ductility("X")


def test_an_i_beam_checks_its_flange_and_moment_frame_web() -> None:
    hits = member_limits(_shape("W14X99"), role="beam", system="SMF", e=E, ry=RY, fy=FY)
    assert [(h.element, h.case) for h in hits] == [("Flange", 7), ("Web", 11)]
    assert hits[0].ratio == pytest.approx(14.6 / (2 * 0.78), rel=1e-6)
    assert hits[1].limit == pytest.approx(2.5 * ROOT)


def test_the_same_i_shape_in_a_brace_uses_table_d1_1a_for_the_web() -> None:
    hits = member_limits(_shape("W14X99"), role="brace", system="SCBF", e=E, ry=RY, fy=FY)
    assert [(h.element, h.case) for h in hits] == [("Flange", 7), ("Web", 4)]
    assert hits[1].limit == pytest.approx(1.49 * ROOT)


def test_a_braced_frame_column_uses_case_13_with_ca() -> None:
    hits = member_limits(
        _shape("W14X99"),
        role="column",
        system="SCBF",
        e=E,
        ry=RY,
        fy=FY,
        ca_value=0.5,
    )
    assert [h.case for h in hits] == [7, 13]
    assert hits[1].limit == pytest.approx(2.26 * (1 - 0.38 * 0.5) * ROOT)


def test_hss_and_pipe_use_their_own_cases() -> None:
    rect = member_limits(_shape("HSS8X8X1/2"), role="brace", system="SCBF", e=E, ry=RY, fy=FY)
    assert [h.case for h in rect] == [2, 2]
    rect_column = member_limits(
        _shape("HSS8X8X1/2"), role="column", system="SMF", e=E, ry=RY, fy=FY
    )
    assert [h.case for h in rect_column] == [12, 12]
    pipe = member_limits(_shape("Pipe10STD"), role="column", system="IMF", e=E, ry=RY, fy=FY)
    assert [h.case for h in pipe] == [16]


def test_no_system_means_no_seismic_checks() -> None:
    assert member_limits(_shape("W14X99"), role="beam", system="none", e=E, ry=RY, fy=FY) == []


def test_utilization_is_ratio_over_limit() -> None:
    hits = member_limits(_shape("W14X99"), role="beam", system="SMF", e=E, ry=RY, fy=FY)
    assert hits[0].utilization == pytest.approx(hits[0].ratio / hits[0].limit)


def test_cpr_and_mpr_follow_aisc_358() -> None:
    assert cpr(50.0, 65.0) == pytest.approx(1.15)
    assert cpr(50.0, 100.0) == pytest.approx(1.2)
    assert cpr(50.0, None) == pytest.approx(1.2)
    assert mpr(1.1, 50.0, 100.0, fu=65.0) == pytest.approx(1.15 * 1.1 * 50.0 * 100.0)
    with pytest.raises(ValueError, match="positive"):
        mpr(0.0, 50.0, 100.0)


def test_mpc_star_reduces_the_column_for_axial_force() -> None:
    # Zc (Fyc - alpha_s Pr / Ag)
    assert mpc_star(100.0, 50.0, 500.0, 20.0) == pytest.approx(2500.0)
    assert mpc_star(100.0, 50.0, 500.0, 20.0, method="ASD") == pytest.approx(1250.0)
    # A column at its yield force contributes nothing.
    assert mpc_star(100.0, 50.0, 2000.0, 20.0) == 0.0
    with pytest.raises(ValueError, match="Ag"):
        mpc_star(100.0, 50.0, 500.0, 0.0)


def test_mbe_star_adds_the_amplified_shear_moment() -> None:
    assert mbe_star(6000.0, 200.0) == pytest.approx(6200.0)
    assert mbe_star(6000.0, 200.0, method="ASD") == pytest.approx(6300.0)


def test_scwb_ratio_and_the_beamless_case() -> None:
    assert scwb_ratio(5000.0, 4000.0) == pytest.approx(1.25)
    assert scwb_ratio(5000.0, 0.0) == pytest.approx(math.inf)


def test_scwb_exception_needs_a_light_column_and_a_listed_case() -> None:
    pyc = 50.0 * 20.0
    assert scwb_exempt(100.0, pyc, one_story_or_top=True)
    assert not scwb_exempt(400.0, pyc, one_story_or_top=True)
    assert scwb_exempt(100.0, pyc, story_shear_share=0.10, line_shear_share=0.20)
    assert not scwb_exempt(100.0, pyc, story_shear_share=0.25, line_shear_share=0.20)
    assert not scwb_exempt(100.0, pyc)


def test_joint_scwb_sums_the_columns_and_projects_the_beam_shear() -> None:
    columns = [
        JointColumn(zc=100.0, fyc=50.0, ag=20.0, pr=500.0, depth=14.0),
        JointColumn(zc=80.0, fyc=50.0, ag=18.0, pr=300.0, depth=14.0),
    ]
    beams = [JointBeam(zb=50.0, fyb=50.0, length=240.0, shear=100.0)]
    pair = joint_scwb(columns, beams, ry=1.1, fu=65.0)
    assert pair is not None
    mpc, mbe = pair
    assert mpc == pytest.approx(100.0 * 25.0 + 80.0 * (50.0 - 300.0 / 18.0))
    # Mpr = 1.15 x 1.1 x 50 x 50; Vp is the larger of 2Mpr/L and 100.
    probable = 1.15 * 1.1 * 50.0 * 50.0
    expected_mbe = probable + 100.0 * 14.0 / 2.0
    assert mbe == pytest.approx(expected_mbe)
    assert mpc / mbe == pytest.approx(1.337, abs=1e-3)


def test_joint_scwb_needs_both_a_column_and_a_beam() -> None:
    column = JointColumn(100.0, 50.0, 20.0, 100.0, 14.0)
    beam = JointBeam(50.0, 50.0, 240.0, 10.0)
    assert joint_scwb([], [beam], ry=1.1) is None
    assert joint_scwb([column], [], ry=1.1) is None


def test_panel_zone_demand_uses_the_face_moments_and_column_shear() -> None:
    assert panel_zone_demand(5000.0, 18.0, 0.6, 50.0) == pytest.approx(5000.0 / 17.4 - 50.0)
    # The column shear cannot make the demand negative.
    assert panel_zone_demand(100.0, 18.0, 0.6, 500.0) == 0.0
    with pytest.raises(ValueError, match="clear depth"):
        panel_zone_demand(100.0, 0.5, 0.6, 10.0)


def test_panel_zone_strength_follows_j10_11_and_j10_12() -> None:
    base = 0.60 * 50.0 * 14.0 * 0.5
    flange = 1.0 + 3.0 * 10.0 * 0.8**2 / (18.0 * 14.0 * 0.5)
    low = panel_zone_strength(50.0, 14.0, 0.5, 10.0, 0.8, 18.0, 100.0, 1500.0)
    assert low == pytest.approx(0.90 * base * flange)
    high = panel_zone_strength(50.0, 14.0, 0.5, 10.0, 0.8, 18.0, 1200.0, 1500.0)
    assert high == pytest.approx(0.90 * base * flange * (1.9 - 1.2 * 1200.0 / 1500.0))
    elastic = panel_zone_strength(50.0, 14.0, 0.5, 10.0, 0.8, 18.0, 100.0, 1500.0, inelastic=False)
    assert elastic == pytest.approx(0.90 * base)
    asd = panel_zone_strength(50.0, 14.0, 0.5, 10.0, 0.8, 18.0, 100.0, 1500.0, method="ASD")
    assert asd == pytest.approx(base * flange / 1.67)


def test_panel_zone_strength_refuses_a_zero_dimension() -> None:
    with pytest.raises(ValueError, match="positive"):
        panel_zone_strength(50.0, 0.0, 0.5, 10.0, 0.8, 18.0, 100.0, 1500.0)


def test_continuity_plate_limits_follow_e3_6f() -> None:
    assert continuity_tlim(7.5) == pytest.approx(0.6 * math.sqrt(7.5))
    assert continuity_plate_thickness([0.57], two_sided=False) == pytest.approx(0.285)
    assert continuity_plate_thickness([0.57, 0.63], two_sided=True) == pytest.approx(0.4725)
    with pytest.raises(ValueError, match="positive"):
        continuity_tlim(0.0)


def test_joint_scwb_uses_the_rbs_hinge_moment_and_shear() -> None:
    columns = [JointColumn(100.0, 50.0, 20.0, 100.0, 14.0)]
    beams = [
        JointBeam(
            zb=50.0,
            fyb=50.0,
            length=240.0,
            shear=10.0,
            mpr_override=5000.0,
            mv_override=600.0,
        )
    ]
    pair = joint_scwb(columns, beams, ry=1.1, fu=65.0)
    assert pair is not None
    _mpc, mbe = pair
    assert mbe == pytest.approx(5000.0 + 600.0)


def test_the_expected_brace_strength_follows_f2_3() -> None:
    from opensees_studio.core.design.aisc341 import expected_brace_strength
    from opensees_studio.core.design.aisc360 import Steel
    from opensees_studio.core.units import UnitSystem
    from opensees_studio.services.steel_design import ishape_in_units

    shape = ishape_in_units("W18X50", UnitSystem.US_IN_KIP)
    steel = Steel(FY, E, 11200.0)
    short = expected_brace_strength(shape, steel, ry=RY, length_x=10.0, length_y=10.0)
    assert short.tension == pytest.approx(RY * FY * shape.A)
    assert short.compression == pytest.approx(short.tension)
    assert short.post_buckling == pytest.approx(0.3 * short.compression)

    slender = expected_brace_strength(shape, steel, ry=RY, length_x=280.0, length_y=280.0)
    assert slender.tension == pytest.approx(short.tension)
    assert 0.0 < slender.compression < slender.tension
    assert slender.post_buckling == pytest.approx(0.3 * slender.compression)
    with pytest.raises(ValueError, match="positive"):
        expected_brace_strength(shape, steel, ry=0.0, length_x=10.0, length_y=10.0)


def test_the_ocbf_brace_slenderness_limit_is_f1_1() -> None:
    from opensees_studio.core.design.aisc341 import ocbf_brace_slenderness_limit

    assert ocbf_brace_slenderness_limit(E, FY) == pytest.approx(4.0 * math.sqrt(E / FY))
    with pytest.raises(ValueError, match="positive"):
        ocbf_brace_slenderness_limit(0.0, FY)
