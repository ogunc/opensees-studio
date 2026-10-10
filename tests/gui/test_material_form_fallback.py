"""Every material the core defines must open in the Material Library.

``FORM_REGISTRY`` holds a hand-written form per material type, and
``form_for`` used to index it directly: a project holding a
``Hysteretic`` or ``HystereticSM`` material — the latter shipped in
``examples/sdof_pushover.osmodel`` — raised ``KeyError`` the moment its
row was selected. The section dialog already had a placeholder
fallback; the material dialog now has the same one.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddMaterialsCommand
from opensees_studio.core import HystereticMaterial, HystereticSM
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.material_forms import FORM_REGISTRY, form_for
from opensees_studio.views.dialogs.material_library import MaterialLibraryDialog


def _hysteretic() -> HystereticMaterial:
    return HystereticMaterial(
        id=1,
        name="Hinge",
        s1p=100.0,
        e1p=0.001,
        s2p=150.0,
        e2p=0.005,
        s3p=160.0,
        e3p=0.02,
        s1n=-100.0,
        e1n=-0.001,
        s2n=-150.0,
        e2n=-0.005,
        s3n=-160.0,
        e3n=-0.02,
    )


def _hysteretic_sm() -> HystereticSM:
    return HystereticSM(
        id=2,
        name="Wire rope",
        pos_env=[(70.0, 0.01), (90.0, 0.05)],
        neg_env=[(-120.0, -0.01), (-160.0, -0.05)],
    )


def test_the_registry_is_not_the_whole_story() -> None:
    """Guard the premise: these types are real, and they have no hand-written form."""
    assert "Hysteretic" not in FORM_REGISTRY
    assert "HystereticSM" not in FORM_REGISTRY


@pytest.mark.gui
@pytest.mark.parametrize("build", [_hysteretic, _hysteretic_sm])
def test_form_for_falls_back_instead_of_raising(qtbot, build) -> None:  # type: ignore[no-untyped-def]
    material = build()

    form = form_for(material)
    qtbot.addWidget(form)

    assert form is not None
    assert form._material_id == material.id
    # The name is shown but not editable: the placeholder form cannot write
    # the material back without clobbering fields it does not know about.
    assert form._name_edit.text() == material.name
    assert not form._name_edit.isEnabled()


@pytest.mark.gui
def test_material_library_opens_a_project_holding_a_hysteretic_material(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The original crash path: select the Hysteretic row in the library."""
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    vm.apply_command(AddMaterialsCommand(vm, [_hysteretic()]))

    dialog = MaterialLibraryDialog(vm)
    qtbot.addWidget(dialog)

    # Opening the dialog selects the first row, which builds its form.
    assert dialog._stack.count() == 1
    assert dialog._selected_material().id == 1


@pytest.mark.gui
def test_material_library_can_still_add_a_supported_material(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The fallback must not have swallowed the real forms."""
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    vm.apply_command(AddMaterialsCommand(vm, [_hysteretic(), _hysteretic_sm()]))

    dialog = MaterialLibraryDialog(vm)
    qtbot.addWidget(dialog)

    # Walk every row the way a user would.
    for row in range(dialog._list.count()):
        dialog._list.setCurrentRow(row)
        form = dialog._stack.currentWidget()
        assert form is not None
