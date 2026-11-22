"""Section Library → Add Cold-Formed (AISI): pick a size, or type one, and insert it."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import UnitSystem
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.sections.cold_formed import ColdFormedShape, properties
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.cold_formed import ColdFormedDialog
from opensees_studio.views.dialogs.section_library import SectionLibraryDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def vm() -> ProjectViewModel:
    model = ProjectViewModel()
    model.new_project(2, 3, units=UnitSystem.US_IN_KIP, default_materials=True)
    return model


def test_every_profile_has_sizes_and_a_drawing(vm: ProjectViewModel, qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = ColdFormedDialog(vm.project, next_id=1)
    qtbot.addWidget(dlg)
    for code in ("CS", "CU", "ZS", "HU", "LU"):
        dlg.set_profile(code)
        assert dlg._list.count() > 0
        assert dlg._view._points  # drawn
        section = dlg.result_section()
        assert isinstance(section, ElasticSection)
        assert isinstance(section.shape, ColdFormedShape)
        assert section.shape.profile == code


def test_a_size_is_inserted_as_a653_with_its_name(vm: ProjectViewModel, qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = ColdFormedDialog(vm.project, next_id=1)
    qtbot.addWidget(dlg)
    dlg.set_profile("ZS")
    dlg.select_size("8ZS2.5x070")

    section = dlg.result_section()

    a653 = next(m for m in vm.project.materials if m.name == "A653SSGr50")
    assert section.name == "8ZS2.5x070"
    assert section.material_id == a653.id
    assert pytest.approx(29_500.0) == section.E
    assert pytest.approx(properties(section.shape).A) == section.A  # type: ignore[arg-type]


def test_edited_dimensions_name_the_section_by_them(vm: ProjectViewModel, qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = ColdFormedDialog(vm.project, next_id=1)
    qtbot.addWidget(dlg)
    dlg.set_profile("CS")
    dlg.select_size("8CS2.5x070")
    dlg._fields["t"].setValue(0.08)

    section = dlg.result_section()

    assert section.name == "CS 8x2.5x0.08"
    assert section.shape.t == pytest.approx(0.08)  # type: ignore[union-attr]


def test_impossible_dimensions_are_shown_not_inserted(vm: ProjectViewModel, qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = ColdFormedDialog(vm.project, next_id=1)
    qtbot.addWidget(dlg)
    dlg.set_profile("CS")
    dlg._fields["lip"].setValue(0.01)
    assert "lip" in dlg._props.text()
    with pytest.raises(ValueError):
        dlg.result_section()


def test_the_section_library_button_inserts_it_in_one_undo(  # type: ignore[no-untyped-def]
    vm: ProjectViewModel, qtbot, monkeypatch
) -> None:
    monkeypatch.setattr(ColdFormedDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    library = SectionLibraryDialog(vm)
    qtbot.addWidget(library)

    library._add_cold_formed_btn.click()

    assert len(vm.project.sections) == 1
    assert isinstance(vm.project.sections[0].shape, ColdFormedShape)
    vm.undo_stack.undo()
    assert vm.project.sections == []


@pytest.mark.parametrize(("assembly", "suffix"), [("box", "box"), ("back_to_back", "BtB")])
def test_two_channels_are_offered_as_a_box_and_back_to_back(  # type: ignore[no-untyped-def]
    vm: ProjectViewModel, qtbot, assembly: str, suffix: str
) -> None:
    dlg = ColdFormedDialog(vm.project, next_id=1)
    qtbot.addWidget(dlg)
    dlg.set_profile("CS", assembly)
    dlg.select_size(f"2-8CS2.5x070 {suffix}")
    assert len(dlg._view._sheets) == 2  # both channels drawn

    section = dlg.result_section()

    single = ColdFormedShape(profile="CS", d=8, bf=2.5, t=0.07, r=0.1875, lip=0.75)
    assert section.name == f"2-8CS2.5x070 {suffix}"
    assert section.shape.assembly == assembly  # type: ignore[union-attr]
    assert pytest.approx(2 * properties(single).A, rel=1e-6) == section.A
    assert section.shape.single.designation == "8CS2.5x070"  # type: ignore[union-attr]
