"""Integration test for the 2D elastic cantilever earthquake example."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_ex1a_canti2d_eq_runs_and_oscillates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.ex1a_canti2d_eq import (
        ANALYSIS_DT,
        COLUMN_HEIGHT,
        build_ex1a_canti2d_eq,
    )

    proj = build_ex1a_canti2d_eq()
    proj.validate_references()

    path = tmp_path / "ex1a.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()

    results_dir = Path(tempfile.mkdtemp(prefix="ex1a_eq_"))
    result = OpenSeesRunner(reloaded).run(reloaded.analyses[1], results_dir=results_dir)

    t = result.time()
    top = result.node_disp_history(2)
    ux = top[:, 0]
    uy = top[:, 1]

    assert len(t) == reloaded.analyses[1].n_steps
    assert result.dt == pytest.approx(ANALYSIS_DT)
    assert t[-1] == pytest.approx(ANALYSIS_DT * reloaded.analyses[1].n_steps, abs=ANALYSIS_DT)

    # Dynamic response should oscillate in both directions under the base motion.
    assert ux.max() > 0.01
    assert ux.min() < -0.01

    # The elastic column should stay in a physically reasonable range.
    assert max(abs(ux)) < 0.10 * COLUMN_HEIGHT

    # Gravity remains locked but the input is horizontal, so Uy should stay small.
    assert max(abs(uy)) < 1.0
