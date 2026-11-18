"""Define → Section Cuts from the window, and the group a cut uses cannot be removed."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import SetGroupsCommand
from opensees_studio.core import Group
from opensees_studio.views.dialogs.groups import SectionCutsDialog


@pytest.mark.gui
def test_define_a_cut_then_the_group_is_kept(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project()
    vm.apply_command(SetGroupsCommand(vm, [Group(id=3, name="piers")]))
    assert mw._act_section_cuts in {
        a for m in mw.menuBar().actions() if m.menu() for a in m.menu().actions()
    }

    def _exec(d: SectionCutsDialog) -> int:
        d._on_add()
        d.table.item(0, 2).setText("1")
        with pytest.raises(ValueError, match="all three"):
            d.section_cuts()
        d.table.item(0, 3).setText("2")
        d.table.item(0, 4).setText("3")
        return 1

    monkeypatch.setattr(SectionCutsDialog, "exec", _exec)
    mw._on_define_section_cuts()
    (cut,) = vm.project.section_cuts
    assert (cut.name, cut.group_id, cut.centre) == ("SCUT1", 3, (1.0, 2.0, 3.0))

    with pytest.raises(ValueError, match="SCUT1"):
        vm.apply_command(SetGroupsCommand(vm, []))
    assert [g.id for g in vm.project.groups] == [3]
