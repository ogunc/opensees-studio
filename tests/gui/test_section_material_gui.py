"""The elastic section form and the AISC picker make a section of a material."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import AddSectionsCommand
from opensees_studio.core import UnitSystem
from opensees_studio.core.aisc import load_shapes
from opensees_studio.core.materials import ElasticIsotropic
from opensees_studio.core.sections import ElasticSection
from opensees_studio.views.dialogs.aisc_library import AiscLibraryDialog
from opensees_studio.views.dialogs.section_forms import ElasticSectionForm
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow()
    qtbot.addWidget(win)
    win._vm.new_project(units=UnitSystem.US_IN_KIP, default_materials=True)
    return win


def _material(win: MainWindow, name: str) -> ElasticIsotropic:
    return next(m for m in win._vm.project.materials if m.name == name)


def test_a_new_elastic_section_is_a572_with_its_moduli_shown_not_edited(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    form = ElasticSectionForm(project=window._vm.project)
    qtbot.addWidget(form)
    steel = _material(window, "A572Gr50")

    assert form._material.currentData() == steel.id
    assert not form._e.isEnabled()
    assert not form._g.isEnabled()
    form._name_edit.setText("Beam")
    form._as2.setValue(1.5)
    section = form.read(1)
    assert section.material_id == steel.id
    assert pytest.approx(29_000.0) == section.E
    assert pytest.approx(29_000.0 / 2.6) == section.G
    assert (section.As2, section.As3) == (1.5, 0.0)


def test_without_a_material_the_moduli_are_typed_in(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    form = ElasticSectionForm(project=window._vm.project)
    qtbot.addWidget(form)
    form._material.setCurrentIndex(form._material.count() - 1)
    assert form._e.isEnabled()
    form._e.setValue(123.0)
    section = form.read(1)
    assert section.material_id is None
    assert section.E == 123.0
    assert (section.As2, section.As3) == (0.0, 0.0)  # given, rigid in shear


def test_the_aisc_picker_inserts_a572_with_the_profile_shear_areas(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    project = window._vm.project
    dlg = AiscLibraryDialog(
        units=project.meta.units, ndm=2, materials=list(project.materials), next_id=7
    )
    qtbot.addWidget(dlg)
    dlg._filter.setText("W14X30")
    section = dlg.result_section()
    w14 = load_shapes()["W14X30"]
    assert isinstance(section, ElasticSection)
    assert section.material_id == _material(window, "A572Gr50").id
    assert section.As2 == pytest.approx(w14.d * w14.tw)
    assert section.As3 == pytest.approx(5 / 3 * w14.bf * w14.tf)


def test_editing_the_material_updates_its_sections_with_undo(window) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.commands import UpdateMaterialCommand

    vm = window._vm
    steel = _material(window, "A36")
    form_section = ElasticSection(
        id=vm.project.next_section_id(), E=1.0, A=10.0, Iz=100.0, material_id=steel.id
    )
    vm.apply_command(AddSectionsCommand(vm, [form_section]))
    assert pytest.approx(29_000.0) == vm.project.sections[-1].E  # synced on the edit

    vm.apply_command(UpdateMaterialCommand(vm, steel.model_copy(update={"E": 30_000.0})))
    assert pytest.approx(30_000.0) == vm.project.sections[-1].E
    vm.undo_stack.undo()
    assert pytest.approx(29_000.0) == vm.project.sections[-1].E
