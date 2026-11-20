"""Design → Base Plates: uplift with a moment over every alternative, by support.

The portal of ``test_direct_analysis`` (kip, in) with hand-made reactions, so the
service is checked without a solver. Uplift with a moment is now solved on the
rod rows: the governing alternative, its demands and the row it pulls must come
through, the moment's sign must pick the row, and an alternative the check
cannot cover must still read ``requires verification`` and stop the sizing.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import StaticCase
from opensees_studio.core.design.base_plate import BasePlateResult, PlateCheck
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
from opensees_studio.services import base_plates
from opensees_studio.services.base_plates import (
    STATUS_REQUIRES_VERIFICATION,
    check_bases,
    column_bases,
    default_design,
    size_thickness,
)
from opensees_studio.services.results import StaticResults
from tests.unit.test_direct_analysis import _portal


def _project_and_results(rows: dict[int, tuple[float, float, float]]):  # type: ignore[no-untyped-def]
    """A case per row; each puts ``(Fx, Fz, My)`` as the reaction of both bases."""
    project = _portal()
    results = {}
    for cid, row in rows.items():  # ids clear of the portal's own cases
        project.analyses.append(StaticCase(id=cid, name=f"C{cid}", pattern_ids=[1]))
        reaction = np.array([row])
        results[cid] = StaticResults(
            case_id=cid, case_name=f"C{cid}", n_steps=1, node_reaction={1: reaction, 2: reaction}
        )
    settings = DesignSettings(load_sets=[DesignLoadSet(source="case", ref_id=c) for c in rows])
    return project, settings, results


def test_uplift_with_moment_is_checked_and_can_govern() -> None:
    project, settings, results = _project_and_results(
        {101: (0.0, 100.0, 0.0), 102: (0.0, -8.0, 1500.0)}
    )
    result = check_bases(project, results, settings)[0]

    assert not result.unverified
    assert result.status in ("OK", "NG")
    assert "C102" in result.load_set
    assert result.demands[:2] == (-8.0, 1500.0)
    assert result.row_tension[0] > 8.0 and result.row_tension[1] == 0.0


def test_the_sign_of_the_moment_picks_the_row() -> None:
    def rows(moment: float) -> tuple[float, float]:
        project, settings, results = _project_and_results({101: (0.0, -8.0, moment)})
        return check_bases(project, results, settings)[0].row_tension

    plus, minus = rows(1500.0), rows(-1500.0)
    assert plus == pytest.approx(minus[::-1])
    assert plus[0] > plus[1]


def test_more_moment_with_uplift_raises_the_ratio() -> None:
    def ratio(moment: float) -> float:
        project, settings, results = _project_and_results({101: (0.0, -8.0, moment)})
        return check_bases(project, results, settings)[0].ratio

    assert ratio(0.0) < ratio(500.0) < ratio(1500.0)


def _uncovered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real = base_plates.check_base_plate

    def fake(plate, *, pu, mu=0.0, vu=0.0):  # type: ignore[no-untyped-def]
        if pu < 0.0:
            return BasePlateResult(
                checks=[PlateCheck("Anchor rod steel in tension", 0.1, "test")],
                requires_verification="outside the method (test)",
            )
        return real(plate, pu=pu, mu=mu, vu=vu)

    monkeypatch.setattr(base_plates, "check_base_plate", fake)


def test_an_uncovered_alternative_flags_the_base_even_when_the_rest_passes(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    _uncovered(monkeypatch)
    project, settings, results = _project_and_results(
        {101: (0.0, 100.0, 0.0), 102: (0.0, -8.0, 500.0)}
    )
    result = check_bases(project, results, settings)[0]

    assert result.status == STATUS_REQUIRES_VERIFICATION
    assert result.ratio < 1.0
    ((label, (pu, mu, _vu)),) = result.unverified
    assert "C102" in label and (pu, mu) == (-8.0, 500.0)
    assert any("Requires verification" in note for note in result.notes)


def test_ng_wins_over_requires_verification(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _uncovered(monkeypatch)
    project, settings, results = _project_and_results(
        {101: (0.0, 5000.0, 0.0), 102: (0.0, -8.0, 500.0)}
    )
    result = check_bases(project, results, settings)[0]
    assert result.status == "NG" and result.unverified


def test_sizing_refuses_a_base_that_requires_verification(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project, settings, results = _project_and_results({101: (0.0, 100.0, 0.0)})
    design = default_design(column_bases(project, settings)[0], project.meta.units)
    assert size_thickness(project, results, settings, design) is not None

    _uncovered(monkeypatch)
    project, settings, results = _project_and_results(
        {101: (0.0, 100.0, 0.0), 102: (0.0, -8.0, 500.0)}
    )
    assert size_thickness(project, results, settings, design) is None


def test_sizing_covers_the_plate_bending_over_the_tension_rods() -> None:
    project, settings, results = _project_and_results({101: (0.0, -8.0, 1500.0)})
    design = default_design(column_bases(project, settings)[0], project.meta.units)
    tp = size_thickness(project, results, settings, design)
    assert tp is not None
    sized = check_bases(
        project, results, settings, designs={1: design.model_copy(update={"tp": tp})}
    )[0]
    assert all(v <= 1.0 for k, v in sized.checks.items() if k.startswith("Plate thickness"))
