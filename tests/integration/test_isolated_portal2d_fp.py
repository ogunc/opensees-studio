"""Integration test for the base-isolated portal frame on single FP bearings."""

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
PEAK_ISOLATOR_UX = 1.424850
# The same frame on elastomeric bearings (ISO-1 example) and fixed-base Example 1b.
ELASTOMERIC_PEAK_UX = 1.351710
FIXED_BASE_PEAK_UX = 0.680483
WEIGHT_PER_BEARING = 7.94 * 504.0 / 2.0  # kip


def _reload(proj, tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "isolated_portal2d_fp.osmodel"
    save_project(proj, path)
    copy_record_files(proj, path.parent)
    reloaded = load_project(path)
    reloaded.validate_references()
    return reloaded


def test_isolated_portal2d_fp_gravity_reaches_the_bearings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.isolated_portal2d_fp import BEARING_L, NODE_GROUND_L, build_isolated_portal2d_fp

    proj = _reload(build_isolated_portal2d_fp(), tmp_path)
    assert [el.type for el in proj.elements if el.id in (4, 5)] == ["SingleFPBearing"] * 2
    assert [fm.type for fm in proj.friction_models] == ["Coulomb"]
    gravity = next(c for c in proj.analyses if isinstance(c, StaticCase))
    result = OpenSeesRunner(proj).run(gravity)
    assert result.node_reaction[NODE_GROUND_L][-1, 1] == pytest.approx(WEIGHT_PER_BEARING, rel=1e-3)
    assert abs(result.element_forces[BEARING_L][-1][0]) == pytest.approx(
        WEIGHT_PER_BEARING, rel=1e-3
    )


def test_isolated_portal2d_fp_earthquake_slides_the_isolators(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.isolated_portal2d_fp import (
        ANALYSIS_STEPS,
        BEARING_L,
        MU,
        NODE_BASE_L,
        NODE_BASE_R,
        NODE_TOP_L,
        R_EFF,
        build_isolated_portal2d_fp,
    )

    proj = _reload(build_isolated_portal2d_fp(), tmp_path)
    eq_case = next(c for c in proj.analyses if isinstance(c, TransientCase))
    result = OpenSeesRunner(proj).run(eq_case, results_dir=Path(tempfile.mkdtemp(prefix="fp_")))
    assert result.n_steps == ANALYSIS_STEPS

    base = result.node_disp_history(NODE_BASE_L)[:, 0]
    top = result.node_disp_history(NODE_TOP_L)[:, 0]
    peak_isolator = float(np.abs(base).max())
    assert peak_isolator == pytest.approx(PEAK_ISOLATOR_UX, rel=0.05)
    bearing = proj.element(BEARING_L)
    assert peak_isolator > 5.0 * bearing.yield_displacement(MU, WEIGHT_PER_BEARING)
    assert bearing.isolated_period(proj.meta.units) == pytest.approx(2.497, abs=0.005)
    shear = -result.element_force_history(BEARING_L)[:, 1]
    # the bearing slides (above mu W) and its force stays near the sliding envelope
    assert float(np.abs(shear).max()) > MU * WEIGHT_PER_BEARING
    envelope = MU * WEIGHT_PER_BEARING + WEIGHT_PER_BEARING * peak_isolator / R_EFF
    assert float(np.abs(shear).max()) < 1.1 * envelope
    other = result.node_disp_history(NODE_BASE_R)[:, 0]
    assert base == pytest.approx(other, rel=1e-6, abs=1e-9)
    # the superstructure drift stays below the fixed-base peak, as with the elastomeric bearings
    assert float(np.abs(top - base).max()) < FIXED_BASE_PEAK_UX
    assert peak_isolator == pytest.approx(ELASTOMERIC_PEAK_UX, rel=0.1)  # same design targets


def test_isolated_portal2d_fp_osmodel_matches_the_script() -> None:
    from examples.isolated_portal2d_fp import build_isolated_portal2d_fp

    path = Path(__file__).resolve().parents[2] / "examples" / "isolated_portal2d_fp.osmodel"
    stored = load_project(path)
    assert stored.model_dump(by_alias=True) == build_isolated_portal2d_fp().model_dump(
        by_alias=True
    )
