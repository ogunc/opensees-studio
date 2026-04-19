"""Round-trip + physics check on the shipped moment-curvature example."""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_moment_curvature_example_round_trips_and_converges(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """build_moment_curvature() → save → load → run → expected shape."""
    from examples.moment_curvature import (
        build_moment_curvature,
        COL_DEPTH,
        COVER,
        E_STEEL,
        FY,
        MU,
        NUM_INCR,
    )
    proj = build_moment_curvature()
    proj.validate_references()

    # Save + reload — catches schema drift.
    from opensees_studio.services import save_project
    path = tmp_path / "mk.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()
    assert reloaded.meta.units.value.startswith("US (in,")

    result = OpenSeesRunner(reloaded).run(reloaded.analyses[0])

    # Yield curvature estimate.
    d = COL_DEPTH - COVER
    ky = (FY / E_STEEL) / (0.7 * d)

    # At least half of the NUM_INCR pushover steps converged.
    assert len(result.control_disp) > NUM_INCR * 0.5, (
        "Pushover bailed out prematurely — check Concrete01 softening"
    )
    # Reached the mu * Ky target.
    assert result.control_disp[-1] == pytest.approx(MU * ky, rel=1e-2)
    # Moment at yield curvature is plausible: > 3 kip·in and < 10 kip·in per rebar
    # → for 8 bars total, the section moment capacity is roughly O(3000-6000) kip·in.
    peak_moment = max(abs(m) for m in result.base_shear)
    assert 2000 < peak_moment < 10000, (
        f"Peak moment {peak_moment:.1f} kip·in is outside the "
        "expected RC section range"
    )
