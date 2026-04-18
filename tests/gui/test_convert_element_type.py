"""Tests for ConvertElementTypeCommand — swap element class by id."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (  # noqa: E402
    AddElementsCommand,
    AddMaterialsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    ConvertElementTypeCommand,
)
from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    Node,
    TrussElement,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402


def _vm_setup() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(3, 0, 0)),
    ]))
    vm.apply_command(AddMaterialsCommand(vm, [
        ElasticUniaxial(id=1, name="Steel", E=200e9),
    ]))
    vm.apply_command(AddSectionsCommand(vm, [
        ElasticSection(
            id=1, name="Default", E=200e9, A=0.01,
            Iz=8.33e-6, Iy=8.33e-6, G=80e9, J=1e-6,
        ),
    ]))
    return vm


@pytest.mark.gui
def test_frame_to_truss_conversion(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_setup()
    vm.apply_command(AddElementsCommand(vm, [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
    ]))
    vm.apply_command(ConvertElementTypeCommand(
        vm, {1}, "Truss",
        defaults={"material_id": 1, "area": 0.001},
    ))
    el = vm.project.element(1)
    assert isinstance(el, TrussElement)
    assert el.nodes == (1, 2)
    assert el.material_id == 1
    assert el.area == pytest.approx(0.001)


@pytest.mark.gui
def test_truss_to_frame_conversion(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_setup()
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=0.001, material_id=1),
    ]))
    vm.apply_command(ConvertElementTypeCommand(
        vm, {1}, "ElasticBeamColumn",
        defaults={"section_id": 1},
    ))
    el = vm.project.element(1)
    assert isinstance(el, ElasticBeamColumn)
    assert el.nodes == (1, 2)
    assert el.section_id == 1


@pytest.mark.gui
def test_convert_preserves_id_and_is_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_setup()
    vm.apply_command(AddElementsCommand(vm, [
        ElasticBeamColumn(id=42, name="A", nodes=(1, 2), section_id=1),
    ]))
    vm.apply_command(ConvertElementTypeCommand(
        vm, {42}, "Truss", defaults={"material_id": 1, "area": 0.002},
    ))
    assert isinstance(vm.project.element(42), TrussElement)
    assert vm.project.element(42).name == "A"
    vm.undo_stack.undo()
    assert isinstance(vm.project.element(42), ElasticBeamColumn)


@pytest.mark.gui
def test_convert_same_type_is_noop(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_setup()
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=0.001, material_id=1),
    ]))
    before = vm.project.element(1)
    vm.apply_command(ConvertElementTypeCommand(
        vm, {1}, "Truss", defaults={"material_id": 1, "area": 0.002},
    ))
    # Class is still Truss and the element object is unchanged.
    assert vm.project.element(1) is before


@pytest.mark.gui
def test_unknown_target_type_raises(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_setup()
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=0.001, material_id=1),
    ]))
    with pytest.raises(ValueError):
        vm.apply_command(ConvertElementTypeCommand(
            vm, {1}, "NotAType", defaults={},
        ))
