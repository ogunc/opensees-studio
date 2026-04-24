"""Integration test for the Simply Supported Beam (Quad) example (Ex 6.4)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_beam_quad_2d_midspan_deflection(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """10-step LoadControl on a 16×4 plane-stress quad mesh — reference
    midspan deflection ≈ 0.394 in (matches the OpenSees Wiki Ex 6.4 result).
    Validates the new QuadElement emit path for ndm=2, ndf=2 models.
    """
    from examples.beam_quad_2d import (
        _mid_bottom_node_id,
        _mid_top_node_id,
        build_beam_quad_2d,
    )
    proj = build_beam_quad_2d()
    proj.validate_references()

    path = tmp_path / "beam_quad.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()

    result = OpenSeesRunner(reloaded).run(reloaded.analyses[0])

    l1 = _mid_bottom_node_id()
    l2 = _mid_top_node_id()
    uy_bottom = result.node_disp[l1][-1, 1]
    uy_top = result.node_disp[l2][-1, 1]

    # Reference (pure openseespy with the same mesh): Uy ≈ -0.3943 in at
    # both midspan nodes after 10 steps of LoadControl (load factor = 10).
    assert uy_bottom == pytest.approx(-0.3943, abs=1e-3)
    assert uy_top == pytest.approx(-0.3943, abs=1e-3)

    # Top and bottom midspan deflections differ only by Poisson-contraction
    # through the beam depth — a few microinches.
    assert abs(uy_top - uy_bottom) < 1e-4

    # By symmetry, left and right support reactions must balance the two
    # 10-kip midspan loads (total -20 kip vertical).
    assert reloaded.nodes[0].id == 1     # left pin
    reaction_sum_fy = sum(
        result.node_reaction[nid][-1, 1]
        for nid in (1, 17)              # node 17 = (L, 0) = roller
    )
    assert reaction_sum_fy == pytest.approx(20.0, abs=1e-6)


def test_beam_quad_2d_free_vibration_chain(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """TransientCase with preload + remove_patterns + mode-1 Rayleigh.

    Confirms the chained-analysis support: after the Static preload,
    dropping pattern 1 leaves the beam oscillating freely about Uy=0
    with 2% stiffness-proportional damping, and the amplitude decays
    monotonically in the envelope sense.
    """
    from examples.beam_quad_2d import (
        _mid_bottom_node_id,
        build_beam_quad_2d,
    )
    proj = build_beam_quad_2d()
    proj.validate_references()

    path = tmp_path / "beam_quad.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()

    results_dir = Path(tempfile.mkdtemp(prefix="beamvib_"))
    r = OpenSeesRunner(reloaded).run(reloaded.analyses[1], results_dir=results_dir)

    import h5py
    with h5py.File(r.h5_path) as f:
        t = f["time"][:]
        u = f[f"nodes/{_mid_bottom_node_id()}/disp"][:, 1]

    # Transient starts at t=0 (loadConst reset) and runs 1500 × 0.5 = 750 s.
    assert t[0] == pytest.approx(0.5, abs=0.01)
    assert t[-1] == pytest.approx(750.0, abs=0.5)

    # Initial displacement inherits the ~0.394-in static sag. The first
    # sample is one transient step in (dt = 0.5 s), so we're a hair away
    # from the peak but still well inside the first half-cycle.
    assert u[0] == pytest.approx(-0.394, abs=0.02)

    # Oscillatory motion: amplitude swings to both signs.
    assert u.min() < -0.1
    assert u.max() > +0.05

    # 2 % stiffness-proportional damping over 750 s drives the amplitude
    # to well below the initial sag — envelope (peak-to-peak across the
    # final 100 samples) should be a small fraction of the initial |u|.
    final_envelope = abs(u[-100:]).max()
    assert final_envelope < 0.05, (
        f"Final-envelope amplitude {final_envelope:.4f} in — "
        "damping did not attenuate the free-vibration response."
    )
