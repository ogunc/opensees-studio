"""MeasureDistanceTool: two node picks, the distance on the clipboard."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from opensees_studio.core import Node
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.canvas3d.selection import SelectionState
from opensees_studio.views.tools.measure import MeasureDistanceTool, Measurement


class _CanvasStub(QObject):
    cursorMoved = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.selection = SelectionState()
        self.anchor: tuple[float, float, float] | None = None
        self.guide: tuple[tuple[float, float, float], tuple[float, float, float], str] | None = None

    def set_snap_preview_enabled(self, _enabled: bool) -> None:
        pass

    def set_measure_anchor(self, point: tuple[float, float, float] | None) -> None:
        self.anchor = point

    def set_measure_guide(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        label: str,
    ) -> None:
        self.guide = (start, end, label)

    def clear_measure_guide(self) -> None:
        self.guide = None

    def clear_measure_preview(self) -> None:
        self.anchor = None
        self.guide = None


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


@pytest.mark.gui
def test_measurement_reports_both_joints_and_the_vector(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_nodes()
    tool = MeasureDistanceTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    seen: list[Measurement] = []
    tool.measurementFinished.connect(seen.append)
    tool.activate()

    tool.on_node_picked(1)
    tool.on_node_picked(3)

    assert len(seen) == 1
    measurement = seen[0]
    assert (measurement.first_node, measurement.second_node) == (1, 3)
    assert measurement.delta == pytest.approx((3.0, 4.0, 12.0))
    assert measurement.distance == pytest.approx(13.0)


@pytest.mark.gui
def test_measure_for_a_dialog_names_it_and_fills_the_listener(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_nodes()
    tool = MeasureDistanceTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    messages: list[str] = []
    seen: list[Measurement] = []
    tool.statusChanged.connect(messages.append)
    tool.measure_for("Move", seen.append)
    tool.activate()

    assert tool.prompt().startswith("Measure for Move")
    tool.on_node_picked(1)
    tool.on_node_picked(2)

    assert seen[0].delta == pytest.approx((3.0, 4.0, 0.0))
    assert "filled the dialog" in messages[-1]

    tool.stop_measuring_for()
    assert tool.prompt().startswith("Measure Distance")


@pytest.mark.gui
def test_the_second_joint_previews_the_dashed_guide(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_nodes()
    canvas = _CanvasStub()
    tool = MeasureDistanceTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    assert canvas.anchor == (0.0, 0.0, 0.0)

    canvas.cursorMoved.emit((3.0, 4.0, 12.0, "node"))
    assert canvas.guide == ((0.0, 0.0, 0.0), (3.0, 4.0, 12.0), "13 m")

    # Leaving the joint drops the preview, but not the red anchor.
    canvas.cursorMoved.emit((1.0, 2.0, 3.0, "grid"))
    assert canvas.guide is None
    assert canvas.anchor == (0.0, 0.0, 0.0)

    # Measuring node 3 clears both transient graphics.
    canvas.cursorMoved.emit((3.0, 4.0, 12.0, "node"))
    tool.on_node_picked(3)
    assert canvas.anchor is None
    assert canvas.guide is None
