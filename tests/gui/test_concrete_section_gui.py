"""Define → Concrete Section Wizard: inputs in the project's units, preview, one undo step."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QDialogButtonBox

from opensees_studio.core import Project, ProjectMeta
from opensees_studio.core.units import UnitSystem
from opensees_studio.views.dialogs.concrete_section import ConcreteSectionDialog


@pytest.mark.gui
def test_defaults_build_a_confined_fibre_section(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ConcreteSectionDialog(Project(meta=ProjectMeta(), ndm=3, ndf=6))
    qtbot.addWidget(dialog)
    result = dialog.built_section()
    assert result is not None and result.fiber is not None and result.elastic is None
    assert len(result.materials) == 3
    assert "Mander" in dialog._summary.text()
    assert dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


@pytest.mark.gui
def test_us_project_starts_with_us_bars_and_ksi(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = Project(meta=ProjectMeta(units=UnitSystem.US_IN_KIP), ndm=2, ndf=3)
    dialog = ConcreteSectionDialog(project)
    qtbot.addWidget(dialog)
    assert dialog._bar.currentText() == "#8"
    assert dialog._fc.value() == pytest.approx(4.0)
    assert dialog.spec().h == pytest.approx(24.0)


@pytest.mark.gui
def test_shapes_switch_their_inputs_and_bad_input_disables_ok(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ConcreteSectionDialog(Project(meta=ProjectMeta(), ndm=3, ndf=6))
    qtbot.addWidget(dialog)
    dialog._shape.setCurrentIndex(2)  # T-beam
    assert dialog.spec().shape == "tee"
    assert dialog._role.currentData() == "beam"
    dialog._make_elastic.setChecked(True)
    result = dialog.built_section()
    assert result is not None and result.elastic is not None
    assert "0.35 Ig" in result.elastic.name
    dialog._bf.setValue(0.1)  # narrower than the web
    assert dialog.built_section() is None
    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "flange" in dialog._message.text()


@pytest.mark.gui
def test_the_menu_adds_materials_and_sections_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(Project(meta=ProjectMeta(), ndm=3, ndf=6))

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self._make_elastic.setChecked(True)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ConcreteSectionDialog, "exec", _accept)
    mw._act_concrete_section.trigger()
    project = mw._vm.project
    assert len(project.materials) == 3
    assert len(project.sections) == 2
    assert "Concrete section: added 3 material(s)" in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert not project.materials and not project.sections


@pytest.mark.gui
def test_concrete_law_combo_builds_concrete_cm(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ConcreteSectionDialog(Project(meta=ProjectMeta(), ndm=2, ndf=3))
    qtbot.addWidget(dialog)
    dialog._model.setCurrentIndex(dialog._model.findData("ConcreteCM"))
    assert dialog.spec().concrete_model == "ConcreteCM"
    result = dialog.built_section()
    assert result is not None
    assert [m.type for m in result.materials] == ["ConcreteCM", "ConcreteCM", "Steel02"]
