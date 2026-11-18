"""MeasureDistanceTool: two node picks, the distance on the clipboard."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication

from opensees_studio.core import Node
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.canvas3d.selection import SelectionState
from opensees_studio.views.tools.measure import MeasureDistanceTool


class _CanvasStub:
    def __init__(self) -> None:
        self.selection = SelectionState()


def _vm_with_nodes() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    assert vm.project is not None
    vm.project.nodes.extend(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(3.0, 4.0, 0.0)),
            Node(id=3, coords=(3.0, 4.0, 12.0)),
        ]
    )
    return vm


@pytest.mark.gui
def test_two_picks_copy_the_distance(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_nodes()
    canvas = _CanvasStub()
    tool = MeasureDistanceTool(canvas, vm)  # type: ignore[arg-type]
    messages: list[str] = []
    tool.statusChanged.connect(messages.append)
    tool.activate()

    tool.on_node_picked(1)
    assert "click the second node" in messages[-1]
    assert tool.prompt().startswith("Measure Distance")
    assert 1 in canvas.selection.nodes

    tool.on_node_picked(2)
    assert QGuiApplication.clipboard().text() == "5"
    assert "5 m" in messages[-1]
    assert "clipboard" in messages[-1]
    assert 1 in canvas.selection.nodes
    assert 2 in canvas.selection.nodes
    assert tool.prompt().startswith("Measure Distance: click the first node")


@pytest.mark.gui
def test_distance_is_three_dimensional(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_nodes()
    tool = MeasureDistanceTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(2)
    tool.on_node_picked(3)

    assert QGuiApplication.clipboard().text() == "12"


@pytest.mark.gui
def test_the_same_node_twice_keeps_waiting(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_nodes()
    tool = MeasureDistanceTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    messages: list[str] = []
    tool.statusChanged.connect(messages.append)
    tool.activate()

    tool.on_node_picked(1)
    QGuiApplication.clipboard().setText("untouched")
    tool.on_node_picked(1)

    assert QGuiApplication.clipboard().text() == "untouched"
    assert "already the first point" in messages[-1]


@pytest.mark.gui
def test_reset_drops_the_first_pick(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_nodes()
    tool = MeasureDistanceTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    tool.reset()

    assert tool.prompt().startswith("Measure Distance: click the first node")
