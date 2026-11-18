"""Design → Built-Up Shapes through the dialog and the menu."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core import Project, ProjectMeta, UnitSystem
from opensees_studio.core.design.built_up_model import BuiltUpShape
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.views.dialogs.built_up_shapes import BuiltUpShapesDialog


def _project() -> Project:
    return Project(meta=ProjectMeta(units=UnitSystem.US_IN_KIP), ndm=2, ndf=3)


@pytest.mark.gui
def test_the_dialog_computes_properties_and_new_sections(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _project()
    dialog = BuiltUpShapesDialog(project)
    qtbot.addWidget(dialog)
    dialog.add_shape()
    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 6).text() == "41"  # A = 2 x 12 x 1 + 34 x 0.5
    # h/tw = 68 <= 3.76 sqrt(E/Fy) = 90.6: a compact web in flexure.
    assert dialog._table.item(0, 10).text() == "compact (68)"
    dialog._table.item(0, 0).setText("PG1")
    (shape,) = dialog.settings().built_up
    assert shape.name == "PG1"
    (section,) = dialog.new_sections()
    assert section.name == "PG1" and section.id == 1


@pytest.mark.gui
def test_duplicate_names_disable_ok(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _project()
    project.design = DesignSettings(
        built_up=[BuiltUpShape(name="A", d=20.0, bf=8.0, tf=0.5, tw=0.25)]
    )
    dialog = BuiltUpShapesDialog(project)
    qtbot.addWidget(dialog)
    dialog.add_shape()
    dialog._table.item(1, 0).setText("a")
    from PySide6.QtWidgets import QDialogButtonBox

    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "used twice" in dialog._message.text()


@pytest.mark.gui
def test_the_menu_stores_shapes_and_sections_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_project())

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self.add_shape()
        return 1

    monkeypatch.setattr(BuiltUpShapesDialog, "exec", _accept)
    assert mw._act_built_up.isEnabled()
    mw._act_built_up.trigger()
    project = mw._vm.project
    assert [s.name for s in project.design.built_up] == ["BU1"]
    assert [s.name for s in project.sections] == ["BU1"]
    assert "Built-up shapes: 1 defined, 1 analysis section(s) added." in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert project.design is None and project.sections == []
