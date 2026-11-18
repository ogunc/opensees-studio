"""Integration test: RC Frame Earthquake example (OpenSees Ex 3.3)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project, save_project
from opensees_studio.services.opensees_runner import OpenSeesRunner


@pytest.fixture(scope="module")
def eq_result(tmp_path_factory):  # type: ignore[no-untyped-def]
    """Build, round-trip and run the example once for every test in this module."""
    from examples.rc_frame_earthquake import build_rc_frame_earthquake

    proj = build_rc_frame_earthquake()
    proj.validate_references()

    osmodel = tmp_path_factory.mktemp("eq_model") / "eq.osmodel"
    save_project(proj, osmodel)
    reloaded = load_project(osmodel)
    reloaded.validate_references()

    results_dir = Path(tempfile.mkdtemp(prefix="eq_"))
    return OpenSeesRunner(reloaded).run(reloaded.analyses[0], results_dir=results_dir)


def test_rc_frame_earthquake_covers_the_record(eq_result) -> None:  # type: ignore[no-untyped-def]
    """The run covers the whole 4-second record.

    With damping on the current tangent (``rayleigh_beta_k``) instead of the
    committed stiffness the run stalled at t = 0.99 s.
    """
    from examples.rc_frame_earthquake import N_PTS

    result = eq_result
    assert result.n_steps == N_PTS, f"Only {result.n_steps}/{N_PTS} steps"
    assert not result.early_stop


def test_rc_frame_earthquake_runs_and_has_oscillatory_response(eq_result) -> None:  # type: ignore[no-untyped-def]
    """Synthetic ground motion produces bounded, oscillatory response."""
    result = eq_result

    # Node 3 Ux history: bounded, non-trivial, some positive AND some
    # negative (oscillation confirms the base excitation actually
    # propagated through the mass + damping chain, not a one-shot push).
    h3 = result.node_disp_history(3)
    ux = h3[:, 0]
    assert max(ux) > 0.05, f"max Ux {max(ux):.4f} too small — did excitation apply?"
    assert min(ux) < -0.05, f"min Ux {min(ux):.4f} — no negative excursion"
    # About 1.1 % drift (1.64 in on 144 in); the run converges in dt (1.65 in
    # at dt / 2), so 2 % of the column height is a wide but meaningful bound.
    assert max(abs(ux)) < 0.02 * 144.0, f"|Ux|_max = {max(abs(ux)):.2f} exceeds 2% drift"

    # Uy on the top nodes — small compared to Ux (gravity holds, base
    # excitation is horizontal).
    uy = h3[:, 1]
    assert max(abs(uy)) < 1.0, f"max |Uy| = {max(abs(uy)):.4f} in too large"
