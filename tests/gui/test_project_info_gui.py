"""File → Project Information: the cover data dialog and the undoable action."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QTableWidgetItem

from opensees_studio.core import Project
from opensees_studio.core.project import Revision
from opensees_studio.views.dialogs.project_info import ProjectInfoDialog
from opensees_studio.views.main_window import MainWindow


@pytest.mark.gui
def test_the_dialog_returns_the_cover_data(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ProjectInfoDialog(Project().meta)
    qtbot.addWidget(dialog)
    dialog._name.setText("Steel tower")
    dialog._author.setText("A. Engineer")
    dialog._company.setText("ACME Structures")
    dialog._date.setText("2026-11-05")
    dialog._add_revision()
    for column, value in enumerate(("A", "2026-11-01", "AE", "Issued")):
        dialog._revisions.setItem(0, column, QTableWidgetItem(value))
    meta = dialog.meta()
    assert meta.name == "Steel tower"
    assert meta.company == "ACME Structures"
    assert meta.revisions == [Revision(code="A", date="2026-11-01", by="AE", description="Issued")]


@pytest.mark.gui
def test_the_action_stores_the_information_and_undoes_it(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = MainWindow()
    qtbot.addWidget(mw)
    project = Project()
    mw._vm.adopt(project)

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self._name.setText("Tower")
        self._company.setText("ACME")
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ProjectInfoDialog, "exec", _accept)
    mw._act_project_info.trigger()
    assert project.meta.name == "Tower"
    assert project.meta.company == "ACME"
    mw._vm.undo_stack.undo()
    assert project.meta.name == "Untitled"
    assert project.meta.company == ""
