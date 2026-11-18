"""Assign → Joint → Springs from the window."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import Node
from opensees_studio.views.dialogs.assign_springs import AssignSpringsDialog


@pytest.mark.gui
def test_assign_springs_to_the_selected_joints(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(ndm=2, ndf=3)
    vm.apply_command(AddNodesCommand(vm, [Node(id=i, coords=(float(i), 0.0, 0.0)) for i in (1, 2)]))
    mw._canvas.selection.set_selection({1, 2}, set())
    mw._refresh_action_enablement()
    assert mw._act_assign_springs.isEnabled()

    def _exec(d: AssignSpringsDialog) -> int:
        assert sorted(d.fields) == [0, 2, 4]  # Ux, Uz, Ry of a 2D frame
        d.fields[2].setValue(1500.0)
        return 1

    monkeypatch.setattr(AssignSpringsDialog, "exec", _exec)
    mw._on_assign_springs()
    assert [n.spring for n in vm.project.nodes] == [(0.0, 0.0, 1500.0, 0.0, 0.0, 0.0)] * 2
    vm.undo_stack.undo()
    assert not any(n.has_spring for n in vm.project.nodes)


@pytest.mark.gui
def test_springs_are_drawn(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project()
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=1, coords=(0.0, 0.0, 0.0), spring=(5.0, 0, 0, 0, 0, 0))])
    )
    assert "support_springs" in mw._canvas.actors
