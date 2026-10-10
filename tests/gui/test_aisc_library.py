"""Section Library → Add from AISC…: pick a shape, get a section in the model."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import ElasticSection, FiberSection, Steel01
from opensees_studio.core.units import UnitSystem
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.aisc_library import AiscLibraryDialog
from opensees_studio.views.dialogs.section_library import SectionLibraryDialog


def _vm(units: UnitSystem = UnitSystem.SI_M_N, *, material: bool = True) -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    vm.project.meta = vm.project.meta.model_copy(update={"units": units})
    if material:
        vm.project.materials.append(Steel01(id=1, name="A992", Fy=345e6, E0=200e9, b=0.01))
    return vm


@pytest.fixture
def dialog(qtbot):  # type: ignore[no-untyped-def]
    def _make(vm: ProjectViewModel) -> AiscLibraryDialog:
        dlg = AiscLibraryDialog(
            units=vm.project.meta.units,
            materials=list(vm.project.materials),
            next_id=1,
        )
        qtbot.addWidget(dlg)
        return dlg

    return _make


# ─────────────────────── picking ───────────────────────
@pytest.mark.gui
def test_it_opens_on_the_first_family_with_shapes_listed(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm())

    assert dlg._table.rowCount() > 100  # W is the first family
    assert dlg.selected_shape() is not None


@pytest.mark.gui
def test_the_filter_narrows_the_table(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm())

    dlg._filter.setText("W14X9")
    names = {dlg._table.item(r, 0).text() for r in range(dlg._table.rowCount())}

    assert "W14X90" in names
    assert len(names) < 20


@pytest.mark.gui
def test_an_empty_filter_result_is_not_an_error(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm())

    dlg._filter.setText("NOT-A-SHAPE")

    assert dlg._table.rowCount() == 0
    assert dlg.selected_shape() is None
    with pytest.raises(ValueError, match="No shape selected"):
        dlg.result_section()


# ─────────────────────── the two routes ───────────────────────
@pytest.mark.gui
def test_the_elastic_route_converts_to_the_project_units(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm(UnitSystem.SI_M_N))
    dlg._filter.setText("W14X90")
    dlg._table.selectRow(0)

    section = dlg.result_section()

    assert isinstance(section, ElasticSection)
    assert section.name == "W14X90"
    assert pytest.approx(26.5 * 0.0254**2, rel=1e-9) == section.A
    assert section.Iz == pytest.approx(999.0 * 0.0254**4, rel=1e-9)
    assert pytest.approx(200e9) == section.E


@pytest.mark.gui
def test_in_us_units_the_published_values_are_inserted_unchanged(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm(UnitSystem.US_IN_KIP))
    dlg._filter.setText("W14X90")
    dlg._table.selectRow(0)

    section = dlg.result_section()

    assert isinstance(section, ElasticSection)
    assert section.A == 26.5
    assert section.Iz == 999.0
    assert pytest.approx(29000.0) == section.E


@pytest.mark.gui
def test_the_fibre_route_builds_the_real_profile(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm())
    dlg._filter.setText("W14X90")
    dlg._table.selectRow(0)
    dlg._fiber_radio.setChecked(True)

    section = dlg.result_section()

    assert isinstance(section, FiberSection)
    assert len(section.patches) == 3
    assert section.patches[0].material_id == 1


@pytest.mark.gui
def test_the_fibre_route_is_off_without_a_material(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm(material=False))

    assert not dlg._fiber_radio.isEnabled()


@pytest.mark.gui
def test_the_fibre_route_refuses_a_family_without_flange_geometry(qtbot, dialog) -> None:  # type: ignore[no-untyped-def]
    dlg = dialog(_vm())
    index = next(i for i in range(dlg._family.count()) if dlg._family.itemData(i) == "PIPE")
    dlg._family.setCurrentIndex(index)
    dlg._fiber_radio.setChecked(True)

    with pytest.raises(ValueError, match="flange-and-web"):
        dlg.result_section()


# ─────────────────────── through the library dialog ───────────────────────
@pytest.mark.gui
def test_the_section_library_adds_the_picked_shape_to_the_project(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    library = SectionLibraryDialog(vm)
    qtbot.addWidget(library)
    before = len(vm.project.sections)

    # Drive the picker the way the button does, but without a second event loop.
    def _fake_exec(self) -> int:  # type: ignore[no-untyped-def]
        self._filter.setText("W24X76")
        self._table.selectRow(0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AiscLibraryDialog, "exec", _fake_exec)
    library._on_add_aisc()

    assert len(vm.project.sections) == before + 1
    added = vm.project.sections[-1]
    assert isinstance(added, ElasticSection)
    assert added.name == "W24X76"
    assert added.Iz == pytest.approx(2100.0 * 0.0254**4, rel=1e-9)
