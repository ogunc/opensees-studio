"""Edit → Interactive Table Editing from the window: paste, apply as one undo step."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import Node
from opensees_studio.views.dialogs.model_tables import ModelTablesDialog


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.apply_command(AddNodesCommand(mw._vm, [Node(id=1, coords=(0.0, 0.0, 0.0))]))
    return mw


@pytest.mark.gui
def test_paste_new_joints_then_undo(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    assert mw._act_table_editing.isEnabled()

    def fill(d: ModelTablesDialog) -> None:
        joints = d.tables["Joints"]
        joints.add_row()  # the new row is current; a taller block adds rows
        joints.paste("\tA\t1\t2\t3\n\tB\t4\t5\t6\n")
        assert joints.rowCount() == 3
        d.accept()

    def _exec(self: ModelTablesDialog) -> int:
        fill(self)
        return int(self.edited is not None)

    monkeypatch.setattr(ModelTablesDialog, "exec", _exec)
    mw._on_table_editing()
    project = mw._vm.project
    assert [(n.id, n.name, n.coords) for n in project.nodes[1:]] == [
        (2, "A", (1.0, 2.0, 3.0)),
        (3, "B", (4.0, 5.0, 6.0)),
    ]
    mw._vm.undo_stack.undo()
    assert [n.id for n in mw._vm.project.nodes] == [1]


@pytest.mark.gui
def test_a_bad_cell_keeps_the_dialog_open(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    d = ModelTablesDialog(mw._vm.project)
    qtbot.addWidget(d)
    d.tables["Joints"].item(0, 2).setText("oops")
    d.accept()
    assert d.edited is None and "not a number" in d.message.text()


@pytest.mark.gui
def test_elements_cannot_get_new_rows(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    d = ModelTablesDialog(mw._vm.project)
    qtbot.addWidget(d)
    d.tabs.setCurrentWidget(d.tables["Elements"])
    assert not d.add_button.isEnabled()
    d.tables["Elements"].paste("1\t2\n")
    assert d.tables["Elements"].rowCount() == 0
