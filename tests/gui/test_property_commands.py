"""Unit tests for property assignment and material/section update commands."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (  # noqa: E402
    AddElementsCommand,
    AddMaterialsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    AssignMaterialCommand,
    AssignSectionCommand,
    UpdateMaterialCommand,
    UpdateSectionCommand,
)
from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Steel01,
    Steel02,
    TrussElement,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402


def _vm_with_steel() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(1, 0, 0)),
        Node(id=3, coords=(2, 0, 0)),
    ]))
    vm.apply_command(AddMaterialsCommand(vm, [
        Steel01(id=1, name="S420", Fy=420e6, E0=200e9, b=0.01),
    ]))
    vm.apply_command(AddSectionsCommand(vm, [
        ElasticSection(id=1, name="Default", E=200e9, A=0.01,
                       Iz=8.33e-6, Iy=8.33e-6, G=80e9, J=1e-6),
    ]))
    return vm


# ──────────────────────── UpdateMaterialCommand ────────────────────────
@pytest.mark.gui
def test_update_material_changes_parameters(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    new = Steel01(id=1, name="S420 (revised)", Fy=500e6, E0=210e9, b=0.02)
    vm.apply_command(UpdateMaterialCommand(vm, new))
    m = vm.project.material(1)
    assert m.Fy == 500e6
    assert m.b == 0.02
    assert m.name == "S420 (revised)"


@pytest.mark.gui
def test_update_material_undo_restores_original(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    new = Steel01(id=1, Fy=500e6, E0=200e9, b=0.02)
    vm.apply_command(UpdateMaterialCommand(vm, new))
    vm.undo_stack.undo()
    m = vm.project.material(1)
    assert m.Fy == 420e6
    assert m.b == 0.01


@pytest.mark.gui
def test_update_material_can_change_type(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    # Same id, different concrete class — discriminator-driven swap.
    swapped = Steel02(id=1, name="Switched", Fy=355e6, E0=210e9, b=0.005)
    vm.apply_command(UpdateMaterialCommand(vm, swapped))
    assert isinstance(vm.project.material(1), Steel02)
    vm.undo_stack.undo()
    assert isinstance(vm.project.material(1), Steel01)


@pytest.mark.gui
def test_update_unknown_id_raises(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    bogus = Steel01(id=99, Fy=420e6, E0=200e9, b=0.01)
    with pytest.raises(KeyError):
        vm.apply_command(UpdateMaterialCommand(vm, bogus))


# ──────────────────────── UpdateSectionCommand ────────────────────────
@pytest.mark.gui
def test_update_section_changes_inertia(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    new = ElasticSection(id=1, name="Updated", E=200e9, A=0.02,
                         Iz=2e-5, Iy=2e-5, G=80e9, J=2e-6)
    vm.apply_command(UpdateSectionCommand(vm, new))
    s = vm.project.section(1)
    assert s.A == 0.02
    assert s.Iz == 2e-5
    vm.undo_stack.undo()
    assert vm.project.section(1).A == 0.01


# ──────────────────────── AssignSectionCommand ────────────────────────
@pytest.mark.gui
def test_assign_section_to_frames(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    # Add a second section and two frames.
    vm.apply_command(AddSectionsCommand(vm, [
        ElasticSection(id=2, name="Big", E=200e9, A=0.05,
                       Iz=4e-5, Iy=4e-5, G=80e9, J=2e-6),
    ]))
    vm.apply_command(AddElementsCommand(vm, [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
    ]))
    vm.apply_command(AssignSectionCommand(vm, {1, 2}, section_id=2))
    assert vm.project.element(1).section_id == 2
    assert vm.project.element(2).section_id == 2
    vm.undo_stack.undo()
    assert vm.project.element(1).section_id == 1
    assert vm.project.element(2).section_id == 1


@pytest.mark.gui
def test_assign_section_skips_truss_elements(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Truss has no section_id — command should silently skip it."""
    vm = _vm_with_steel()
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1),
        ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
    ]))
    vm.apply_command(AssignSectionCommand(vm, {1, 2}, section_id=1))
    # Frame ok, truss unchanged (still material-based).
    assert vm.project.element(2).section_id == 1
    assert isinstance(vm.project.element(1), TrussElement)


# ──────────────────────── AssignMaterialCommand ────────────────────────
@pytest.mark.gui
def test_assign_material_to_truss(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    vm.apply_command(AddMaterialsCommand(vm, [
        Steel02(id=2, name="S355", Fy=355e6, E0=210e9, b=0.005),
    ]))
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1),
        TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
    ]))
    vm.apply_command(AssignMaterialCommand(vm, {1, 2}, material_id=2))
    assert vm.project.element(1).material_id == 2
    assert vm.project.element(2).material_id == 2
    vm.undo_stack.undo()
    assert vm.project.element(1).material_id == 1


@pytest.mark.gui
def test_assign_material_skips_frame_elements(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_steel()
    vm.apply_command(AddElementsCommand(vm, [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
    ]))
    vm.apply_command(AssignMaterialCommand(vm, {1, 2}, material_id=1))
    # Frame doesn't have material_id; only the truss is affected.
    assert vm.project.element(2).material_id == 1
    assert isinstance(vm.project.element(1), ElasticBeamColumn)
