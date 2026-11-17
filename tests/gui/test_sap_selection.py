"""SAP2000-style selection: box direction, Intersecting Line and the side buttons."""

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


def _window(qtbot, monkeypatch):  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    vm = window._vm
    vm.new_project()
    project = vm.project
    # Two columns (1-2 and 3-4) and a beam 2-4 on top.
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
    canvas = window._canvas
    # A fixed projection: x * 50 + 100 across, z * 50 + 100 up (device pixels
    # from the bottom-left of a 600 px high view).
    monkeypatch.setattr(
        canvas,
        "_project_to_display",
        lambda coords: np.asarray([(c[0] * 50 + 100, c[2] * 50 + 100) for c in coords]),
    )
    monkeypatch.setattr(canvas, "height", lambda: 600)
    monkeypatch.setattr(canvas, "devicePixelRatioF", lambda: 1.0)
    canvas.selection.clear()
    return window


def _drag(canvas, start: tuple[float, float], end: tuple[float, float]) -> None:  # type: ignore[no-untyped-def]
    for kind, pos in (
        (QEvent.Type.MouseButtonPress, start),
        (QEvent.Type.MouseMove, end),
        (QEvent.Type.MouseButtonRelease, end),
    ):
        buttons = (
            Qt.MouseButton.NoButton
            if kind == QEvent.Type.MouseButtonRelease
            else Qt.MouseButton.LeftButton
        )
        event = QMouseEvent(
            kind,
            QPointF(*pos),
            QPointF(*pos),
            Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        {
            QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
            QEvent.Type.MouseMove: canvas.mouseMoveEvent,
            QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
        }[kind](event)


def test_left_to_right_is_a_window_and_right_to_left_a_crossing_box(qtbot, monkeypatch) -> None:
    window = _window(qtbot, monkeypatch)
    canvas = window._canvas
    try:
        # Screen (Qt, y down): column 1-2 at x = 100 from y 500 to 350; the box
        # x 80..120, y 400..600 holds joint 1 only and cuts the column.
        _drag(canvas, (80.0, 400.0), (120.0, 590.0))
        assert canvas.selection.nodes == {1} and canvas.selection.elements == frozenset()
        canvas.selection.clear()
        _drag(canvas, (120.0, 590.0), (80.0, 400.0))
        assert canvas.selection.nodes == {1} and canvas.selection.elements == {1}
    finally:
        window._help_controller.uninstall()


def test_an_intersecting_line_takes_the_columns_it_cuts_once(qtbot, monkeypatch) -> None:
    window = _window(qtbot, monkeypatch)
    canvas = window._canvas
    try:
        window._act_select_line.trigger()
        assert canvas.line_select_armed
        # A horizontal line at mid-height (z = 1.5: Qt y = 600 - 175 = 425)
        # crosses both columns and not the beam.
        _drag(canvas, (50.0, 425.0), (450.0, 425.0))
        assert canvas.selection.elements == {1, 2}
        assert canvas.selection.nodes == frozenset()
        assert not canvas.line_select_armed
        assert not window._act_select_line.isChecked()
    finally:
        window._help_controller.uninstall()


def test_the_side_buttons_are_all_ps_clr_and_line(qtbot, monkeypatch) -> None:
    window = _window(qtbot, monkeypatch)
    try:
        assert [a.iconText() for a in window._selection_toolbar_actions()] == [
            "all",
            "ps",
            "clr",
            "line",
        ]
        window._act_select_all.trigger()
        window._act_clear_selection.trigger()
        assert window._act_previous_selection.isEnabled()  # without opening the menu
        window._act_previous_selection.trigger()
        assert window._canvas.selection.elements == {1, 2, 3}
    finally:
        window._help_controller.uninstall()
