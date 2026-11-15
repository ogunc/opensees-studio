"""Tools → Quick Draw Frame: a click on a grid line draws the member between crossings."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (
    CoordinateGridSystem,
    ElasticBeamColumn,
    GridSystem,
    make_grid_lines,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.canvas3d import SelectionState
from opensees_studio.views.tools.quick_draw import QuickDrawFrameTool

pytestmark = pytest.mark.gui


class _CanvasStub:
    def __init__(self, plane: str | None = None, offset: float | None = None) -> None:
        self.selection = SelectionState()
        self._plane = plane
        self._offset = offset

    def set_snap_preview_enabled(self, _enabled: bool) -> None:
        pass

    def set_snap_reference(self, _point: tuple[float, float, float] | None) -> None:
        pass

    def working_plane_type(self) -> str | None:
        return self._plane

    def working_plane_offset(self) -> float | None:
        return self._offset


def _vm() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.coord_systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", [0.0, 6.0, 12.0]),
                y_grid_lines=make_grid_lines("Y", [0.0, 5.0]),
                z_grid_lines=make_grid_lines("Z", [0.0, 3.0]),
            ),
        )
    ]
    return vm


def _coords(vm: ProjectViewModel, node_id: int) -> tuple[float, ...]:
    return tuple(next(n.coords for n in vm.project.nodes if n.id == node_id))


def test_a_click_on_a_line_draws_the_member_between_its_crossings(qtbot) -> None:
    vm = _vm()
    tool = QuickDrawFrameTool(_CanvasStub("XY", 3.0), vm)  # type: ignore[arg-type]
    tool.activate()
    assert tool.on_plane_point((8.0, 0.3, 3.0)) is True
    (beam,) = vm.project.elements
    assert isinstance(beam, ElasticBeamColumn)
    assert {_coords(vm, n) for n in beam.nodes} == {(6.0, 0.0, 3.0), (12.0, 0.0, 3.0)}
    # The next beam shares the joint at (6, 0, 3).
    tool.on_plane_point((3.0, -0.2, 3.0))
    assert len(vm.project.elements) == 2 and len(vm.project.nodes) == 3


def test_a_click_mid_bay_or_twice_on_a_line_draws_nothing_new(qtbot) -> None:
    vm = _vm()
    tool = QuickDrawFrameTool(_CanvasStub("XY", 0.0), vm)  # type: ignore[arg-type]
    tool.activate()
    messages: list[str] = []
    tool.statusChanged.connect(messages.append)
    tool.on_plane_point((3.0, 2.5, 0.0))
    assert vm.project.elements == [] and "not on a grid line" in messages[-1]
    tool.on_plane_point((3.0, 0.1, 0.0))
    tool.on_plane_point((2.0, 0.0, 0.0))
    assert len(vm.project.elements) == 1 and "already joined" in messages[-1]


def test_in_elevation_a_vertical_line_gives_a_column(qtbot) -> None:
    vm = _vm()
    tool = QuickDrawFrameTool(_CanvasStub("XZ", 0.0), vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_plane_point((6.2, 0.0, 1.5))
    (column,) = vm.project.elements
    assert {_coords(vm, n) for n in column.nodes} == {(6.0, 0.0, 0.0), (6.0, 0.0, 3.0)}


def test_the_window_refuses_it_without_grid_lines(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from opensees_studio.views.main_window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: shown.append(text))
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    try:
        window._act_tool_quick_frame.trigger()
        assert shown and "grid lines" in shown[0]
        assert window._act_tool_select.isChecked()
        window._vm.project.coord_systems = _vm().project.coord_systems
        window._act_tool_quick_frame.trigger()
        assert isinstance(window._tool_controller.active, QuickDrawFrameTool)
        assert window._canvas.plane_click_handler is not None
        assert window._draw_section_action.isVisible()  # the Section box applies
        window._act_tool_select.trigger()
        assert window._canvas.plane_click_handler is None
    finally:
        window._help_controller.uninstall()
