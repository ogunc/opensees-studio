"""View → Zoom In / Zoom Out / Zoom Window, driven through the main window's actions."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from opensees_studio.core import ElasticBeamColumn, Node
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def _window(qtbot):  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    vm = window._vm
    vm.new_project()
    project = vm.project
    project.nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(0.0, 0.0, 3.0)),
        Node(id=3, coords=(6.0, 0.0, 0.0)),
        Node(id=4, coords=(6.0, 0.0, 3.0)),
    ]
    project.elements = [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
        ElasticBeamColumn(id=3, nodes=(2, 4), section_id=1),
    ]
    vm.projectChanged.emit(project)
    window._canvas.selection.clear()
    return window


def _scale(camera) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    return camera.GetViewAngle(), camera.GetParallelScale()


def _drag(canvas, start: tuple[float, float], end: tuple[float, float]) -> None:  # type: ignore[no-untyped-def]
    for kind, pos, button, buttons in (
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        event = QMouseEvent(
            kind, QPointF(*pos), QPointF(*pos), button, buttons, Qt.KeyboardModifier.NoModifier
        )
        {
            QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
            QEvent.Type.MouseMove: canvas.mouseMoveEvent,
            QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
        }[kind](event)


def test_the_zoom_in_and_out_actions_zoom_without_an_error(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The actions used to hand ``checked`` (False) to the canvas as the factor:
    Zoom Out divided by zero and Zoom In collapsed the view."""
    window = _window(qtbot)
    camera = window._canvas.camera
    before = _scale(camera)

    window._act_zoom_in.trigger()
    zoomed_in = _scale(camera)
    window._act_zoom_out.trigger()
    back = _scale(camera)

    assert zoomed_in[0] < before[0] or zoomed_in[1] < before[1]
    assert back == pytest.approx(before)


def test_zoom_window_frames_the_rectangle_and_selects_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    # VTK only knows the viewport size once the window is on screen.
    window.show()
    qtbot.waitExposed(window)
    canvas = window._canvas
    canvas.camera.parallel_projection = True
    width, height = canvas.renderer.GetSize()
    dpr = float(canvas.devicePixelRatioF())
    w, h = width / dpr, height / dpr
    scale_before = canvas.camera.GetParallelScale()
    focal_before = np.asarray(canvas.camera.GetFocalPoint())

    # The model point drawn at the rectangle's centre before the zoom.
    corner = (w / 4, h / 4)
    renderer = canvas.renderer
    renderer.SetWorldPoint(*focal_before, 1.0)
    renderer.WorldToDisplay()
    depth = renderer.GetDisplayPoint()[2]
    renderer.SetDisplayPoint(corner[0] / 2 * dpr, height - corner[1] / 2 * dpr, depth)
    renderer.DisplayToWorld()
    target = np.asarray(renderer.GetWorldPoint())
    target = target[:3] / target[3]

    window._act_zoom_window.trigger()
    assert canvas.zoom_window_armed
    # A quarter of the view, off centre: the zoom is about four times.
    _drag(canvas, (0.0, 0.0), corner)

    assert canvas.camera.GetParallelScale() == pytest.approx(scale_before / 4, rel=0.05)
    # ... and that point is now in the middle of the view.
    centre = canvas._project_to_display(target[None, :])[0]
    assert centre == pytest.approx((width / 2, height / 2), abs=2.0)
    assert not canvas.selection.nodes and not canvas.selection.elements
    # One rectangle, then the command switches itself off.
    assert not canvas.zoom_window_armed
    assert not window._act_zoom_window.isChecked()


def test_esc_cancels_an_armed_zoom_window(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    window._act_zoom_window.trigger()
    window._on_clear_selection()
    assert not window._canvas.zoom_window_armed
    assert not window._act_zoom_window.isChecked()
