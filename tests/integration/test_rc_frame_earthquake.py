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


@pytest.mark.xfail(
    strict=True,
    reason="solver two-state cycle at step 193, t = 1.93 s; see roadmap box",
)
def test_rc_frame_earthquake_covers_the_record(eq_result) -> None:  # type: ignore[no-untyped-def]
    """The run covers at least 90 percent of the 4-second record."""
    from examples.rc_frame_earthquake import N_PTS

    result = eq_result
    assert result.n_steps >= int(0.9 * N_PTS), (
        f"Only {result.n_steps}/{N_PTS} steps, fallback did not recover"
    )


def test_rc_frame_earthquake_runs_and_has_oscillatory_response(eq_result) -> None:  # type: ignore[no-untyped-def]
    """Synthetic ground motion produces bounded, oscillatory response.

    Holds on whatever part of the record completed; the step count is
    asserted separately in test_rc_frame_earthquake_covers_the_record.
    """
    result = eq_result

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
