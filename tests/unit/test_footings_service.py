"""Design → Footings over hand-made reactions (services.footings), no solver.

The portal of ``test_direct_analysis`` (kip, in, 2D, W14X90 columns on fixed
supports 1 and 2) with one static case per reaction row.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from opensees_studio.core import StaticCase
from opensees_studio.core.combinations import CombinationTerm, LoadCombination
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
from opensees_studio.services.base_plates import check_bases
from opensees_studio.services.footings import (
    check_footings,
    default_footing,
    footing_in_si,
    footing_load_sets,
    footing_loads,
    footing_supports,
    is_service_name,
    size_design,
)
from opensees_studio.services.results import StaticResults
from tests.unit.test_direct_analysis import _portal


def _setup(rows: dict[int, tuple[float, float, float]]):  # type: ignore[no-untyped-def]
    project = _portal()
    results = {}
    for cid, row in rows.items():
        project.analyses.append(StaticCase(id=cid, name=f"C{cid}", pattern_ids=[1]))
        reaction = np.array([row])
        results[cid] = StaticResults(
            case_id=cid, case_name=f"C{cid}", n_steps=1, node_reaction={1: reaction, 2: reaction}
        )
    return project, results


def _with_footings(project, sets):  # type: ignore[no-untyped-def]
    settings = DesignSettings(load_sets=sets)
    supports = footing_supports(project, settings)
    designs = [default_footing(s, project.meta.units, settings) for s in supports]
    return settings.model_copy(update={"footings": designs})


def test_supports_and_the_default_footing_under_a_steel_column() -> None:
    project, _results = _setup({})
    supports = footing_supports(project)
    assert [s.node_id for s in supports] == [1, 2]
    assert supports[0].column == "W14X90"
    design = default_footing(supports[0], project.meta.units)
    # 1.5 m in inches, under the default plate (d + 6 in along X in a 2D frame).
    assert design.length_x == pytest.approx(1500.0 / 25.4)
    assert design.steel_x == pytest.approx(supports[0].base.d)  # type: ignore[union-attr]
    assert design.column_x == pytest.approx(design.steel_x + 6.0)
    si = footing_in_si(design, project.meta.units)
    assert si.fc == pytest.approx(21.0)
    assert si.concrete_weight == pytest.approx(23.6e-6)
    assert si.flex_cx == pytest.approx((design.column_x + design.steel_x) / 2.0 * 25.4)  # type: ignore[operator]


def test_service_names() -> None:
    assert is_service_name("ASD 2: D + L")
    assert is_service_name("Service D+L")
    assert is_service_name("SLS char.")
    assert not is_service_name("LRFD 2: 1.2D + 1.6L")


def test_load_sets_split_by_name_and_fall_back_with_a_note() -> None:
    project, _results = _setup({101: (0.0, 100.0, 0.0)})
    project.combinations = [
        LoadCombination(id=1, name="ASD D", terms=[CombinationTerm(ref_id=101, factor=1.0)]),
        LoadCombination(id=2, name="LRFD 1.4D", terms=[CombinationTerm(ref_id=101, factor=1.4)]),
    ]
    service, strength, notes = footing_load_sets(project, DesignSettings())
    assert [s.ref_id for s in service] == [1]
    assert [s.ref_id for s in strength] == [2]
    assert not notes
    project.combinations = project.combinations[1:]
    service, strength, notes = footing_load_sets(project, DesignSettings())
    assert service == strength and notes


def test_a_2d_reaction_is_in_the_xz_plane_and_scaled_to_n_mm() -> None:
    project, results = _setup({101: (2.0, 100.0, 50.0)})
    sets = [DesignLoadSet(source="case", ref_id=101)]
    settings = DesignSettings(footing_service_sets=sets, footing_strength_sets=sets)
    service, strength, _notes = footing_loads(project, results, settings, 1)
    (load,) = service
    kip = 4448.2216152605
    assert load.force == pytest.approx((2.0 * kip, 0.0, 100.0 * kip))
    assert load.moment == pytest.approx((0.0, 50.0 * kip * 25.4, 0.0))
    assert strength == service


def test_only_footings_asked_for_are_checked() -> None:
    project, results = _setup({101: (0.0, 100.0, 0.0)})
    sets = [DesignLoadSet(source="case", ref_id=101)]
    assert check_footings(project, results, DesignSettings(load_sets=sets)) == []
    settings = _with_footings(project, sets)
    reports = check_footings(project, results, settings)
    assert [r.node_id for r in reports] == [1, 2]
    assert reports[0].status in ("OK", "NG")
    assert reports[0].governing
    assert reports[0].q_max > 0.0
    # No ASD combination: the strength loads checked the soil, and it says so.
    assert any("No service" in n for n in reports[0].notes)


def test_more_load_raises_the_ratio_and_sizing_passes() -> None:
    def ratio(p: float) -> float:
        project, results = _setup({101: (0.0, p, 0.0)})
        settings = _with_footings(project, [DesignLoadSet(source="case", ref_id=101)])
        return check_footings(project, results, settings)[0].ratio

    assert ratio(50.0) < ratio(200.0)
    project, results = _setup({101: (5.0, 300.0, 400.0)})
    settings = _with_footings(project, [DesignLoadSet(source="case", ref_id=101)])
    sized = size_design(project, results, settings, settings.footings[0])
    assert sized is not None
    report = check_footings(project, results, settings, designs={1: sized}, nodes={1})[0]
    assert report.status == "OK"


def test_the_footing_sets_a2_of_the_base_plate() -> None:
    project, results = _setup({101: (0.0, 300.0, 0.0)})
    sets = [DesignLoadSet(source="case", ref_id=101)]
    plain = check_bases(project, results, DesignSettings(load_sets=sets))[0]
    with_footing = check_bases(project, results, _with_footings(project, sets))[0]
    assert with_footing.checks["Concrete bearing"] < plain.checks["Concrete bearing"]
    assert any("Design → Footings" in n for n in with_footing.notes)


def test_settings_without_footings_save_as_before() -> None:
    project, _results = _setup({})
    empty = DesignSettings()
    assert "footings" not in json.loads(empty.model_dump_json())
    settings = _with_footings(project, [])
    again = DesignSettings.model_validate_json(settings.model_dump_json())
    assert again == settings
