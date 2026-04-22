"""Integration test for RC Frame Pushover example (OpenSees Ex 3.2)."""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_rc_frame_pushover_reaches_target_with_fallback(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The 15-in pushover requires the ModifiedNewton convergence
    fallback to finish; without it the Newton solver stalls in the
    softening regime. This test asserts the full curve is produced
    AND shows expected nonlinear shape.
    """
    from examples.rc_frame_pushover import (
        build_rc_frame_pushover,
        D_STEP,
        D_TARGET,
    )
    proj = build_rc_frame_pushover()
    proj.validate_references()

    path = tmp_path / "rc_push.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()

    result = OpenSeesRunner(reloaded).run(reloaded.analyses[0])

    expected_pts = int(D_TARGET / D_STEP) + 1     # 151 including step 0
    assert len(result.control_disp) == expected_pts, (
        f"Got {len(result.control_disp)} points, expected {expected_pts} — "
        "ModifiedNewton fallback probably didn't kick in."
    )
    # Reached the target displacement.
    assert result.control_disp[-1] == pytest.approx(D_TARGET, rel=1e-3)

    # Curve shape: monotonic climb followed by near-plateau (yielding).
    # The elastic slope should exceed the post-yield slope by > 4x.
    early_slope = (result.base_shear[10] - result.base_shear[0]) / (
        result.control_disp[10] - result.control_disp[0]
    )
    late_slope = (result.base_shear[-1] - result.base_shear[-20]) / (
        result.control_disp[-1] - result.control_disp[-20]
    )
    assert early_slope > 4 * late_slope, (
        f"Early slope {early_slope:.2f} not >> late slope {late_slope:.2f} — "
        "no yielding visible in the curve."
    )

    # Peak base shear in a reasonable band for this frame — 150-250 kip.
    peak = max(abs(result.base_shear))
    assert 100.0 < peak < 300.0, f"Peak base shear {peak:.1f} kip out of band"

    # Gravity preload stayed applied — column axial force at the start
    # of the pushover (step 1) should be close to P = 180 kip.
    step1_col1 = result.element_forces[1][1]
    axial_step1 = abs(step1_col1[0])
    assert 100.0 < axial_step1 < 260.0, (
        f"Col 1 axial at step 1 = {axial_step1:.1f} kip — gravity preload lost?"
    )
