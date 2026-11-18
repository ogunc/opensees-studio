"""Design → Base Plates over real OpenSees results, against hand calculations.

The one-bay portal of ``tests/unit/test_direct_analysis.py`` on W14X90 columns,
with fixed and with pinned bases, under its direct analysis cases. A pinned
base takes no moment and its bearing ratio is Pu / (N B fp,max); a fixed base
is governed by a lateral combination with the reaction moment; the sizing
picks the thinnest standard plate that passes. The column kinds and the
saved plates are pinned on top of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core.design.base_plate import BasePlate, BasePlateDesign
from opensees_studio.core.design.direct_analysis import direct_analysis_cases
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.services import load_project, save_project
from opensees_studio.services.base_plates import (
    check_bases,
    column_bases,
    default_design,
    size_thickness,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from tests.unit.test_direct_analysis import ROLES, _portal

PINNED_2D = (True, False, True, False, False, False)


def _solved(pinned: bool = False):  # type: ignore[no-untyped-def]
    project = _portal()
    if pinned:
        for node in project.nodes[:2]:
            node.restraint = PINNED_2D
    settings = DesignSettings(stability_method="direct")
    out = direct_analysis_cases(project, settings, ROLES, first_id=10)
    project.analyses += out.cases
    results = {c.id: OpenSeesRunner(project).run(c) for c in out.strength_cases}
    return project, settings, results


def test_the_bases_and_their_support_types_are_found() -> None:
    project, settings, _results = _solved()
    bases = column_bases(project, settings)
    assert [(b.node_id, b.shape, b.kind, b.support) for b in bases] == [
        (1, "W14X90", "W", "fixed"),
        (2, "W14X90", "W", "fixed"),
    ]
    project.nodes[0].restraint = PINNED_2D
    assert column_bases(project, settings)[0].support == "pinned"


def test_a_pinned_base_is_checked_concentric() -> None:
    project, settings, results = _solved(pinned=True)
    result = check_bases(project, results, settings)[0]
    pu, mu, _vu = result.demands
    assert mu == 0.0
    # Gravity governs a pinned base: 1.2 x 200 + 1.6 x 100 kip on each column.
    assert pu == pytest.approx(400.0, rel=0.01)
    design = default_design(column_bases(project, settings)[0], project.meta.units)
    fp_max = 0.65 * 0.85 * 4.0
    bearing = pu / (design.n_length * design.b_width * fp_max)
    assert result.checks["Concrete bearing"] == pytest.approx(bearing, rel=1e-6)
    assert "Plate thickness (bearing)" in result.checks


def test_a_fixed_base_is_governed_by_a_lateral_combination_with_its_moment() -> None:
    project, settings, results = _solved()
    result = check_bases(project, results, settings)[0]
    _pu, mu, _vu = result.demands
    assert mu > 0.0
    assert "W" in result.load_set
    assert "Plate thickness" in result.checks


def test_sizing_picks_the_thinnest_standard_plate_that_passes() -> None:
    project, settings, results = _solved()
    base = column_bases(project, settings)[0]
    design = default_design(base, project.meta.units)
    tp = size_thickness(project, results, settings, design)
    assert tp == pytest.approx(1.25)
    sized = design.model_copy(update={"tp": tp})
    result = check_bases(project, results, settings, designs={base.node_id: sized})[0]
    assert result.checks["Plate thickness"] <= 1.0
    thinner = design.model_copy(update={"tp": 1.125})
    result = check_bases(project, results, settings, designs={base.node_id: thinner})[0]
    assert result.checks["Plate thickness"] > 1.0


def test_hss_and_round_columns_use_their_own_cantilevers() -> None:
    common = dict(n_length=20.0, b_width=20.0, tp=1.0, fy=36.0, fc=4.0)
    w = BasePlate(d=14.0, bf=14.5, **common)  # type: ignore[arg-type]
    hss = BasePlate(d=14.0, bf=14.5, kind="HSS", **common)  # type: ignore[arg-type]
    pipe = BasePlate(d=14.0, bf=14.0, kind="round", **common)  # type: ignore[arg-type]
    assert w.cantilevers() == pytest.approx(((20 - 0.95 * 14) / 2, (20 - 0.8 * 14.5) / 2))
    assert hss.cantilevers() == pytest.approx(((20 - 0.95 * 14) / 2, (20 - 0.95 * 14.5) / 2))
    assert pipe.cantilevers() == pytest.approx(((20 - 0.8 * 14) / 2,) * 2)


def test_the_plates_save_only_when_set(tmp_path: Path) -> None:
    project, settings, _results = _solved()
    project.design = settings
    path = save_project(project, tmp_path / "plain.osmodel")
    assert "base_plates" not in json.loads(path.read_text(encoding="utf-8"))["design"]
    base = column_bases(project, settings)[0]
    plate = default_design(base, project.meta.units).model_copy(update={"tp": 1.5})
    project.design = settings.model_copy(update={"base_plates": [plate]})
    path = save_project(project, tmp_path / "plates.osmodel")
    assert load_project(path).design.base_plates == [plate]
    assert isinstance(load_project(path).design.base_plates[0], BasePlateDesign)
