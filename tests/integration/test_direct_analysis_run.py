"""The Direct Analysis Method cases solved by OpenSees, against hand calculations.

The one-bay portal of ``tests/unit/test_direct_analysis.py``: a factored case
equals the superposition of its patterns, the reduced stiffness makes a linear
drift exactly 1/0.8 times larger, the notional loads come back as base shear,
and Δ2/Δ1 matches the storey amplifier 1 / (1 - P Δ1 / (H L)). The steel check
then reads the strength cases with K = 1, each member with its grade.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import StaticCase
from opensees_studio.core.design.direct_analysis import direct_analysis_cases, drift_ratios
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.steel_design import default_load_sets, steel_frame_check
from tests.unit.test_direct_analysis import H_WIND, P_DEAD, P_LIVE, ROLES, _portal

HEIGHT = 144.0


def _final(results) -> dict[int, np.ndarray]:  # type: ignore[no-untyped-def]
    return {nid: np.atleast_2d(v)[-1] for nid, v in results.node_disp.items()}


def _base_shear(results) -> float:  # type: ignore[no-untyped-def]
    return float(sum(np.atleast_2d(results.node_reaction[n])[-1][0] for n in (1, 2)))


def test_a_factored_case_equals_the_superposition_of_its_patterns() -> None:
    project = _portal()
    dead = _final(OpenSeesRunner(project).run(project.analyses[0]))
    live = _final(OpenSeesRunner(project).run(project.analyses[1]))
    combo = StaticCase(id=9, pattern_ids=[1, 2], pattern_factors=[1.2, 1.6])
    together = _final(OpenSeesRunner(project).run(combo))
    for nid, u in together.items():
        np.testing.assert_allclose(u, 1.2 * dead[nid] + 1.6 * live[nid], atol=1e-14)


def test_reduced_stiffness_makes_a_linear_drift_1_25_times_larger() -> None:
    project = _portal()
    full = _final(OpenSeesRunner(project).run(project.analyses[2]))
    reduced_case = StaticCase(id=9, pattern_ids=[3], stiffness_factor=0.8)
    reduced = _final(OpenSeesRunner(project).run(reduced_case))
    assert reduced[3][0] == pytest.approx(full[3][0] / 0.8, rel=1e-12)


def test_notional_loads_come_back_as_base_shear() -> None:
    project = _portal()
    case = StaticCase(
        id=9,
        pattern_ids=[1, 2],
        pattern_factors=[1.2, 1.6],
        notional_ratio=0.003,
        notional_direction="+X",
    )
    results = OpenSeesRunner(project).run(case)
    assert _base_shear(results) == pytest.approx(-0.003 * (1.2 * 2 * P_DEAD + 1.6 * 2 * P_LIVE))
    assert any("Ni = 0.003 Yi" in w for w in results.warnings)


def test_second_to_first_order_drift_matches_the_storey_amplifier() -> None:
    project = _portal()
    out = direct_analysis_cases(project, DesignSettings(), ROLES, first_id=10)
    project.analyses += out.cases
    case = next(c for c in out.cases if c.name == "DAM 0.9D+W")
    twin = next(c for c in out.cases if c.name == "DAM 1st-order 0.9D+W")
    second = OpenSeesRunner(project).run(case)
    first = OpenSeesRunner(project).run(twin)
    assert any("PDelta" in w for w in second.warnings)
    (row,) = drift_ratios(project, case, _final(first), _final(second))
    gravity = 0.9 * 2 * P_DEAD
    shear = H_WIND + 0.001 * gravity
    b2 = 1.0 / (1.0 - gravity * row.first / (shear * HEIGHT))
    assert row.ratio == pytest.approx(b2, rel=2e-3)


def test_the_steel_check_reads_the_strength_cases_with_k_1_and_member_grades() -> None:
    project = _portal()
    settings = DesignSettings(stability_method="direct")
    out = direct_analysis_cases(project, settings, ROLES, first_id=10)
    project.analyses += out.cases
    results = {c.id: OpenSeesRunner(project).run(c) for c in out.strength_cases}
    sets = default_load_sets(project)
    assert [s.ref_id for s in sets] == [c.id for c in out.strength_cases]

    a992 = settings.model_copy(update={"steel_grades": {"W": "A992"}})
    a36 = settings.model_copy(update={"steel_grades": {"W": "A36"}})
    with_k = a992.model_copy(
        update={"members": [a992.member(1).model_copy(update={"k_major": 2.0, "k_minor": 2.0})]}
    )
    report_992 = steel_frame_check(project, results, a992)
    report_36 = steel_frame_check(project, results, a36)
    report_k = steel_frame_check(project, results, with_k)
    column_992 = next(m for m in report_992.members if m.element_id == 1)
    column_36 = next(m for m in report_36.members if m.element_id == 1)
    assert column_992.grade == "ASTM A992" and column_36.grade == "ASTM A36"
    assert column_36.ratio > column_992.ratio
    assert any("Direct Analysis Method" in n for n in report_992.notes)
    column_k = next(m for m in report_k.members if m.element_id == 1)
    assert column_k.ratio == pytest.approx(column_992.ratio)
    assert any("uses K = 1" in n for n in column_k.notes)


def test_pynite_refuses_a_direct_analysis_case() -> None:
    pytest.importorskip("Pynite")
    from opensees_studio.services.pynite_runner import PyNiteRunner, PyNiteUnsupportedError

    project = _portal()
    case = StaticCase(id=9, pattern_ids=[1], p_delta=True, stiffness_factor=0.8)
    with pytest.raises(PyNiteUnsupportedError, match="P-Delta in every frame"):
        PyNiteRunner(project).run(case)
