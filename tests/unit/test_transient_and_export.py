"""Tests for new TransientResults accessors and animation_export service."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from opensees_studio.services.results import TransientResults


@pytest.fixture
def fake_transient_h5(tmp_path: Path) -> Path:
    """Synthetic 5-step transient with disp/vel/accel for nodes 1, 2."""
    import h5py

    h5_path = tmp_path / "fake_case.h5"
    n_steps = 5
    ndf = 6
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("time", data=np.linspace(0.0, 0.04, n_steps))
        for nid in (1, 2):
            base = nid * 10.0
            f.create_dataset(f"nodes/{nid}/disp",
                             data=np.full((n_steps, ndf), base))
            f.create_dataset(f"nodes/{nid}/vel",
                             data=np.full((n_steps, ndf), base + 0.1))
            f.create_dataset(f"nodes/{nid}/accel",
                             data=np.full((n_steps, ndf), base + 0.2))
        f.create_dataset("elements/100/forces",
                         data=np.full((n_steps, 12), 5.0))
    return h5_path


def test_node_disp_vel_accel_history_round_trip(fake_transient_h5: Path) -> None:
    r = TransientResults(case_id=1, case_name="t",
                         h5_path=fake_transient_h5, n_steps=5, dt=0.01)
    np.testing.assert_array_equal(r.node_disp_history(1), np.full((5, 6), 10.0))
    np.testing.assert_array_equal(r.node_vel_history(1), np.full((5, 6), 10.1))
    np.testing.assert_array_equal(r.node_accel_history(1), np.full((5, 6), 10.2))
    np.testing.assert_array_equal(r.node_disp_history(2), np.full((5, 6), 20.0))


def test_missing_history_raises_keyerror(tmp_path: Path) -> None:
    """Older runs (pre-Phase-7c) only stored disp; vel/accel must error
    explicitly so the caller knows to re-run, not silently return zeros."""
    import h5py

    h5_path = tmp_path / "old_case.h5"
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("time", data=np.array([0.0, 0.01]))
        f.create_dataset("nodes/1/disp", data=np.zeros((2, 6)))

    r = TransientResults(case_id=1, case_name="x",
                         h5_path=h5_path, n_steps=2, dt=0.01)
    # disp works:
    assert r.node_disp_history(1).shape == (2, 6)
    # vel/accel raise:
    with pytest.raises(KeyError, match="vel"):
        r.node_vel_history(1)
    with pytest.raises(KeyError, match="accel"):
        r.node_accel_history(1)


def test_export_mode_shape_video_writes_file(tmp_path: Path) -> None:
    """Smoke: export ⇒ produces a non-empty file."""
    pytest.importorskip("imageio")
    import pyvista as pv

    from opensees_studio.services.animation_export import export_mode_shape_video

    plotter = pv.Plotter(off_screen=True, window_size=(160, 120))
    sphere = pv.Sphere(radius=1.0)
    plotter.add_mesh(sphere)

    captured = []

    def set_phase(phase: float) -> None:
        captured.append(phase)

    out = tmp_path / "anim.gif"
    export_mode_shape_video(plotter, set_phase, out, n_frames=4, fps=4)
    plotter.close()

    assert out.exists()
    assert out.stat().st_size > 0
    # 4 frames called → 4 phases recorded.
    assert len(captured) == 4


def test_export_time_history_video_decimates(tmp_path: Path) -> None:
    pytest.importorskip("imageio")
    import pyvista as pv

    from opensees_studio.services.animation_export import (
        export_time_history_video,
    )

    plotter = pv.Plotter(off_screen=True, window_size=(160, 120))
    plotter.add_mesh(pv.Cube())

    seen_steps = []

    def set_step(step: int) -> None:
        seen_steps.append(step)

    out = tmp_path / "th.gif"
    # 100 steps with every=10 → 10 frames captured.
    export_time_history_video(plotter, set_step, out, n_steps=100,
                              fps=4, every=10)
    plotter.close()

    assert out.exists()
    assert seen_steps == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
