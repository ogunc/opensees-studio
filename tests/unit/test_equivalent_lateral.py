"""Equivalent lateral force: the code formulas, by hand, and the storey distribution."""

from __future__ import annotations

import math

import numpy as np
import pytest

from opensees_studio.core import Node, Project, RigidDiaphragm, Storey
from opensees_studio.core.equivalent_lateral import (
    ElfError,
    ElfParameters,
    approximate_period,
    asce7_cs,
    asce7_k,
    equivalent_lateral_forces,
    nodal_forces,
    tbdy_sar,
)
from opensees_studio.core.units import gravity

G = gravity(Project().meta.units)  # SI m: 9.80665


def _asce(**kw) -> ElfParameters:  # type: ignore[no-untyped-def]
    base = dict(code="asce7_16", period=0.4, sds=1.0, sd1=0.6, r=8.0, importance=1.0, tl=8.0)
    return ElfParameters(**{**base, **kw})  # type: ignore[arg-type]


def _tbdy(**kw) -> ElfParameters:  # type: ignore[no-untyped-def]
    base = dict(
        code="tbdy2018", period=0.4, sds=1.0, sd1=0.6, r=8.0, importance=1.0, overstrength_d=3.0
    )
    return ElfParameters(**{**base, **kw})  # type: ignore[arg-type]


# ─────────────────────────── ASCE 7-16 ───────────────────────────
def test_asce_cs_is_sds_over_r_on_the_plateau() -> None:
    cs, why = asce7_cs(_asce(period=0.4))  # SD1 / (T R/Ie) = 0.1875 > 0.125
    assert cs == pytest.approx(1.0 / 8.0)
    assert "12.8-2" in why


def test_asce_cs_is_capped_by_sd1_over_t() -> None:
    cs, why = asce7_cs(_asce(period=1.2))
    assert cs == pytest.approx(0.6 / (1.2 * 8.0))
    assert "12.8-3" in why


def test_asce_cs_beyond_tl() -> None:
    cs, why = asce7_cs(_asce(period=10.0, tl=4.0, r=3.0))
    # 0.6 * 4 / (100 * 3) = 0.008 < the 0.044 SDS Ie floor
    assert cs == pytest.approx(0.044)
    assert "12.8-5" in why


def test_asce_near_fault_minimum() -> None:
    cs, why = asce7_cs(_asce(period=2.0, s1=0.8))
    assert cs == pytest.approx(0.5 * 0.8 / 8.0)
    assert "12.8-6" in why


@pytest.mark.parametrize(
    ("period", "k"), [(0.3, 1.0), (0.5, 1.0), (1.5, 1.5), (2.5, 2.0), (4.0, 2.0)]
)
def test_asce_distribution_exponent(period: float, k: float) -> None:
    assert asce7_k(period) == pytest.approx(k)


# ─────────────────────────── TBDY 2018 ───────────────────────────
def test_tbdy_ra_is_r_over_i_past_tb_and_ramps_from_d_below() -> None:
    # TB = SD1 / SDS = 0.6 s
    sar, ra = tbdy_sar(_tbdy(period=1.2))
    assert ra == pytest.approx(8.0)
    assert sar == pytest.approx((0.6 / 1.2) / 8.0)
    sar, ra = tbdy_sar(_tbdy(period=0.3))
    assert ra == pytest.approx(3.0 + (8.0 - 3.0) * 0.3 / 0.6)
    assert sar == pytest.approx(1.0 / ra)


# ─────────────────────────── the distribution ───────────────────────────
def _shear_building(ndm: int = 3, storeys: bool = True) -> Project:
    """Three floors of 4 joints at z = 3, 6, 9, 10 t each (2.5 t per joint)."""
    nodes = []
    nid = 1
    for z in (0.0, 3.0, 6.0, 9.0):
        for x, y in ((0.0, 0.0), (6.0, 0.0), (0.0, 4.0), (6.0, 4.0)):
            if ndm == 2 and y:
                continue
            m = 0.0 if z == 0.0 else (2.5 if ndm == 3 else 5.0)
            nodes.append(Node(id=nid, coords=(x, y, z), mass=(m, m, m, 0.0, 0.0, 0.0)))
            nid += 1
    project = Project(ndm=ndm, ndf=6 if ndm == 3 else 3, nodes=nodes)
    if storeys:
        project.storeys = [Storey(id=k, name=f"S{k}", elevation=3.0 * k) for k in (1, 2, 3)]
    return project


def test_asce_forces_follow_weight_times_height() -> None:
    result = equivalent_lateral_forces(_shear_building(), 0, _asce(period=0.4))
    w = 10.0 * G
    assert result.total_weight == pytest.approx(3 * w)
    assert result.base_shear == pytest.approx(3 * w / 8.0)
    forces = [lv.force for lv in result.levels]
    assert forces == pytest.approx([result.base_shear * h / 18.0 for h in (3.0, 6.0, 9.0)])
    assert sum(forces) == pytest.approx(result.base_shear)


def test_tbdy_adds_the_top_force_and_respects_the_minimum() -> None:
    result = equivalent_lateral_forces(_shear_building(), 1, _tbdy(period=1.2))
    w = 3 * 10.0 * G
    vt = max(w * (0.5 / 8.0), 0.04 * 1.0 * w)
    assert result.base_shear == pytest.approx(vt)
    top = 0.0075 * 3 * vt
    forces = [lv.force for lv in result.levels]
    rest = vt - top
    assert forces[:2] == pytest.approx([rest * 3 / 18, rest * 6 / 18])
    assert forces[2] == pytest.approx(rest * 9 / 18 + top)
    low = equivalent_lateral_forces(_shear_building(), 0, _tbdy(period=3.0, r=8.0))
    assert low.base_shear == pytest.approx(0.04 * w)  # the minimum governs
    assert "minimum" in low.notes[0]


def test_levels_come_from_the_masses_without_storeys() -> None:
    result = equivalent_lateral_forces(_shear_building(storeys=False), 0, _asce())
    assert [lv.elevation for lv in result.levels] == [3.0, 6.0, 9.0]


def test_a_2d_model_takes_x_only_and_nothing_without_mass_is_refused() -> None:
    with pytest.raises(ElfError, match="X only"):
        equivalent_lateral_forces(_shear_building(ndm=2), 1, _asce())
    empty = Project(ndm=3, ndf=6, nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))])
    with pytest.raises(ElfError, match="No storey carries mass"):
        equivalent_lateral_forces(empty, 0, _asce())


def test_nodal_forces_share_the_storey_force_by_mass() -> None:
    project = _shear_building()
    result = equivalent_lateral_forces(project, 0, _asce())
    loads = nodal_forces(project, result)
    top = result.levels[-1]
    assert sum(loads[n][0] for n in top.nodes) == pytest.approx(top.force)
    assert all(loads[n][0] == pytest.approx(top.force / 4) for n in top.nodes)


def test_eccentricity_moves_the_resultant_by_five_percent() -> None:
    project = _shear_building()
    result = equivalent_lateral_forces(project, 0, _asce())
    loads = nodal_forces(project, result, eccentricity_sign=1, ratio=0.05)
    coords = {n.id: n.coords for n in project.nodes}
    top = result.levels[-1]
    total = sum(loads[n][0] for n in top.nodes)
    centroid_y = sum(loads[n][0] * coords[n][1] for n in top.nodes) / total
    assert total == pytest.approx(top.force)
    assert centroid_y == pytest.approx(2.0 + 0.05 * 4.0)  # floor 4 m deep in Y


def test_a_diaphragm_takes_the_force_and_the_torque_at_its_retained_node() -> None:
    project = _shear_building()
    top = [n.id for n in project.nodes if n.coords[2] == 9.0]
    project.nodes.append(
        Node(id=99, coords=(3.0, 2.0, 9.0), mass=(10.0, 10.0, 0.0, 0.0, 0.0, 50.0))
    )
    project.nodes = [
        n.model_copy(update={"mass": (0.0,) * 6}) if n.id in top else n for n in project.nodes
    ]
    project.diaphragms = [
        RigidDiaphragm(id=1, perp_dirn=3, retained_node=99, constrained_nodes=tuple(top))
    ]
    result = equivalent_lateral_forces(project, 1, _asce())
    loads = nodal_forces(project, result, eccentricity_sign=-1, ratio=0.05)
    force = result.levels[-1].force
    assert loads[99][1] == pytest.approx(force)
    # Load along Y, e = -0.05 x 6 m along X: Mz = F e.
    assert loads[99][5] == pytest.approx(force * -0.3)
    assert all(n not in loads for n in top)


def test_approximate_periods() -> None:
    assert approximate_period("asce7_16", "concrete_mrf", 30.0, 1.0) == pytest.approx(
        0.0466 * 30.0**0.9
    )
    assert approximate_period("tbdy2018", "concrete_frame", 30.0, 1.0) == pytest.approx(
        0.1 * 30.0**0.75
    )
    # 100 ft in feet units is 30.48 m
    assert approximate_period("asce7_16", "other", 100.0, 0.3048) == pytest.approx(
        0.0488 * 30.48**0.75
    )
    assert math.isfinite(approximate_period("tbdy2018", "other", 1.0, 1.0))
    assert np.isclose(approximate_period("tbdy2018", "other", 1.0, 1.0), 0.05)
