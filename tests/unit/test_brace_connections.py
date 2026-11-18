"""AISC 341-22 F2.6c: brace connection demands and gusset welds."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.brace_connections import (
    brace_connection_demands,
    critical_plastic_modulus,
    fillet_weld_capacity,
    gusset_weld_check,
    gusset_weld_required_leg,
)
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.steel_design import shape_in_units


def test_brace_connection_demands_follow_f2_6c() -> None:
    demands = brace_connection_demands(
        ry=1.1,
        fy=50.0,
        ag=14.7,
        expected_compression=210.0,
        plastic_modulus=50.0,
    )
    assert demands.tension == pytest.approx(1.1 * 50.0 * 14.7)
    assert demands.compression == pytest.approx(210.0)
    assert demands.flexure == pytest.approx(1.1 * 1.1 * 50.0 * 50.0)
    assert [step.label for step in demands.steps] == [
        "Required tension",
        "Required compression",
        "Required flexure",
    ]

    asd = brace_connection_demands(
        ry=1.1,
        fy=50.0,
        ag=14.7,
        expected_compression=210.0,
        plastic_modulus=50.0,
        method="ASD",
    )
    assert asd.tension == pytest.approx(demands.tension / 1.5)
    assert asd.compression == pytest.approx(140.0)
    assert asd.flexure == pytest.approx(demands.flexure / 1.5)


def test_a_shape_without_a_plastic_modulus_leaves_flexure_out() -> None:
    shape = shape_in_units("L4X4X1/2", UnitSystem.US_IN_KIP)
    assert critical_plastic_modulus(shape) is None
    demands = brace_connection_demands(
        ry=1.1,
        fy=50.0,
        ag=shape.A,
        expected_compression=100.0,
        plastic_modulus=None,
    )
    assert demands.flexure == 0.0
    assert any("F2.6c.3" in note for note in demands.notes)


def test_the_critical_axis_is_the_minor_one() -> None:
    shape = shape_in_units("W18X50", UnitSystem.US_IN_KIP)
    assert shape.ry < shape.rx
    assert critical_plastic_modulus(shape) == pytest.approx(shape.Zy)

    round_hss = shape_in_units("HSS10.000X0.500", UnitSystem.US_IN_KIP)
    assert critical_plastic_modulus(round_hss) == pytest.approx(round_hss.Z)


def test_the_fillet_weld_strength_is_j2_4() -> None:
    nominal = 2.0 * 0.60 * 70.0 * math.sqrt(0.5) * 0.5
    assert fillet_weld_capacity(fexx=70.0, leg=0.5) == pytest.approx(0.75 * nominal)
    assert fillet_weld_capacity(fexx=70.0, leg=0.5, method="ASD") == pytest.approx(nominal / 2.0)
    assert fillet_weld_capacity(fexx=70.0, leg=0.5, both_sides=False) == pytest.approx(
        0.75 * nominal / 2.0
    )
    with pytest.raises(ValueError, match="positive"):
        fillet_weld_capacity(fexx=0.0, leg=0.5)


def test_the_gusset_weld_check_is_per_unit_length() -> None:
    check = gusset_weld_check(ry=1.1, fy=50.0, thickness=0.5, fexx=70.0, leg=0.5)
    demand = 0.60 * 1.1 * 50.0 * 0.5
    capacity = 0.75 * 2.0 * 0.60 * 70.0 * math.sqrt(0.5) * 0.5
    assert check.demand == pytest.approx(demand)
    assert check.capacity == pytest.approx(capacity)
    assert check.ratio == pytest.approx(demand / capacity)
    assert "F2.6c.4" in check.name


def test_the_required_leg_solves_the_same_equation() -> None:
    leg = gusset_weld_required_leg(ry=1.1, fy=50.0, thickness=0.5, fexx=70.0)
    check = gusset_weld_check(ry=1.1, fy=50.0, thickness=0.5, fexx=70.0, leg=leg)
    assert check.ratio == pytest.approx(1.0)
    assert leg == pytest.approx(
        0.60 * 1.1 * 50.0 * 0.5 / (2.0 * 0.75 * 0.60 * 70.0 * math.sqrt(0.5))
    )
