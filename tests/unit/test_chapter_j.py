"""AISC 360 Chapter J: welds, bolts and affected connection elements."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.chapter_j import (
    block_shear_strength,
    bolt_bearing_strength,
    bolt_shear_strength,
    bolt_tension_strength,
    fillet_weld_strength,
    plate_shear_rupture,
    plate_shear_yielding,
    slip_critical_strength,
)


def test_fillet_weld_j2_4() -> None:
    strength = fillet_weld_strength(fexx=70.0, leg=0.25, length=10.0, both_sides=False)
    throat = 0.70710678 * 0.25
    area = throat * 10.0
    assert strength.nominal == pytest.approx(0.60 * 70.0 * area)
    assert strength.available == pytest.approx(0.75 * strength.nominal)
    asd = fillet_weld_strength(fexx=70.0, leg=0.25, length=10.0, both_sides=False, method="ASD")
    assert asd.available == pytest.approx(strength.nominal / 2.0)


def test_bolt_shear_and_tension_j3_1() -> None:
    area = math.pi * 0.75**2 / 4.0
    shear = bolt_shear_strength(fnv=54.0, diameter=0.75, count=4)
    assert shear.nominal == pytest.approx(4 * 54.0 * area)
    assert shear.available == pytest.approx(0.75 * shear.nominal)
    tension = bolt_tension_strength(fnt=90.0, diameter=0.75, count=4)
    assert tension.nominal == pytest.approx(4 * 90.0 * area)
    assert tension.available == pytest.approx(0.75 * tension.nominal)


def test_bolt_bearing_and_tearout_j3_6() -> None:
    strength = bolt_bearing_strength(
        fu=65.0,
        thickness=0.5,
        diameter=0.75,
        count=4,
        edge_distance=1.5,
        hole_diameter=0.8125,
    )
    clear = 1.5 - 0.8125 / 2.0
    tearout = 1.2 * clear * 0.5 * 65.0
    bearing = 2.4 * 0.75 * 0.5 * 65.0
    assert strength.nominal == pytest.approx(4 * min(bearing, tearout))
    assert strength.available == pytest.approx(0.75 * strength.nominal)


def test_slip_critical_j3_4() -> None:
    standard = slip_critical_strength(mu=0.3, tb=28.0, ns=1, count=4, hole_type="standard")
    assert standard.nominal == pytest.approx(4 * 0.3 * 1.13 * 28.0)
    assert standard.available == pytest.approx(standard.nominal)
    oversized = slip_critical_strength(mu=0.3, tb=28.0, ns=1, count=4, hole_type="oversized")
    assert oversized.available == pytest.approx(0.85 * oversized.nominal)


def test_plate_shear_j4_3_and_j4_4() -> None:
    yielding = plate_shear_yielding(fy=50.0, agv=6.0)
    assert yielding.nominal == pytest.approx(180.0)
    assert yielding.available == pytest.approx(180.0)
    rupture = plate_shear_rupture(fu=65.0, anv=4.375)
    assert rupture.nominal == pytest.approx(170.625)
    assert rupture.available == pytest.approx(0.75 * 170.625)


def test_block_shear_j4_5() -> None:
    strength = block_shear_strength(
        fy=50.0,
        fu=65.0,
        agv=6.0,
        anv=4.375,
        ant=1.0,
    )
    rupture = 0.60 * 65.0 * 4.375 + 65.0
    yield_path = 0.60 * 50.0 * 6.0 + 65.0
    assert strength.nominal == pytest.approx(min(rupture, yield_path))
    nonuniform = block_shear_strength(
        fy=50.0,
        fu=65.0,
        agv=6.0,
        anv=4.375,
        ant=1.0,
        uniform_tension=False,
    )
    assert nonuniform.nominal == pytest.approx(
        min(0.60 * 65.0 * 4.375 + 0.5 * 65.0, 0.60 * 50.0 * 6.0 + 0.5 * 65.0)
    )


def test_chapter_j_inputs_are_guarded() -> None:
    with pytest.raises(ValueError, match="positive"):
        fillet_weld_strength(fexx=0.0, leg=0.25, length=10.0)
    with pytest.raises(ValueError, match="positive"):
        bolt_shear_strength(fnv=54.0, diameter=0.75, count=0)
    with pytest.raises(ValueError, match="positive"):
        plate_shear_yielding(fy=50.0, agv=0.0)
    with pytest.raises(ValueError, match="Unknown hole"):
        slip_critical_strength(
            mu=0.3,
            tb=28.0,
            ns=1,
            count=1,
            hole_type="round",  # type: ignore[arg-type]
        )


def test_fillers_follow_j5() -> None:
    from opensees_studio.core.design.chapter_j import (
        filler_bolt_factor,
        filler_weld_required_leg,
    )

    assert filler_bolt_factor(0.25) == pytest.approx(1.0)
    assert filler_bolt_factor(0.5) == pytest.approx(0.9)
    assert filler_bolt_factor(1.0) == pytest.approx(0.85)
    assert filler_bolt_factor(6.0, threshold=6.0, slope=0.0154) == pytest.approx(1.0)
    assert filler_bolt_factor(10.0, threshold=6.0, slope=0.0154) == pytest.approx(
        1.0 - 0.0154 * 4.0
    )
    assert filler_weld_required_leg(0.25, 0.125) == pytest.approx(0.375)
    assert filler_weld_required_leg(0.25, 0.125, transfers_force=True) == pytest.approx(0.25)


def test_the_filler_reduces_the_bolt_shear() -> None:
    plain = bolt_shear_strength(fnv=54.0, diameter=0.75, count=4)
    filled = bolt_shear_strength(fnv=54.0, diameter=0.75, count=4, filler_thickness=0.5)
    assert filled.nominal == pytest.approx(plain.nominal * 0.9)
    assert any("J5.2" in note for note in filled.notes)


def test_bearing_concrete_and_splice_j6_to_j8() -> None:
    from opensees_studio.core.design.chapter_j import (
        bearing_strength,
        concrete_bearing_strength,
        splice_strength,
    )

    bearing = bearing_strength(fy=50.0, apb=2.0)
    assert bearing.nominal == pytest.approx(180.0)
    assert bearing.available == pytest.approx(0.75 * 180.0)

    full = concrete_bearing_strength(fc=4.0, a1=100.0)
    assert full.nominal == pytest.approx(0.85 * 4.0 * 100.0)
    assert full.available == pytest.approx(0.65 * full.nominal)
    partial = concrete_bearing_strength(fc=4.0, a1=100.0, a2=400.0)
    assert partial.nominal == pytest.approx(1.7 * 4.0 * 100.0)

    splice = splice_strength(nominal=1000.0)
    assert splice.nominal == pytest.approx(1000.0)
    assert splice.available == pytest.approx(1000.0)


def test_flange_local_bending_j10_1() -> None:
    from opensees_studio.core.design.chapter_j import flange_local_bending

    strength = flange_local_bending(fyf=50.0, tf=0.5, bf=6.0, lb=2.0, distance_to_end=20.0)
    assert strength.nominal == pytest.approx(78.125)
    assert strength.available == pytest.approx(0.90 * 78.125)
    near_end = flange_local_bending(fyf=50.0, tf=0.5, bf=6.0, lb=2.0, distance_to_end=4.0)
    assert near_end.nominal == pytest.approx(39.0625)
    assert any("50%" in note for note in near_end.notes)
    short = flange_local_bending(fyf=50.0, tf=0.5, bf=6.0, lb=0.5, distance_to_end=20.0)
    assert short.nominal == pytest.approx(0.0)
    assert short.available == pytest.approx(0.0)
    assert short.equation == "J10-1 not required"


def test_web_local_yielding_j10_2_and_j10_3() -> None:
    from opensees_studio.core.design.chapter_j import web_local_yielding

    far = web_local_yielding(fyw=50.0, tw=0.3, k=1.0, lb=2.0, d=14.0, distance_to_end=20.0)
    assert far.nominal == pytest.approx(105.0)
    assert far.available == pytest.approx(105.0)
    near = web_local_yielding(fyw=50.0, tw=0.3, k=1.0, lb=2.0, d=14.0, distance_to_end=14.0)
    assert near.nominal == pytest.approx(67.5)
    assert near.available == pytest.approx(67.5)


def test_web_local_crippling_j10_4_and_j10_5() -> None:
    from opensees_studio.core.design.chapter_j import web_local_crippling

    far = web_local_crippling(
        fyw=50.0, e=29000.0, tw=0.3, tf=0.5, d=14.0, lb=2.0, distance_to_end=10.0
    )
    assert far.nominal == pytest.approx(134.2227, rel=1e-5)
    assert far.available == pytest.approx(0.75 * far.nominal)
    near = web_local_crippling(
        fyw=50.0, e=29000.0, tw=0.3, tf=0.5, d=14.0, lb=2.0, distance_to_end=5.0
    )
    assert near.nominal == pytest.approx(67.1114, rel=1e-5)
    deep = web_local_crippling(
        fyw=50.0, e=29000.0, tw=0.3, tf=0.5, d=14.0, lb=4.0, distance_to_end=5.0
    )
    assert deep.nominal == pytest.approx(80.4878, rel=1e-5)


def test_web_sidesway_buckling_j10_6_and_j10_7() -> None:
    from opensees_studio.core.design.chapter_j import web_sidesway_buckling

    restrained = web_sidesway_buckling(
        fy=50.0, sx=100.0, mr=1000.0, tw=1.0, tf=0.5, h=10.0, bf=8.0, lb=100.0
    )
    assert restrained.nominal == pytest.approx(5783.04, rel=1e-6)
    assert restrained.available == pytest.approx(0.85 * 5783.04, rel=1e-6)
    unrestrained = web_sidesway_buckling(
        fy=50.0,
        sx=100.0,
        mr=1000.0,
        tw=1.0,
        tf=0.5,
        h=10.0,
        bf=8.0,
        lb=100.0,
        restrained=False,
    )
    assert unrestrained.nominal == pytest.approx(983.04, rel=1e-6)
    low = web_sidesway_buckling(
        fy=50.0, sx=100.0, mr=6000.0, tw=1.0, tf=0.5, h=10.0, bf=8.0, lb=100.0
    )
    assert low.nominal == pytest.approx(2891.52, rel=1e-6)
    not_applicable = web_sidesway_buckling(
        fy=50.0, sx=100.0, mr=1000.0, tw=0.3, tf=0.5, h=12.0, bf=6.0, lb=100.0
    )
    assert not_applicable.nominal == pytest.approx(0.0)
    assert not_applicable.equation == "J10-6/7 not applicable"


def test_web_compression_buckling_j10_8() -> None:
    from opensees_studio.core.design.chapter_j import web_compression_buckling

    strength = web_compression_buckling(
        e=29000.0, fyw=50.0, tw=0.5, h=12.0, distance_to_end=10.0, d=14.0
    )
    assert strength.nominal == pytest.approx(301.0399, rel=1e-5)
    assert strength.available == pytest.approx(0.90 * strength.nominal)
    near_end = web_compression_buckling(
        e=29000.0, fyw=50.0, tw=0.5, h=12.0, distance_to_end=5.0, d=14.0
    )
    assert near_end.nominal == pytest.approx(150.5199, rel=1e-5)
    assert any("50%" in note for note in near_end.notes)


def test_j10_sidesway_constants_follow_the_project_stress_unit() -> None:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck
    from opensees_studio.core.units import (
        UnitSystem,
        length_scale,
        moment_scale,
        stress_scale,
    )
    from opensees_studio.services.steel_design import _chapter_j_strength

    def check(units: UnitSystem, mr: float = 1000.0) -> ChapterJCheck:
        length = length_scale(UnitSystem.US_IN_KIP, units)
        stress = stress_scale(UnitSystem.US_IN_KIP, units)
        moment = moment_scale(UnitSystem.US_IN_KIP, units)
        return ChapterJCheck(
            id=1,
            check_type="web_sidesway_buckling",
            demand=1.0,
            fy=50.0 * stress,
            section_modulus=100.0 * length**3,
            required_moment=mr * moment,
            web_thickness=1.0 * length,
            flange_thickness=0.5 * length,
            clear_web_height=10.0 * length,
            flange_width=8.0 * length,
            bearing_length=100.0 * length,
        )

    cr_high = {
        UnitSystem.US_IN_KIP: 960_000.0,
        UnitSystem.US_FT_KIP: 960_000.0 * 144.0,
        UnitSystem.SI_MM_N: 6.6e6,
        UnitSystem.SI_M_N: 6.6e12,
    }
    cr_low = {
        UnitSystem.US_IN_KIP: 480_000.0,
        UnitSystem.US_FT_KIP: 480_000.0 * 144.0,
        UnitSystem.SI_MM_N: 3.3e6,
        UnitSystem.SI_M_N: 3.3e12,
    }
    for units in cr_high:
        length = length_scale(UnitSystem.US_IN_KIP, units)
        for mr, expected_us, cr_table, cr_us in (
            (1000.0, 5783.04, cr_high, 960_000.0),
            (6000.0, 2891.52, cr_low, 480_000.0),
        ):
            strength = _chapter_j_strength(check(units, mr), "LRFD", units=units)
            expected = expected_us * (cr_table[units] / cr_us) * length**2
            assert strength.nominal == pytest.approx(expected, rel=1e-9)
