"""Export viewport frames to MP4 / GIF.

Lightweight helper that takes a sequence of phase values, drives the
mode-shape source generator at each phase, captures the plotter window,
and writes the frames to a video/animated-gif file via imageio.

Designed to be runnable from a worker thread; the only Qt interaction
is requesting screenshots from the canvas which is supposed to live on
the main thread.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import numpy as np


def export_mode_shape_video(
    plotter: Any,
    set_frame: Callable[[float], None],
    output_path: Path,
    *,
    n_frames: int = 60,
    fps: int = 30,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Render ``n_frames`` of a one-period sin(2π·t) loop and save them.

    ``set_frame(phase)`` must update the plotter's deformation source for
    a phase in [-1, 1]. ``output_path`` extension determines the format
    (``.mp4``, ``.gif``, ``.webm``).
    """
    import imageio.v3 as iio

    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frames: list[np.ndarray] = []
    for i in range(n_frames):
        phase = math.sin(2.0 * math.pi * i / n_frames)
        set_frame(phase)
        plotter.render()
        # Prefer .screenshot() — works for off-screen and on-screen plotters.
        img = plotter.screenshot(transparent_background=False, return_img=True)
        frames.append(np.asarray(img))
        if progress is not None:
            progress(i + 1, n_frames)

    suffix = output_path.suffix.lower()
    if suffix == ".gif":
        iio.imwrite(output_path, frames, duration=1.0 / fps, loop=0)
    else:
        # MP4 / WebM use FFmpeg backend.
        iio.imwrite(output_path, frames, fps=fps, codec="libx264")


def export_time_history_video(
    plotter: Any,
    set_step: Callable[[int], None],
    output_path: Path,
    n_steps: int,
    *,
    fps: int = 30,
    every: int = 1,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Render the deformed shape at ``n_steps`` time steps and save a video.

    ``set_step(step_index)`` must update the renderer for the given step.
    ``every`` decimates the time series (fps stays as requested) so a
    1000-step run with ``every=10`` writes 100 frames.
    """
    import imageio.v3 as iio

    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    indices = list(range(0, n_steps, max(1, every)))
    frames: list[np.ndarray] = []
    for k, step in enumerate(indices):
        set_step(step)
        plotter.render()
        img = plotter.screenshot(transparent_background=False, return_img=True)
        frames.append(np.asarray(img))
        if progress is not None:
            progress(k + 1, len(indices))

    suffix = output_path.suffix.lower()
    if suffix == ".gif":
        iio.imwrite(output_path, frames, duration=1.0 / fps, loop=0)
    else:
        iio.imwrite(output_path, frames, fps=fps, codec="libx264")
