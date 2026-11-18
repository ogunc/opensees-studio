"""Edit → Delete Loads: the dialog's counts, the removal and its undo."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    NodalLoad,
    Node,
    PointElementLoad,
    UniformElementLoad,
    make_default_section,
)
from opensees_studio.views.dialogs.delete_loads import DeleteLoadsDialog


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(ndm=3, ndf=6, dead_case=True)
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=i, coords=(float(i), 0.0, 0.0)) for i in (1, 2, 3)])
    )
    vm.apply_command(AddSectionsCommand(vm, [make_default_section(1)]))
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
            ],
        )
    )
    pattern = vm.project.load_patterns[0]
    pattern.nodal_loads.append(NodalLoad(node_id=2, forces=(0, 0, -1, 0, 0, 0)))
    pattern.element_loads += [
        UniformElementLoad(element_id=1, wy=-1.0),
        UniformElementLoad(element_id=2, wy=-1.0),
    ]
    pattern.point_loads.append(PointElementLoad(element_id=2, py=-5.0))
    mw._canvas.selection.clear()
    return mw


@pytest.mark.gui
def test_the_dialog_counts_what_it_would_delete(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    dialog = DeleteLoadsDialog(mw._vm.project, selected_nodes=set(), selected_elements={2})
    qtbot.addWidget(dialog)
    assert dialog._scope_selection.isChecked()
    assert not dialog._ok.isEnabled()  # nothing ticked yet
    dialog._kinds["uniform"].setChecked(True)
    assert "(1)" in dialog._kinds["uniform"].text()  # only element 2's
    assert dialog._ok.isEnabled()
    dialog._scope_all.setChecked(True)
    assert "(2)" in dialog._kinds["uniform"].text()
    assert "(1)" in dialog._kinds["self_weight"].text()


@pytest.mark.gui
def test_deleting_frame_loads_of_the_selection_and_undo(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    pattern = mw._vm.project.load_patterns[0]

    def _fake_exec(self: DeleteLoadsDialog) -> int:
        self._kinds["uniform"].setChecked(True)
        self._kinds["point"].setChecked(True)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(DeleteLoadsDialog, "exec", _fake_exec)
    mw._canvas.selection.set_selection(set(), {2})
    mw._act_delete_loads.trigger()

    assert [ul.element_id for ul in pattern.element_loads] == [1]
    assert pattern.point_loads == []
    assert len(pattern.nodal_loads) == 1  # not a ticked type

    mw._vm.undo_stack.undo()
    pattern = mw._vm.project.load_patterns[0]
    assert len(pattern.element_loads) == 2 and len(pattern.point_loads) == 1
