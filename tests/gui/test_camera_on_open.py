"""A new file opens in a camera fitted to *its* model.

A 2D file is shown face on. Opening a 3D file next used to keep that direction
(and, worse, re-fit to furniture sized for the previous model), so the new
model looked like a long, flat elevation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.views.main_window import MainWindow

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.gui
def test_a_3d_project_after_a_2d_one_opens_isometric_and_fitted(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.waitExposed(window)

    window._vm.open(EXAMPLES / "ex1a_canti2d.osmodel")
    window._apply_project_view_settings()
    qtbot.wait(50)

    window._vm.open(EXAMPLES / "space_frame_3d.osmodel")
    window._apply_project_view_settings()
    qtbot.wait(50)

    camera = window._canvas.camera
    direction = np.asarray(camera.position, dtype=float) - np.asarray(
        camera.focal_point, dtype=float
    )
    direction /= np.linalg.norm(direction)

    # The default isometric view looks from +X, +Y, +Z. A front view left over
    # from the 2D file would have a negative Y component.
    assert direction[1] > 0.3
    assert direction[0] > 0.3
    assert direction[2] > 0.3
    # A fit to the old model's triad would be ~156; the new model is ~20.
    assert camera.distance < 100.0
