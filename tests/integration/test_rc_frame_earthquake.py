"""Integration test: RC Frame Earthquake example (OpenSees Ex 3.3)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_rc_frame_earthquake_runs_and_has_oscillatory_response(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Synthetic ground motion produces bounded, oscillatory response."""
    from examples.rc_frame_earthquake import (
        build_rc_frame_earthquake,
        DT,
        N_PTS,
    )
    proj = build_rc_frame_earthquake()
    proj.validate_references()

    osmodel = tmp_path / "eq.osmodel"
    save_project(proj, osmodel)
    reloaded = load_project(osmodel)
    reloaded.validate_references()

    results_dir = Path(tempfile.mkdtemp(prefix="eq_"))
    result = OpenSeesRunner(reloaded).run(reloaded.analyses[0], results_dir=results_dir)

    # Simulation covers most of the 4-second record (ModifiedNewton
    # fallback may trim a few steps at stiffness jumps; we allow that).
    assert result.n_steps >= int(0.9 * N_PTS), (
        f"Only {result.n_steps}/{N_PTS} steps — fallback didn't recover"
    )

    # Node 3 Ux history: bounded, non-trivial, some positive AND some
    # negative (oscillation confirms the base excitation actually
    # propagated through the mass + damping chain, not a one-shot push).
    h3 = result.node_disp_history(3)
    ux = h3[:, 0]
    assert max(ux) > 0.05, f"max Ux {max(ux):.4f} too small — did excitation apply?"
    assert min(ux) < -0.05, f"min Ux {min(ux):.4f} — no negative excursion"
    # Drift stays reasonable (< 10% of column height).
    assert max(abs(ux)) < 14.4, f"|Ux|_max = {max(abs(ux)):.2f} exceeds 10% drift"

    # Uy on the top nodes — small compared to Ux (gravity holds, base
    # excitation is horizontal).
    uy = h3[:, 1]
    assert max(abs(uy)) < 1.0, f"max |Uy| = {max(abs(uy)):.4f} in too large"