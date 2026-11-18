"""Rename the analysis cases the user names in the Case Manager.

The dialog already had a Name field in the form; this covers the faster paths:
renaming from the case list and keeping results valid when only the label moved.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import AddAnalysisCasesCommand, RenameAnalysisCaseCommand
from opensees_studio.core import ModalCase, Project, StaticCase
from opensees_studio.core.combinations import model_fingerprint
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.case_manager import AnalysisCaseManagerDialog


def _vm_with_case(name: str = "Gravity") -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(AddAnalysisCasesCommand(vm, [ModalCase(id=1, name=name, n_modes=3)]))
    return vm


@pytest.mark.gui
def test_renaming_a_case_from_the_list(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_case("Gravity")
    dialog = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dialog)
    dialog._list.setCurrentRow(0)

    dialog._list.item(0).setText("#1  Wind  [Modal]")

    assert vm.project.analyses[0].name == "Wind"
    assert "Wind" in dialog._list.item(0).text()
    vm.undo_stack.undo()
    assert vm.project.analyses[0].name == "Gravity"


@pytest.mark.gui
def test_an_empty_name_keeps_the_old_one(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_case("Gravity")
    dialog = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dialog)
    dialog._list.setCurrentRow(0)

    dialog._list.item(0).setText("#1    [Modal]")

    assert vm.project.analyses[0].name == "Gravity"


@pytest.mark.gui
def test_renaming_keeps_the_case_type_and_settings(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_case("Gravity")
    dialog = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dialog)
    dialog._list.setCurrentRow(0)

    dialog._list.item(0).setText("#1  Modes  [Modal]")

    case = vm.project.analyses[0]
    assert isinstance(case, ModalCase)
    assert case.n_modes == 3
    assert case.id == 1


@pytest.mark.gui
def test_the_name_field_in_the_form_renames_too(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_case("Gravity")
    dialog = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dialog)
    dialog._list.setCurrentRow(0)

    form = dialog._stack.currentWidget()
    form._name_edit.setText("Modes")
    dialog._on_apply()

    assert vm.project.analyses[0].name == "Modes"
    assert isinstance(vm.project.analyses[0], ModalCase)


@pytest.mark.gui
def test_renaming_a_case_with_a_reference_warning(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The row may carry "[Invalid references]": it is not part of the name."""
    vm = ProjectViewModel()
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddAnalysisCasesCommand(vm, [StaticCase(id=1, name="Gravity", pattern_ids=[99])])
    )
    dialog = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dialog)
    dialog._list.setCurrentRow(0)
    assert "Invalid references" in dialog._list.item(0).text()

    dialog._list.item(0).setText("#1  Lateral  [Static] [Invalid references]")

    assert vm.project.analyses[0].name == "Lateral"


def test_renaming_does_not_invalidate_results() -> None:
    """A label is not a model input: the fingerprint must not change."""
    project = Project()
    project.analyses = [ModalCase(id=1, name="Gravity", n_modes=3)]
    before = model_fingerprint(project)
    project.analyses[0] = project.analyses[0].model_copy(update={"name": "Wind"})
    assert model_fingerprint(project) == before


def test_the_rename_command_leaves_the_other_cases_alone() -> None:
    vm = ProjectViewModel()
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddAnalysisCasesCommand(
            vm,
            [
                ModalCase(id=1, name="Gravity", n_modes=3),
                StaticCase(id=2, name="Lateral", pattern_ids=[1]),
            ],
        )
    )
    vm.apply_command(RenameAnalysisCaseCommand(vm, 2, "Wind"))
    assert [c.name for c in vm.project.analyses] == ["Gravity", "Wind"]
    vm.undo_stack.undo()
    assert [c.name for c in vm.project.analyses] == ["Gravity", "Lateral"]
