"""Integration tests for OpenSees Example 2a variable-driven cantilever."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import PushoverCase, TransientCase  # noqa: E402
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def _reload(proj, tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "ex2a_canti2d_elastic_element.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()
    return reloaded


def test_ex2a_canti2d_pushover_reaches_target(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.ex2a_canti2d_elastic_element import (
        PUSH_STEP,
        PUSH_TARGET,
        build_ex2a_canti2d_elastic_element,
    )

    proj = _reload(build_ex2a_canti2d_elastic_element(), tmp_path)
    push_case = next(c for c in proj.analyses if isinstance(c, PushoverCase))
    result = OpenSeesRunner(proj).run(push_case)

    expected_pts = int(PUSH_TARGET / PUSH_STEP) + 1
    assert len(result.control_disp) == expected_pts
    assert result.control_disp[-1] == pytest.approx(PUSH_TARGET, rel=1e-6)
    assert result.base_shear[-1] > 0.0

    slope_early = (result.base_shear[5] - result.base_shear[0]) / (
        result.control_disp[5] - result.control_disp[0]
    )
    slope_late = (result.base_shear[-1] - result.base_shear[-3]) / (
        result.control_disp[-1] - result.control_disp[-3]
    )
    assert slope_early == pytest.approx(slope_late, rel=0.02)


def test_ex2a_canti2d_earthquake_runs_and_oscillates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.ex2a_canti2d_elastic_element import (
        ANALYSIS_DT,
        ANALYSIS_STEPS,
        build_ex2a_canti2d_elastic_element,
    )

    proj = _reload(build_ex2a_canti2d_elastic_element(), tmp_path)
    eq_case = next(c for c in proj.analyses if isinstance(c, TransientCase))

    results_dir = Path(tempfile.mkdtemp(prefix="ex2a_canti2d_eq_"))
    result = OpenSeesRunner(proj).run(eq_case, results_dir=results_dir)

    time = result.time()
    top = result.node_disp_history(2)
    ux = top[:, 0]
    uy = top[:, 1]

    assert len(time) == ANALYSIS_STEPS
    assert result.dt == pytest.approx(ANALYSIS_DT)
    assert ux.max() > 1e-4
    assert ux.min() < -1e-4
    assert max(abs(uy)) < 1.0
