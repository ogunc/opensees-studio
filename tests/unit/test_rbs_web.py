"""AISC 358-22 5.5: RBS beam web connection checks."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.rbs_web import web_connection_checks


def _checks(**overrides: float):
    values = {
        "vu": 100.0,
        "plate_thickness": 0.5,
        "plate_height": 12.0,
        "bolt_count": 4,
        "bolt_diameter": 0.75,
        "bolt_fnv": 54.0,
        "hole_allowance": 0.0625,
        "weld_leg": 0.375,
        "weld_fexx": 70.0,
        "fy": 50.0,
        "fu": 65.0,
        "min_thickness": 0.375,
    }
    values.update(overrides)
    return web_connection_checks(**values)  # type: ignore[arg-type]


def test_the_bolted_plate_checks_follow_5_5() -> None:
    checks, notes = _checks()
    names = [check.name for check in checks]
    assert names == [
        "Web plate thickness (5.5)",
        "Web plate shear yielding (5.5)",
        "Web plate shear rupture (5.5)",
        "Web bolts in shear (5.5)",
        "Web plate weld minimum leg (5.5)",
        "Web plate fillet weld (5.5)",
    ]
    by_name = {check.name: check for check in checks}
    assert by_name["Web plate thickness (5.5)"].ratio == pytest.approx(0.75)
    assert by_name["Web plate shear yielding (5.5)"].capacity == pytest.approx(
        0.60 * 50.0 * 0.5 * 12.0
    )
    net_height = 12.0 - 4 * (0.75 + 0.0625)
    assert by_name["Web plate shear rupture (5.5)"].capacity == pytest.approx(
        0.75 * 0.60 * 65.0 * 0.5 * net_height
    )
    bolt_area = math.pi * 0.75**2 / 4.0
    assert by_name["Web bolts in shear (5.5)"].capacity == pytest.approx(
        0.75 * 4 * 54.0 * bolt_area
    )
    assert by_name["Web plate weld minimum leg (5.5)"].demand == pytest.approx(0.625 * 0.5)
    assert any("bearing" in note for note in notes)


def test_cjp_only_checks_the_backing_plate_thickness() -> None:
    checks, notes = _checks(connection_type="cjp")  # type: ignore[arg-type]
    assert [check.name for check in checks] == ["Web plate thickness (5.5)"]
    assert any("CJP" in note for note in notes)
    assert any("demand critical" in note for note in notes)


def test_asd_divides_the_capacities_by_the_safety_factors() -> None:
    lrfd, _ = _checks()
    asd, _ = _checks(method="ASD")
    lrfd_by_name = {check.name: check for check in lrfd}
    asd_by_name = {check.name: check for check in asd}
    assert asd_by_name["Web plate shear yielding (5.5)"].capacity == pytest.approx(
        lrfd_by_name["Web plate shear yielding (5.5)"].capacity / 1.5
    )
    assert asd_by_name["Web bolts in shear (5.5)"].capacity == pytest.approx(
        lrfd_by_name["Web bolts in shear (5.5)"].capacity * (0.5 / 0.75)
    )


def test_a_thin_plate_and_a_missing_weld_are_reported() -> None:
    checks, notes = _checks(plate_thickness=0.25, weld_leg=None)
    by_name = {check.name: check for check in checks}
    assert by_name["Web plate thickness (5.5)"].ratio > 1.0
    assert "Web plate fillet weld (5.5)" not in by_name
    assert any("weld leg was not given" in note for note in notes)


def test_the_inputs_are_guarded() -> None:
    with pytest.raises(ValueError, match="negative"):
        _checks(vu=-1.0)
    with pytest.raises(ValueError, match="positive"):
        _checks(plate_thickness=0.0)
    with pytest.raises(ValueError, match="bolt"):
        _checks(bolt_count=0)
