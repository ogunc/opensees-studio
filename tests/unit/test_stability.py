"""AISC 360 Chapter C: notional loads and the stiffness reduction factor."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import (
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    Storey,
    UnitSystem,
)
from opensees_studio.core.design.stability import (
    ALPHA_ASD,
    ALPHA_LRFD,
    NOTIONAL_FRACTION,
    b1,
    gravity_weight_per_node,
    notional_alpha,
    notional_factor,
    notional_loads,
    notional_pattern,
    pe1,
    storey_notional_loads,
    tau_b,
)


def _two_storey() -> Project:
    """A 2D two-storey frame with 10 kN of dead load on each floor."""
    return Project(
        meta=ProjectMeta(units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 3.0)),
            Node(id=3, coords=(0.0, 0.0, 6.0)),
        ],
        storeys=[
            Storey(id=1, name="Level 1", elevation=3.0),
            Storey(id=2, name="Level 2", elevation=6.0),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="D",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=2, forces=(0.0, 0.0, -10.0, 0.0, 0.0, 0.0)),
                    NodalLoad(node_id=3, forces=(0.0, 0.0, -10.0, 0.0, 0.0, 0.0)),
                ],
            )
        ],
    )


def test_tau_b_follows_the_two_branches() -> None:
    assert tau_b(0.0, 100.0) == pytest.approx(1.0)
    assert tau_b(50.0, 100.0) == pytest.approx(1.0)
    assert tau_b(75.0, 100.0) == pytest.approx(0.75)
    assert tau_b(100.0, 100.0) == pytest.approx(0.0)
    assert tau_b(120.0, 100.0) == pytest.approx(0.0)
    assert tau_b(10.0, 0.0) == pytest.approx(1.0)


def test_tau_b_scales_the_service_force_by_alpha_in_asd() -> None:
    # C2-2 uses alpha Pr / Pns: 40 kN in ASD counts as 1.6 x 40 = 64 kN.
    assert tau_b(40.0, 100.0, alpha=ALPHA_LRFD) == pytest.approx(1.0)
    assert tau_b(40.0, 100.0, alpha=ALPHA_ASD) == pytest.approx(4.0 * 0.64 * (1.0 - 0.64))


def test_notional_factor_is_0_002_alpha() -> None:
    assert notional_alpha("LRFD") == ALPHA_LRFD
    assert notional_alpha("ASD") == ALPHA_ASD
    assert notional_factor() == pytest.approx(NOTIONAL_FRACTION)
    assert notional_factor(method="ASD") == pytest.approx(NOTIONAL_FRACTION * 1.6)
    with pytest.raises(ValueError, match="LRFD"):
        notional_alpha("WSD")


def test_gravity_weight_comes_from_the_dead_pattern() -> None:
    project = _two_storey()
    weights = gravity_weight_per_node(project)
    assert weights[2] == pytest.approx(10.0)
    assert weights[3] == pytest.approx(10.0)


def test_notional_loads_are_0_002_of_each_storey_weight() -> None:
    project = _two_storey()
    levels = storey_notional_loads(project)
    assert [level.name for level in levels] == ["Level 1", "Level 2"]
    assert [level.weight for level in levels] == pytest.approx([10.0, 10.0])
    assert [level.force for level in levels] == pytest.approx([0.02, 0.02])
    loads = notional_loads(project)
    assert sum(load.forces[0] for load in loads) == pytest.approx(0.04)
    assert all(load.forces[0] > 0.0 for load in loads)


def test_asd_uses_1_6_times_the_lrfd_notional_load() -> None:
    project = _two_storey()
    lrfd = notional_loads(project)
    asd = notional_loads(project, method="ASD")
    assert sum(load.forces[0] for load in asd) == pytest.approx(
        1.6 * sum(load.forces[0] for load in lrfd)
    )


def test_a_notional_pattern_is_a_plain_pattern() -> None:
    project = _two_storey()
    pattern = notional_pattern(project, pattern_id=7, time_series_id=1)
    assert pattern.id == 7
    assert pattern.name == "NOTIONAL X"
    assert pattern.time_series_id == 1
    assert len(pattern.nodal_loads) == 2
    assert sum(load.forces[0] for load in pattern.nodal_loads) == pytest.approx(0.04)


def test_the_y_direction_is_refused_in_a_2d_model() -> None:
    project = _two_storey()
    with pytest.raises(ValueError, match="only the global X"):
        notional_loads(project, direction=1)


def test_pe1_is_the_euler_load_in_the_plane_of_bending() -> None:
    assert pe1(29000.0, 1000.0, 120.0) == pytest.approx(math.pi**2 * 29000.0 * 1000.0 / 120.0**2)
    assert pe1(29000.0, 1000.0, 120.0, k=2.0) == pytest.approx(
        math.pi**2 * 29000.0 * 1000.0 / 240.0**2
    )
    with pytest.raises(ValueError, match="positive"):
        pe1(29000.0, 1000.0, 0.0)


def test_b1_follows_a_8_3_and_never_drops_below_one() -> None:
    assert b1(0.0, 1000.0) == pytest.approx(1.0)
    assert b1(100.0, 1000.0) == pytest.approx(1.0 / (1.0 - 0.1))
    assert b1(100.0, 1000.0, alpha=ALPHA_ASD) == pytest.approx(1.0 / (1.0 - 1.6 * 0.1))
    # A member past its elastic critical load has no finite amplifier.
    assert b1(1000.0, 1000.0) == math.inf
    assert b1(1200.0, 1000.0) == math.inf
