"""Define → Steel Deck Slab Wizard: presets in the project's units, one undo step."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QDialogButtonBox

from opensees_studio.core import LayeredShellSection, Project, ProjectMeta
from opensees_studio.core.default_materials import default_materials
from opensees_studio.core.units import UnitSystem
from opensees_studio.views.dialogs.steel_deck import SteelDeckDialog


def _project(units: UnitSystem = UnitSystem.SI_M_N) -> Project:
    project = Project(meta=ProjectMeta(units=units), ndm=3, ndf=6)
    project.materials.extend(default_materials(1, units))
    return project


@pytest.mark.gui
def test_defaults_build_an_orthotropic_deck_of_4000_psi(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SteelDeckDialog(_project())
    qtbot.addWidget(dialog)
    assert dialog._concrete.currentData().name == "4000Psi"
    assert dialog._steel.currentData().name == "A653SSGr33"
    result = dialog.built_deck()
    assert result is not None
    assert isinstance(result.section, LayeredShellSection)
    assert result.properties.stiffness_ratio > 2.0
    assert "Along the ribs" in dialog._summary.text()
    assert dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


@pytest.mark.gui
def test_presets_and_gauges_follow_the_project_units(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SteelDeckDialog(_project(UnitSystem.SI_MM_N))
    qtbot.addWidget(dialog)
    dialog._profile.setCurrentIndex(1)  # 2 in, 12 in pitch
    assert dialog._hr.value() == pytest.approx(50.8)
    assert dialog._pitch.value() == pytest.approx(304.8)
    assert dialog._t.value() == pytest.approx(0.91)
    assert dialog._topping.value() == pytest.approx(65.0)
    dialog._hr.setValue(60.0)
    assert dialog._profile.currentText() == "Custom"


@pytest.mark.gui
def test_a_project_without_materials_still_gets_the_default_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SteelDeckDialog(Project(meta=ProjectMeta(), ndm=3, ndf=6))
    qtbot.addWidget(dialog)
    assert "default values" in dialog._concrete.currentText()
    assert dialog.built_deck() is not None


@pytest.mark.gui
def test_bad_geometry_disables_ok(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SteelDeckDialog(_project())
    qtbot.addWidget(dialog)
    dialog._wt.setValue(1.0)  # wider than the pitch
    assert dialog.built_deck() is None
    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "rib widths" in dialog._message.text()


@pytest.mark.gui
def test_the_menu_adds_materials_and_the_section_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_project())
    before = len(mw._vm.project.materials)
    monkeypatch.setattr(SteelDeckDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    mw._act_steel_deck.trigger()
    project = mw._vm.project
    assert len(project.materials) == before + 4
    assert isinstance(project.sections[-1], LayeredShellSection)
    assert "Steel deck slab: added 4 material(s)" in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert len(project.materials) == before and not project.sections


@pytest.mark.gui
def test_a_new_3d_project_has_the_default_slab(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import DEFAULT_SLAB_NAME
    from opensees_studio.viewmodels.project_vm import ProjectViewModel

    vm = ProjectViewModel()
    vm.new_project(3, 6, default_materials=True)
    assert [s.name for s in vm.project.sections] == [DEFAULT_SLAB_NAME]
    vm.new_project(2, 3, default_materials=True)
    assert vm.project.sections == []
