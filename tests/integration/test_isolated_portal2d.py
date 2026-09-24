"""Integration test for the base-isolated portal frame example."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import StaticCase, TransientCase
from opensees_studio.services import load_project, save_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from tests.integration._record_files import copy_record_files

# Peak isolator displacement |ux| of the left base node (in) measured on this run.
PEAK_ISOLATOR_UX = 1.351710
# Peak top-node |ux| of the fixed-base Example 1b frame under the same record.
FIXED_BASE_PEAK_UX = 0.680483


def _reload(proj, tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "isolated_portal2d.osmodel"
    save_project(proj, path)
    copy_record_files(proj, path.parent)
    reloaded = load_project(path)
    reloaded.validate_references()
    return reloaded


def test_isolated_portal2d_gravity_reaches_the_bearings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.isolated_portal2d import BEARING_L, NODE_GROUND_L, build_isolated_portal2d

    proj = _reload(build_isolated_portal2d(), tmp_path)
    assert [el.type for el in proj.elements if el.id in (4, 5)] == [
        "ElastomericBearingPlasticity"
    ] * 2
    gravity = next(c for c in proj.analyses if isinstance(c, StaticCase))
    result = OpenSeesRunner(proj).run(gravity)
    # the beam load 7.94 kip/in over 504 in is carried half by each bearing
    assert result.node_reaction[NODE_GROUND_L][-1, 1] == pytest.approx(7.94 * 504.0 / 2.0, rel=1e-3)
    axial = result.element_forces[BEARING_L][-1]
    assert abs(axial[0]) == pytest.approx(7.94 * 504.0 / 2.0, rel=1e-3)


def test_isolated_portal2d_earthquake_yields_the_isolators(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.isolated_portal2d import (
        ANALYSIS_STEPS,
        BEARING_L,
        NODE_BASE_L,
        NODE_BASE_R,
        NODE_TOP_L,
        build_isolated_portal2d,
    )

    proj = _reload(build_isolated_portal2d(), tmp_path)
    eq_case = next(c for c in proj.analyses if isinstance(c, TransientCase))
    result = OpenSeesRunner(proj).run(eq_case, results_dir=Path(tempfile.mkdtemp(prefix="iso_")))
    assert result.n_steps == ANALYSIS_STEPS

    base = result.node_disp_history(NODE_BASE_L)[:, 0]
    top = result.node_disp_history(NODE_TOP_L)[:, 0]
    peak_isolator = float(np.abs(base).max())
    assert peak_isolator == pytest.approx(PEAK_ISOLATOR_UX, rel=0.05)
    bearing = proj.element(BEARING_L)
    assert peak_isolator > 5.0 * bearing.yield_displacement  # well into the post-yield branch
    shear = -result.element_force_history(BEARING_L)[:, 1]
    assert float(np.abs(shear).max()) > bearing.yield_force
    # the two isolators move together (base slab equalDOF in X)
    other = result.node_disp_history(NODE_BASE_R)[:, 0]
    assert base == pytest.approx(other, rel=1e-6, abs=1e-9)
    # the superstructure drift stays below the fixed-base peak of Example 1b
    assert float(np.abs(top - base).max()) < FIXED_BASE_PEAK_UX


def test_isolated_portal2d_osmodel_matches_the_script() -> None:
    from examples.isolated_portal2d import build_isolated_portal2d

    path = Path(__file__).resolve().parents[2] / "examples" / "isolated_portal2d.osmodel"
    stored = load_project(path)
    assert stored.model_dump(by_alias=True) == build_isolated_portal2d().model_dump(by_alias=True)
