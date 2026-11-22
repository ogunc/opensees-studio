"""Combined footings (core.design.combined_footing) and their service and drawing.

The hand case: two 400 mm columns 4 m apart, 1000 kN each, on a 6 m by 1.5 m
footing 700 mm thick. The net pressure is a uniform line load of
2000 kN / 6 m = 333.3 N/mm: 106.7 kN·m sagging at the outer faces (an 800 mm
cantilever) and 500 kN·m hogging at mid-span (w 3000²/2 - P 2000).
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from opensees_studio.core.design.combined_footing import (
    CombinedFooting,
    CombinedLoad,
    FootingColumn,
    beam_diagram,
    check_combined_footing,
    combined_actions,
    size_combined_footing,
)
from opensees_studio.core.design.footing import FootingLoad, soil_pressure
from opensees_studio.core.design.footing_solids import footing_solids
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
from opensees_studio.services.footings import (
    all_footing_reports,
    check_combined_footings,
    check_footings,
    combined_in_si,
    default_combined,
    default_footing,
    footing_supports,
    pressure_grid,
    size_combined_design,
)
from tests.unit.test_footings_service import _setup


def _footing(**kw: object) -> CombinedFooting:
    columns = (FootingColumn(-2000.0, 0.0, 400.0, 400.0, label="A"),
               FootingColumn(2000.0, 0.0, 400.0, 400.0, label="B"))  # fmt: skip
    data: dict[str, object] = dict(
        length_x=6000.0, width_y=1500.0, thickness=700.0, columns=columns,
        bar_x_spacing=150.0, bar_y_spacing=150.0, top_bar_diameter=16.0, top_bar_spacing=150.0,
    )  # fmt: skip
    data.update(kw)
    return CombinedFooting(**data)  # type: ignore[arg-type]


def _load(p1: float = 1.0e6, p2: float = 1.0e6, label: str = "U") -> CombinedLoad:
    return CombinedLoad((FootingLoad((0.0, 0.0, p1)), FootingLoad((0.0, 0.0, p2))), label)


def _check(name: str, result):  # type: ignore[no-untyped-def]
    (found,) = [c for c in result.checks if c.name == name]
    return found


def test_beam_statics_by_hand() -> None:
    f = _footing()
    p = soil_pressure(6000.0, 1500.0, 2.0e6, 0.0, 0.0)
    assert p is not None
    d = beam_diagram(f, p, _load(), np.array([-2200.0, 0.0, 2200.0]))
    w = 2.0e6 / 6000.0
    assert d.moment[0] == pytest.approx(w * 800.0**2 / 2.0, rel=1e-3)
    assert d.moment[1] == pytest.approx(w * 3000.0**2 / 2.0 - 1.0e6 * 2000.0, rel=1e-3)
    assert d.shear[1] == pytest.approx(0.0, abs=1e3)
    result = check_combined_footing(f, [], [_load()])
    assert "Mu+ = 106.7" in _check("Flexure, bottom (X bars)", result).value
    assert "Mu- = 500" in _check("Flexure, top (X bars)", result).value


def test_hogging_without_top_bars_fails() -> None:
    result = check_combined_footing(_footing(top_bar_diameter=0.0), [], [_load()])
    assert _check("Flexure, top (X bars)", result).ratio == math.inf


def test_one_way_shear_at_d_from_the_inner_face() -> None:
    f = _footing()
    result = check_combined_footing(f, [], [_load()])
    w = 2.0e6 / 6000.0
    section = -2000.0 + 200.0 + f.d_x
    vu = abs(w * (section + 3000.0) - 1.0e6)
    value = _check("One-way shear (X direction)", result).value
    reported = float(value.split("Vu = ")[1].split(" kN")[0])
    assert reported == pytest.approx(vu / 1e3, rel=1e-2)


def test_resultant_and_unequal_columns() -> None:
    f = _footing()
    act = combined_actions(f, _load(1.0e6, 0.5e6), with_weight=False)
    assert act.n == pytest.approx(1.5e6)
    # Resultant towards the heavier column at x = -2000.
    assert act.ex == pytest.approx((1.0e6 * -2000.0 + 0.5e6 * 2000.0) / 1.5e6)
    result = check_combined_footing(f, [_load(1.0e6, 0.5e6, "S")], [])
    assert result.pressure is not None and result.pressure.b < 0.0


def test_per_column_checks_and_long_axis_along_y() -> None:
    columns = (FootingColumn(0.0, -2000.0, 400.0, 400.0, label="A"),
               FootingColumn(0.0, 2000.0, 400.0, 400.0, label="B"))  # fmt: skip
    along_y = _footing(length_x=1500.0, width_y=6000.0, columns=columns)
    assert along_y.axis == "y"
    result = check_combined_footing(along_y, [], [_load()])
    names = {c.name for c in result.checks}
    assert {"Flexure, top (Y bars)", "Two-way shear (punching)", "Bearing on the footing"} <= names
    assert "Transverse flexure under the columns (X bars)" in names
    x_case = check_combined_footing(_footing(), [], [_load()])
    assert _check("Flexure, top (Y bars)", result).ratio == pytest.approx(
        _check("Flexure, top (X bars)", x_case).ratio, rel=0.05
    )


def test_sizing_a_combined_footing() -> None:
    service, strength = [_load(0.7e6, 0.7e6, "S")], [_load()]
    sized = size_combined_footing(_footing(width_y=1000.0), service, strength)
    assert sized is not None and sized.length_x == 6000.0
    result = check_combined_footing(sized, service, strength)
    assert result.governing is not None and result.governing.ratio <= 1.0


# ── service, persistence, drawing ─────────────────────────────────────
def _portal_settings():  # type: ignore[no-untyped-def]
    project, results = _setup({101: (2.0, 150.0, 100.0)})
    settings = DesignSettings(load_sets=[DesignLoadSet(source="case", ref_id=101)])
    combined = default_combined(project, [1, 2], settings)
    return project, results, settings.model_copy(update={"combined_footings": [combined]})


def test_default_combined_footing_spans_the_supports() -> None:
    project, _results, settings = _portal_settings()
    combined = settings.combined_footings[0]
    assert combined.node_ids == [1, 2]
    assert combined.center_x == pytest.approx(120.0)
    assert combined.length_x > 240.0
    si = combined_in_si(project, combined)
    assert si.axis == "x"
    assert [c.x for c in si.columns] == pytest.approx([-120.0 * 25.4, 120.0 * 25.4])


def test_supports_on_a_combined_footing_get_no_isolated_one() -> None:
    project, results, settings = _portal_settings()
    isolated = [default_footing(s, project.meta.units) for s in footing_supports(project)]
    settings = settings.model_copy(update={"footings": isolated})
    assert check_footings(project, results, settings) == []
    (report,) = check_combined_footings(project, results, settings)
    assert report.label.startswith("CF-") and report.node_ids == (1, 2)
    assert report.status in ("OK", "NG") and report.pressure is not None
    assert len(all_footing_reports(project, results, settings)) == 1
    grid = pressure_grid(report, project.meta.units, n=10)
    assert grid is not None and grid[2].max() == pytest.approx(report.q_max, rel=0.05)
    sized = size_combined_design(project, results, settings, settings.combined_footings[0])
    assert sized is not None


def test_combined_footings_round_trip_and_stay_out_when_unused() -> None:
    _project, _results, settings = _portal_settings()
    assert "combined_footings" not in json.loads(DesignSettings().model_dump_json())
    again = DesignSettings.model_validate_json(settings.model_dump_json())
    assert again == settings


def test_footing_solids_under_the_supports() -> None:
    project, _results, settings = _portal_settings()
    single = default_footing(footing_supports(project)[0], project.meta.units).model_copy(
        update={"node_id": 1, "pedestal_height": 20.0}
    )
    combined = settings.combined_footings[0]
    combined = combined.model_copy(
        update={
            "columns": [c.model_copy(update={"pedestal_height": 30.0}) for c in combined.columns]
        }
    )
    solids = footing_solids(project, settings.model_copy(update={"combined_footings": [combined]}))
    kinds = sorted(s.kind for s in solids)
    assert kinds == ["footing", "pedestal", "pedestal"]
    footing = next(s for s in solids if s.kind == "footing")
    assert footing.z == pytest.approx((-30.0 - combined.thickness, -30.0))
    # An isolated footing is drawn when its node is not on a combined one.
    alone = footing_solids(project, DesignSettings(footings=[single]))
    assert sorted(s.kind for s in alone) == ["footing", "pedestal"]
    assert next(s for s in alone if s.kind == "pedestal").z == pytest.approx((-20.0, 0.0))
    assert footing_solids(project, None) == []
