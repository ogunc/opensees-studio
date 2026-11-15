"""Draw Shell: four clicks make a quadrilateral, three and the first again a triangle."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticMembranePlateSection,
    Node,
    ShellDKGTElement,
    ShellMITC4Element,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.canvas3d import SelectionState
from opensees_studio.views.tools.draw_shell import DrawShellTool

pytestmark = pytest.mark.gui


class _CanvasStub:
    def __init__(self) -> None:
        self.selection = SelectionState()

    def set_snap_preview_enabled(self, _enabled: bool) -> None:
        pass

    def set_snap_reference(self, _point: tuple[float, float, float] | None) -> None:
        pass


def _vm() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0, 0, 3)),
                Node(id=2, coords=(4, 0, 3)),
                Node(id=3, coords=(4, 4, 3)),
                Node(id=4, coords=(0, 4, 3)),
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [
                ElasticMembranePlateSection(id=1, name="Slab 20", E=3e10, nu=0.2, h=0.2),
                ElasticMembranePlateSection(id=2, name="Slab 25", E=3e10, nu=0.2, h=0.25),
            ],
        )
    )
    return vm


def test_four_corners_in_any_order_make_a_flat_quadrilateral(qtbot) -> None:
    vm = _vm()
    tool = DrawShellTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    for node_id in (1, 3, 2, 4):  # a crossed click order
        tool.on_node_picked(node_id)
    (shell,) = vm.project.elements
    assert isinstance(shell, ShellMITC4Element)
    assert shell.section_id == 1  # the first plate section by default
    ring = list(shell.nodes) * 2
    start = ring.index(1)
    # Consistent winding: neighbours around the square, never across it.
    assert ring[start : start + 4] in ([1, 2, 3, 4], [1, 4, 3, 2])
    assert tool._corners == []


def test_three_corners_and_the_first_again_make_a_triangle(qtbot) -> None:
    vm = _vm()
    tool = DrawShellTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    tool.section_id = 2
    for node_id in (1, 2, 3, 1):
        tool.on_node_picked(node_id)
    (shell,) = vm.project.elements
    assert isinstance(shell, ShellDKGTElement)
    assert shell.nodes == (1, 2, 3)
    assert shell.section_id == 2


def test_empty_clicks_create_the_corner_nodes_and_esc_drops_them(qtbot) -> None:
    vm = _vm()
    canvas = _CanvasStub()
    tool = DrawShellTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_empty_clicked(0.0, 0.0, 6.0)
    tool.on_empty_clicked(4.0, 0.0, 6.0)
    assert len(vm.project.nodes) == 6
    assert canvas.selection.nodes == frozenset({5, 6})
    tool.reset()  # Esc
    assert tool._corners == []
    assert vm.project.elements == []


def test_a_repeated_corner_is_not_added_twice(qtbot) -> None:
    vm = _vm()
    tool = DrawShellTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    for node_id in (1, 2, 2, 1):  # the last one is not the closing third corner
        tool.on_node_picked(node_id)
    assert tool._corners == [1, 2]
    assert vm.project.elements == []


def test_the_tool_is_refused_without_a_plate_section(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from opensees_studio.views.main_window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: shown.append(text))
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    try:
        window._act_tool_draw_shell.trigger()
        assert shown and "plate section" in shown[0]
        assert window._act_tool_select.isChecked()
        window._vm.apply_command(
            AddSectionsCommand(
                window._vm, [ElasticMembranePlateSection(id=1, name="Slab", E=3e10, nu=0.2, h=0.2)]
            )
        )
        window._act_tool_draw_shell.trigger()
        assert window._tool_controller.active is window._draw_shell_tool
        assert window._draw_shell_section_action.isVisible()
        assert window._draw_shell_section_combo.currentText() == "Slab"
    finally:
        window._help_controller.uninstall()
