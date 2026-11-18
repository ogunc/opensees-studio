"""The MP4 writer must survive an odd frame size.

libx264 with the ``yuv420p`` pixel format needs both dimensions even, so the
1200x537 a maximised viewport produces used to abort the export with
"height not divisible by 2" and a broken pipe. The writer now pads to a
multiple of two; this test encodes a real file and reads the size back.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("imageio")
pytest.importorskip("imageio_ffmpeg")

from opensees_studio.services.animation_export import (
    export_mode_shape_video,
    export_time_history_video,
)

#: Odd on purpose: 101x99 is what a user's window looks like after chrome.
_ODD_FRAME = (99, 101, 3)


class _FakePlotter:
    """The two calls the exporter makes, and nothing else."""

    def __init__(self) -> None:
        self.phases: list[float] = []

    def render(self) -> None:
        return None

    def screenshot(self, **_kwargs: object) -> np.ndarray:
        return np.zeros(_ODD_FRAME, dtype=np.uint8) + 128


def _read_size(path: Path) -> tuple[int, int]:
    import imageio.v3 as iio

    frame = iio.imread(path, index=0)
    height, width = frame.shape[:2]
    return width, height


def test_odd_height_mp4_is_padded_instead_of_failing(tmp_path: Path) -> None:
    out = tmp_path / "mode.mp4"
    plotter = _FakePlotter()

    export_mode_shape_video(plotter, lambda _phase: None, out, n_frames=3)

    assert out.exists() and out.stat().st_size > 0
    width, height = _read_size(out)
    assert width % 2 == 0
    assert height % 2 == 0


def test_odd_height_time_history_mp4_is_padded(tmp_path: Path) -> None:
    out = tmp_path / "history.mp4"
    plotter = _FakePlotter()

    export_time_history_video(plotter, lambda _step: None, out, n_steps=3)

    assert out.exists() and out.stat().st_size > 0
    width, height = _read_size(out)
    assert width % 2 == 0
    assert height % 2 == 0


def test_even_frames_are_not_resized(tmp_path: Path) -> None:
    """A frame that already fits is written at its own size."""
    out = tmp_path / "even.mp4"

    class _Even(_FakePlotter):
        def screenshot(self, **_kwargs: object) -> np.ndarray:
            return np.zeros((100, 120, 3), dtype=np.uint8)

    export_mode_shape_video(_Even(), lambda _phase: None, out, n_frames=3)

    assert _read_size(out) == (120, 100)
