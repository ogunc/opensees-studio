"""AISC 341-22 gusset plates: Whitmore width, yielding and buckling."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.gussets import (
    gusset_buckling,
    gusset_checks,
    gusset_yielding,
    whitmore_width,
)


def test_whitmore_width_spreads_at_30_degrees() -> None:
    assert whitmore_width(10.0, 0.5) == pytest.approx(2.0 * 10.0 * math.tan(math.pi / 6) + 0.5)
    assert whitmore_width(10.0) == pytest.approx(2.0 * 10.0 * math.tan(math.pi / 6))
    with pytest.raises(ValueError, match="positive"):
        whitmore_width(0.0)


def test_gusset_yielding_is_fy_b_t() -> None:
    strength = gusset_yielding(50.0, 12.0, 0.5)
    assert strength.nominal == pytest.approx(300.0)
    assert strength.available == pytest.approx(0.9 * 300.0)
    assert [step.label for step in strength.steps] == ["Gusset area", "Nominal strength"]


def test_gusset_buckling_uses_the_plate_radius_of_gyration() -> None:
    r = 0.5 / math.sqrt(12.0)
    slenderness = 0.65 * 10.0 / r
    fe = math.pi**2 * 29000.0 / slenderness**2
    fcr = 0.658 ** (50.0 / fe) * 50.0
    strength = gusset_buckling(50.0, 29000.0, 12.0, 0.5, 10.0)
    assert strength.nominal == pytest.approx(fcr * 12.0 * 0.5)
    assert "Slenderness" in [step.label for step in strength.steps]
    assert strength.available == pytest.approx(0.9 * strength.nominal)


def test_the_three_checks_compare_the_expected_brace_force() -> None:
    checks = gusset_checks(
        fy=50.0,
        e=29000.0,
        width=12.0,
        thickness=0.5,
        whitmore_length=10.0,
        free_length=10.0,
        demand=200.0,
        brace_thickness=0.5,
    )
    assert [check.name for check in checks] == [
        "Gusset Whitmore width",
        "Gusset yielding",
        "Gusset buckling",
    ]
    assert checks[0].ratio == pytest.approx(whitmore_width(10.0, 0.5) / 12.0)
    assert checks[1].ratio == pytest.approx(200.0 / (0.9 * 300.0))
    assert checks[2].ratio > 0.0


def test_a_zero_dimension_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        gusset_yielding(50.0, 0.0, 0.5)
    with pytest.raises(ValueError, match="positive"):
        gusset_buckling(50.0, 29000.0, 12.0, 0.0, 10.0)
