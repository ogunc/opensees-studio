"""Define → Groups, Assign → Assign to Group, Select → By Group and pruning on delete."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import (
    AddElementsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    DeleteElementsCommand,
    DeleteNodesCommand,
)
from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node
from opensees_studio.views.dialogs.groups import NEW_GROUP, AssignGroupDialog, GroupsDialog


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project()
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=i, coords=(float(i), 0.0, 0.0)) for i in (1, 2, 3)])
    )
    vm.apply_command(
        AddSectionsCommand(vm, [ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0, Iy=1.0, G=1.0, J=1.0)])
    )
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
            ],
        )
    )
    return mw


def _accept(monkeypatch, cls, fill=None):  # type: ignore[no-untyped-def]
    def _exec(self) -> int:  # type: ignore[no-untyped-def]
        if fill is not None:
            fill(self)
        return 1

    monkeypatch.setattr(cls, "exec", _exec)


@pytest.mark.gui
def test_the_menus_hold_the_group_actions(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    menus = {a.text(): a.menu() for a in mw.menuBar().actions()}
    assert mw._act_groups in menus["&Define"].actions()
    assert mw._act_assign_group in menus["&Assign"].actions()
    assert mw._menu_select_by_group.menuAction() in menus["&Select"].actions()


@pytest.mark.gui
def test_assign_a_new_group_then_select_it_back(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection({1, 2}, {1})
    mw._refresh_action_enablement()
    assert mw._act_assign_group.isEnabled()

    def fill(d: AssignGroupDialog) -> None:
        assert d.group_id == NEW_GROUP
        d.new_name.setText("Bay A")

    _accept(monkeypatch, AssignGroupDialog, fill)
    mw._on_assign_group()
    (group,) = mw._vm.project.groups
    assert (group.name, group.node_ids, group.element_ids) == ("Bay A", [1, 2], [1])

    mw._canvas.selection.set_selection(set(), set())
    mw._fill_select_by_group(mw._menu_select_by_group)
    (action,) = mw._menu_select_by_group.actions()
    action.trigger()
    assert (set(mw._canvas.selection.nodes), set(mw._canvas.selection.elements)) == ({1, 2}, {1})

    mw._vm.undo_stack.undo()  # one macro: the group and its members go together
    assert not mw._vm.project.groups


@pytest.mark.gui
def test_remove_from_an_existing_group(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection({1, 2, 3}, {1, 2})
    _accept(monkeypatch, AssignGroupDialog)
    mw._on_assign_group()
    mw._canvas.selection.set_selection({3}, {2})

    def fill(d: AssignGroupDialog) -> None:
        d.group_combo.setCurrentIndex(0)
        next(b for b in d.mode_buttons.buttons() if b.property("mode") == "remove").setChecked(True)

    _accept(monkeypatch, AssignGroupDialog, fill)
    mw._on_assign_group()
    (group,) = mw._vm.project.groups
    assert (group.node_ids, group.element_ids) == ([1, 2], [1])


@pytest.mark.gui
def test_define_groups_renames_and_removes(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)

    def add_two(d: GroupsDialog) -> None:
        d._on_add()
        d._on_add()
        d.table.item(0, 0).setText("Columns")

    _accept(monkeypatch, GroupsDialog, add_two)
    mw._on_define_groups()
    assert [g.name for g in mw._vm.project.groups] == ["Columns", "GROUP2"]
    assert len({g.colour for g in mw._vm.project.groups}) == 2

    def repeat_name(d: GroupsDialog) -> None:
        d.table.item(1, 0).setText("columns")
        with pytest.raises(ValueError, match="Two groups"):
            d.groups()
        d.table.selectRow(1)
        d._on_remove()

    _accept(monkeypatch, GroupsDialog, repeat_name)
    mw._on_define_groups()
    assert [g.name for g in mw._vm.project.groups] == ["Columns"]


@pytest.mark.gui
def test_deleting_members_prunes_groups_and_undo_restores(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    vm = mw._vm
    mw._canvas.selection.set_selection({1, 2, 3}, {1, 2})
    _accept(monkeypatch, AssignGroupDialog)
    mw._on_assign_group()

    vm.apply_command(DeleteElementsCommand(vm, {1}))
    assert vm.project.groups[0].element_ids == [2]
    vm.apply_command(DeleteNodesCommand(vm, {3}))  # cascades element 2
    assert (vm.project.groups[0].node_ids, vm.project.groups[0].element_ids) == ([1, 2], [])
    vm.undo_stack.undo()
    vm.undo_stack.undo()
    assert (vm.project.groups[0].node_ids, vm.project.groups[0].element_ids) == ([1, 2, 3], [1, 2])
