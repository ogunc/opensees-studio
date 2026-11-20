"""Design → Base Plates: a moment with uplift is flagged, never passed or sized.

The portal of ``test_direct_analysis`` (kip, in) with hand-made reactions, so the
service is checked without a solver: one alternative in compression, one with
uplift and a moment. The base must read ``requires verification`` although the
compression alternative passes, keep the demands and the load set of the flagged
alternative, and refuse automatic sizing.
"""

from __future__ import annotations

import numpy as np

from opensees_studio.core import StaticCase
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
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
            case_id=cid,
            case_name=f"C{cid}",
            n_steps=1,
            node_reaction={1: reaction, 2: reaction},
        )
    settings = DesignSettings(load_sets=[DesignLoadSet(source="case", ref_id=cid) for cid in rows])
    return project, settings, results


def test_uplift_with_moment_flags_the_base_even_when_the_rest_passes() -> None:
    project, settings, results = _project_and_results(
        {101: (0.0, 100.0, 0.0), 102: (0.0, -8.0, 500.0)}
    )
    result = check_bases(project, results, settings)[0]

    assert result.status == STATUS_REQUIRES_VERIFICATION
    assert result.ratio < 1.0  # the compression alternative alone would pass
    ((label, (pu, mu, _vu)),) = result.unverified
    assert "C102" in label
    assert (pu, mu) == (-8.0, 500.0)
    assert any("Requires verification" in note for note in result.notes)


def test_a_base_with_only_moment_and_no_axial_keeps_its_demand() -> None:
    project, settings, results = _project_and_results({101: (0.0, 0.0, 500.0)})
    result = check_bases(project, results, settings)[0]

    assert result.status == STATUS_REQUIRES_VERIFICATION
    assert "C101" in result.load_set
    assert result.demands[:2] == (0.0, 500.0)


def test_ng_wins_over_requires_verification() -> None:
    project, settings, results = _project_and_results(
        {101: (0.0, 5000.0, 0.0), 102: (0.0, -8.0, 500.0)}
    )
    result = check_bases(project, results, settings)[0]

    assert result.status == "NG"
    assert result.unverified


def test_pure_uplift_and_compression_with_moment_stay_ok() -> None:
    project, settings, results = _project_and_results(
        {101: (0.0, 100.0, 300.0), 102: (0.0, -8.0, 0.0)}
    )
    result = check_bases(project, results, settings)[0]

    assert result.status == "OK"
    assert not result.unverified


def test_sizing_refuses_a_base_that_requires_verification() -> None:
    project, settings, results = _project_and_results(
        {101: (0.0, 100.0, 0.0), 102: (0.0, -8.0, 500.0)}
    )
    base = column_bases(project, settings)[0]
    design = default_design(base, project.meta.units)

    assert size_thickness(project, results, settings, design) is None
    project, settings, results = _project_and_results({101: (0.0, 100.0, 0.0)})
    assert size_thickness(project, results, settings, design) is not None
