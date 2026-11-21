"""Selection modifiers stay with the current click, and tools follow the view.

Two regressions this guards:

* a Ctrl+click made while a tool was armed used to leave Ctrl "stuck"; the
  next plain click in Select then behaved as a removal and selected nothing;
* Measure Distance used to receive no picks in a secondary ``View → New View``
  window because the tool controller stayed attached to the main canvas.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtTest import QTest

from opensees_studio.commands import AddNodesCommand, SetCoordSystemsCommand
from opensees_studio.core import CoordinateGridSystem, GridSystem, Node, make_grid_lines
from opensees_studio.views.main_window import MainWindow


def _move_pointer(canvas, pos: QPoint) -> None:  # type: ignore[no-untyped-def]
    """Send a move event even when the platform cursor already sits there."""
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        canvas.mapToGlobal(pos),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(event)


def _setup(qtbot) -> MainWindow:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.waitExposed(window)
    window._vm.new_project(ndm=2, ndf=3)
    assert window._vm.project is not None
    window._vm.apply_command(
        AddNodesCommand(
            window._vm,
            [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(10.0, 0.0, 0.0))],
        )
    )
    return window


def _node_point(canvas, project, node_id: int) -> QPoint:  # type: ignore[no-untyped-def]
    node = next(item for item in project.nodes if item.id == node_id)
    display = canvas._project_to_display(np.asarray([node.coords], dtype=float))[0]
    dpr = canvas.devicePixelRatioF()
    return QPoint(int(display[0] / dpr), int(canvas.height() - display[1] / dpr))


def _world_point(canvas, world: tuple[float, float, float]) -> QPoint:  # type: ignore[no-untyped-def]
    display = canvas._project_to_display(np.asarray([world], dtype=float))[0]
    dpr = canvas.devicePixelRatioF()
    return QPoint(int(display[0] / dpr), int(canvas.height() - display[1] / dpr))


@pytest.mark.gui
def test_plain_select_click_after_ctrl_click_with_a_tool(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _setup(qtbot)
    canvas = window._canvas
    canvas.view_xy()
    canvas.render()
    qtbot.wait(50)
    assert window._vm.project is not None
    first = _node_point(canvas, window._vm.project, 1)
    second = _node_point(canvas, window._vm.project, 2)

    window._on_measure_tool()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, first)
    window._on_select_tool()
    canvas.selection.clear()

    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, second)

    assert canvas.selection.nodes == frozenset({2})


@pytest.mark.gui
def test_ctrl_click_removes_in_select(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _setup(qtbot)
    canvas = window._canvas
    canvas.view_xy()
    canvas.render()
    qtbot.wait(50)
    assert window._vm.project is not None
    second = _node_point(canvas, window._vm.project, 2)

    canvas.selection.select_node(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, second)

    assert canvas.selection.nodes == frozenset()


@pytest.mark.gui
def test_measure_works_in_a_secondary_view(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _setup(qtbot)
    window._on_new_view_window()
    view = window._view_windows[-1]
    canvas = view.canvas
    canvas.view_xy()
    canvas.render()
    qtbot.wait(50)
    assert window._vm.project is not None
    first = _node_point(canvas, window._vm.project, 1)
    second = _node_point(canvas, window._vm.project, 2)

    QGuiApplication.clipboard().setText("")
    window._on_measure_tool()

    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, second)

    assert window._tool_controller._canvas is canvas
    assert window._measure_tool is not None
    assert window._measure_tool.canvas is canvas
    assert QGuiApplication.clipboard().text() == "10"


@pytest.mark.gui
def test_measure_between_joints_in_3d_is_three_dimensional(qtbot) -> None:  # type: ignore[no-untyped-def]
    """An isometric view: the two clicks pick joints at different X, Y and Z."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.waitExposed(window)
    window._vm.new_project(ndm=3, ndf=6)
    assert window._vm.project is not None
    window._vm.apply_command(
        AddNodesCommand(
            window._vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0)),
                Node(id=2, coords=(3.0, 4.0, 12.0)),
            ],
        )
    )
    canvas = window._canvas
    canvas.view_isometric()
    canvas.render()
    qtbot.wait(50)
    assert window._vm.project is not None
    first = _node_point(canvas, window._vm.project, 1)
    second = _node_point(canvas, window._vm.project, 2)

    QGuiApplication.clipboard().setText("")
    window._on_measure_tool()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, second)

    assert QGuiApplication.clipboard().text() == "13"


@pytest.mark.gui
def test_measure_between_grid_intersections(qtbot) -> None:  # type: ignore[no-untyped-def]
    """No joints: the two points come from the grid, with the same guide."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.waitExposed(window)
    window._vm.new_project(ndm=3, ndf=6)
    assert window._vm.project is not None
    window._vm.apply_command(
        SetCoordSystemsCommand(
            window._vm,
            [
                CoordinateGridSystem(
                    name="Global",
                    grid=GridSystem(
                        x_grid_lines=make_grid_lines("X", [0.0, 10.0]),
                        y_grid_lines=make_grid_lines("Y", [0.0, 10.0]),
                        z_grid_lines=make_grid_lines("Z", [0.0]),
                    ),
                ),
            ],
        )
    )
    canvas = window._canvas
    canvas.refresh(window._vm.project)
    canvas.view_xy()
    canvas.render()
    qtbot.wait(50)
    first = _world_point(canvas, (0.0, 0.0, 0.0))
    second = _world_point(canvas, (10.0, 10.0, 0.0))

    QGuiApplication.clipboard().setText("")
    window._on_measure_tool()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    assert canvas._renderer._measure_anchor_actor is not None

    _move_pointer(canvas, second)
    qtbot.wait(50)
    assert canvas._renderer._measure_guide_actor is not None

    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, second)
    assert float(QGuiApplication.clipboard().text()) == pytest.approx(math.sqrt(200.0))
    assert canvas._renderer._measure_anchor_actor is None
    assert canvas._renderer._measure_guide_actor is None


@pytest.mark.gui
def test_measure_highlights_the_joint_under_the_pointer(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _setup(qtbot)
    canvas = window._canvas
    canvas.view_xy()
    canvas.render()
    qtbot.wait(50)
    assert window._vm.project is not None
    second = _node_point(canvas, window._vm.project, 2)
    seen: list[object] = []
    canvas.cursorMoved.connect(seen.append)

    window._on_measure_tool()
    _move_pointer(canvas, second)
    qtbot.wait(50)

    assert any(isinstance(point, tuple) and point[3] == "node" for point in seen)
    assert canvas._renderer._hover_actor is not None


@pytest.mark.gui
def test_measure_previews_and_clears_the_dashed_guide(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _setup(qtbot)
    canvas = window._canvas
    canvas.view_xy()
    canvas.render()
    qtbot.wait(50)
    project = window._vm.project
    assert project is not None
    first = _node_point(canvas, project, 1)
    second = _node_point(canvas, project, 2)

    window._on_measure_tool()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    assert canvas._renderer._measure_anchor_actor is not None

    _move_pointer(canvas, second)
    qtbot.wait(50)
    assert canvas._renderer._measure_guide_actor is not None
    assert canvas._renderer._measure_label_actor is not None

    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, second)
    assert canvas._renderer._measure_anchor_actor is None
    assert canvas._renderer._measure_guide_actor is None
    assert canvas._renderer._measure_label_actor is None
