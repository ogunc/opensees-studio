"""Integration tests for OpenSees Example 1a cantilever column."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import PushoverCase, TransientCase  # noqa: E402
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def _reload(proj, tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "ex1a_canti2d.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()
    return reloaded


def test_ex1a_canti2d_pushover_reaches_target(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.ex1a_canti2d import PUSH_STEP, PUSH_TARGET, build_ex1a_canti2d

    proj = _reload(build_ex1a_canti2d(), tmp_path)
    push_case = next(c for c in proj.analyses if isinstance(c, PushoverCase))
    result = OpenSeesRunner(proj).run(push_case)

    expected_pts = int(PUSH_TARGET / PUSH_STEP) + 1
    assert len(result.control_disp) == expected_pts
    assert result.control_disp[-1] == pytest.approx(PUSH_TARGET, rel=1e-6)

    # Linear-elastic frame -> monotonic base shear and nearly constant tangent stiffness.
    assert result.base_shear[-1] > 0.0
    assert result.base_shear[200] > result.base_shear[100] > result.base_shear[1]

    slope_early = (result.base_shear[10] - result.base_shear[0]) / (
        result.control_disp[10] - result.control_disp[0]
    )
    slope_late = (result.base_shear[-1] - result.base_shear[-11]) / (
        result.control_disp[-1] - result.control_disp[-11]
    )
    assert slope_early == pytest.approx(slope_late, rel=0.02)


def test_ex1a_canti2d_earthquake_runs_and_oscillates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.ex1a_canti2d import ANALYSIS_DT, ANALYSIS_STEPS, build_ex1a_canti2d

    proj = _reload(build_ex1a_canti2d(), tmp_path)
    eq_case = next(c for c in proj.analyses if isinstance(c, TransientCase))

    results_dir = Path(tempfile.mkdtemp(prefix="ex1a_canti2d_eq_"))
    result = OpenSeesRunner(proj).run(eq_case, results_dir=results_dir)

    time = result.time()
    top = result.node_disp_history(2)
    ux = top[:, 0]
    uy = top[:, 1]

    assert len(time) == ANALYSIS_STEPS
    assert result.dt == pytest.approx(ANALYSIS_DT)
    assert ux.max() > 0.001
    assert ux.min() < -0.001
    assert max(abs(uy)) < 1.0
