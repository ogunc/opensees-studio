"""The typical-material picker, and the Material Library button that opens it."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import UnitSystem
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.material_catalog import load_materials, materials_of
from opensees_studio.views.dialogs.material_library import MaterialLibraryDialog
from opensees_studio.views.dialogs.typical_materials import TypicalMaterialsDialog


def _picker(qtbot, units: UnitSystem = UnitSystem.SI_M_N, next_id: int = 1):  # type: ignore[no-untyped-def]
    dialog = TypicalMaterialsDialog(units=units, next_id=next_id)
    qtbot.addWidget(dialog)
    return dialog


def _row_of(dialog: TypicalMaterialsDialog, key: str) -> int:
    for row, entry in enumerate(dialog._entries):
        if entry.key == key:
            return row
    raise AssertionError(f"{key} is not in the list")


@pytest.mark.gui
def test_the_picker_lists_the_whole_library(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _picker(qtbot)
    assert dialog._list.rowCount() == len(load_materials()) == 23
    families = {dialog._family.itemData(i) for i in range(dialog._family.count())}
    assert families >= {"", "concrete", "rebar", "structural_steel", "masonry"}
    assert dialog.property(TOPIC_PROPERTY) == "define.material_library"


@pytest.mark.gui
def test_the_family_filter_and_the_search_narrow_the_list(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _picker(qtbot)
    index = dialog._family.findData("masonry")
    dialog._family.setCurrentIndex(index)
    assert dialog._list.rowCount() == len(materials_of("masonry")) == 5
    assert all(entry.family == "masonry" for entry in dialog._entries)

    dialog._family.setCurrentIndex(0)  # back to all
    dialog._query.setText("A992")
    assert [entry.key for entry in dialog._entries] == ["steel_a992"]

    dialog._query.setText("zzz")
    assert dialog._list.rowCount() == 0
    assert not dialog._insert.isEnabled()


@pytest.mark.gui
def test_the_preview_shows_the_published_value_beside_the_converted_one(qtbot) -> None:  # type: ignore[no-untyped-def]
    """420 MPa of rebar is 60.9 ksi in a kip-in project, and says so."""
    dialog = _picker(qtbot, units=UnitSystem.US_IN_KIP, next_id=4)
    dialog._list.setCurrentCell(_row_of(dialog, "rebar_grade_420"), 0)
    rows = {
        dialog._preview.item(row, 0).text(): (
            dialog._preview.item(row, 1).text(),
            dialog._preview.item(row, 2).text(),
        )
        for row in range(dialog._preview.rowCount())
    }
    assert rows["Fy"][0] == "420 MPa"
    assert rows["Fy"][1].endswith("ksi")
    assert float(rows["Fy"][1].split()[0]) == pytest.approx(60.92, abs=0.05)
    assert "ACI 318" in dialog._standard.text()


@pytest.mark.gui
def test_the_preview_flags_the_sign_convention_for_concrete(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _picker(qtbot)
    dialog._list.setCurrentCell(_row_of(dialog, "concrete_4000_unconfined"), 0)
    assert "minus sign" in dialog._notes.text()
    fpc = next(
        dialog._preview.item(row, 2).text()
        for row in range(dialog._preview.rowCount())
        if dialog._preview.item(row, 0).text() == "f'c"
    )
    assert fpc.startswith("-")


@pytest.mark.gui
def test_insert_builds_a_project_material_in_the_project_units(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _picker(qtbot, units=UnitSystem.US_IN_KIP, next_id=9)
    assert dialog.result_material() is None  # nothing chosen yet

    dialog._list.setCurrentCell(_row_of(dialog, "concrete_4000_unconfined"), 0)
    dialog._insert.click()

    material = dialog.result_material()
    assert material is not None
    assert material.id == 9
    assert material.type == "Concrete01"
    assert material.fpc == pytest.approx(-4.0, rel=1e-4)  # 4000 psi, in kip-in units
    assert material.epsc0 == -0.002


@pytest.mark.gui
def test_the_material_library_inserts_from_the_picker_in_one_undoable_step(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs import typical_materials as module

    library = MaterialLibraryDialog(_library_vm(qtbot))
    qtbot.addWidget(library)

    material = load_materials()["masonry_clay_1500"]
    from opensees_studio.core.material_catalog import to_material

    chosen = to_material(material, library._vm.project.next_material_id(), UnitSystem.SI_M_N)

    class _AutoPicker:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def result_material(self):  # type: ignore[no-untyped-def]
            return chosen

    monkeypatch.setattr(module, "TypicalMaterialsDialog", _AutoPicker)

    before = len(library._vm.project.materials)
    library._on_add_from_library()

    assert len(library._vm.project.materials) == before + 1
    assert library._vm.project.materials[-1].id == chosen.id
    assert library._vm.project.materials[-1].type == "ElasticIsotropic"

    library._vm.undo_stack.undo()
    assert len(library._vm.project.materials) == before


def _library_vm(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.viewmodels import ProjectViewModel

    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    return vm
