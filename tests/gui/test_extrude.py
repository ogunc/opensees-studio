"""Edit → Extrude: joints into column stacks, frames into shell strips."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (
    AddElementsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    ExtrudeCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    ShellMITC4Element,
)
from opensees_studio.viewmodels import ProjectViewModel

pytestmark = pytest.mark.gui


def _vm() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(6, 0, 0))])
    )
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [
                ElasticSection(id=1, name="Col", E=2e11, A=0.01, Iz=1e-4, Iy=1e-4, G=8e10, J=1e-5),
                ElasticMembranePlateSection(id=2, name="Wall", E=3e10, nu=0.2, h=0.2),
            ],
        )
    )
    return vm


def _coords(vm: ProjectViewModel, node_id: int) -> tuple[float, ...]:
    return tuple(next(n.coords for n in vm.project.nodes if n.id == node_id))


def test_joints_become_a_column_stack(qtbot) -> None:
    vm = _vm()
    command = ExtrudeCommand(vm, {1, 2}, set(), (0.0, 0.0, 3.0), 2, 1)
    vm.apply_command(command)
    frames = vm.project.elements
    assert len(frames) == 4 and all(isinstance(e, ElasticBeamColumn) for e in frames)
    assert all(e.section_id == 1 for e in frames)
    first = next(e for e in frames if e.nodes[0] == 1)
    assert _coords(vm, first.nodes[1]) == (0.0, 0.0, 3.0)
    assert len(vm.project.nodes) == 6
    vm.undo_stack.undo()
    assert vm.project.elements == [] and len(vm.project.nodes) == 2


def test_a_frame_becomes_a_shell_strip_and_reuses_joints(qtbot) -> None:
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [Node(id=3, coords=(0, 0, 3))]))  # already there
    vm.apply_command(AddElementsCommand(vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)]))
    command = ExtrudeCommand(vm, set(), {1}, (0.0, 0.0, 3.0), 1, 2)
    vm.apply_command(command)
    shells = [e for e in vm.project.elements if isinstance(e, ShellMITC4Element)]
    assert len(shells) == 1
    a, b, c, d = shells[0].nodes
    assert (a, b, d) == (1, 2, 3)  # node 3 reused at (0, 0, 3)
    assert _coords(vm, c) == (6.0, 0.0, 3.0)
    assert command.added_nodes == [c]


def test_a_zero_offset_is_refused(qtbot) -> None:
    with pytest.raises(ValueError, match="non-zero offset"):
        ExtrudeCommand(_vm(), {1}, set(), (0.0, 0.0, 0.0), 1, 1)


def test_the_menu_command_extrudes_the_selection(qtbot, monkeypatch) -> None:
    from opensees_studio.views.dialogs import extrude
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    vm = window._vm
    vm.apply_command(AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0))]))
    vm.apply_command(
        AddSectionsCommand(
            vm, [ElasticSection(id=1, name="C", E=2e11, A=0.01, Iz=1e-4, Iy=1e-4, G=8e10, J=1e-5)]
        )
    )
    monkeypatch.setattr(extrude.ExtrudeDialog, "exec", lambda self: 1)
    monkeypatch.setattr(extrude.ExtrudeDialog, "count", lambda self: 3)
    try:
        window._canvas.selection.set_selection({1}, set())
        window._refresh_action_enablement()
        assert window._act_extrude.isEnabled()
        window._act_extrude.trigger()
        assert len(vm.project.elements) == 3
        assert window._canvas.selection.elements == frozenset(e.id for e in vm.project.elements)
    finally:
        window._help_controller.uninstall()
