"""Selection modifiers stay with the current click, and tools follow the view.

Two regressions this guards:

* a Ctrl+click made while a tool was armed used to leave Ctrl "stuck"; the
  next plain click in Select then behaved as a removal and selected nothing;
* Measure Distance used to receive no picks in a secondary ``View → New View``
  window because the tool controller stayed attached to the main canvas.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import Node
from opensees_studio.views.main_window import MainWindow


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
