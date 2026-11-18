"""Design → Member Classification through the dialog and the menu."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.views.dialogs.member_classification import MemberClassificationDialog


def _portal():  # type: ignore[no-untyped-def]
    from tests.unit.test_direct_analysis import _portal

    return _portal()


@pytest.mark.gui
def test_the_dialog_lists_members_and_sets_roles(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    dialog = MemberClassificationDialog(project)
    qtbot.addWidget(dialog)
    assert dialog.member_count() == 3
    assert dialog._table.item(0, 1).text() == "1"
    assert dialog._roles[1].currentText() == "Auto (column)"
    assert dialog._table.item(2, 3).text() == "240"
    dialog.set_role(3, "brace")
    settings = dialog.settings()
    assert [(m.element_id, m.role) for m in settings.members] == [(3, "brace")]
    # Back to auto removes the override.
    project.design = settings
    again = MemberClassificationDialog(project)
    qtbot.addWidget(again)
    assert again._roles[3].currentData() == "brace"
    again.set_role(3, None)
    assert again.settings().members == []


@pytest.mark.gui
def test_the_menu_stores_the_roles_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_portal())

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self.set_role(1, "beam")
        return 1

    monkeypatch.setattr(MemberClassificationDialog, "exec", _accept)
    assert mw._act_member_classification.isEnabled()
    mw._act_member_classification.trigger()
    project = mw._vm.project
    assert project.design.member(1).role == "beam"
    assert "Member classification: 3 member(s)" in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert project.design is None
