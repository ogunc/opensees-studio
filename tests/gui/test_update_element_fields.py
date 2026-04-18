"""Tests for UpdateElementFieldsCommand — inline scalar edits."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (  # noqa: E402
    AddElementsCommand,
    AddMaterialsCommand,
    AddNodesCommand,
    UpdateElementFieldsCommand,
)
from opensees_studio.core import (  # noqa: E402
    ElasticUniaxial,
    Node,
    TrussElement,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402


def _vm_with_truss() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(3, 0, 0)),
    ]))
    vm.apply_command(AddMaterialsCommand(vm, [
        ElasticUniaxial(id=1, name="Steel", E=200e9),
    ]))
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=0.001, material_id=1),
    ]))
    return vm


@pytest.mark.gui
def test_update_area_on_truss_element(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_truss()
    vm.apply_command(UpdateElementFieldsCommand(vm, 1, {"area": 0.00645}))
    assert vm.project.element(1).area == pytest.approx(0.00645)


@pytest.mark.gui
def test_update_area_is_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_truss()
    vm.apply_command(UpdateElementFieldsCommand(vm, 1, {"area": 0.005}))
    vm.undo_stack.undo()
    assert vm.project.element(1).area == pytest.approx(0.001)
    vm.undo_stack.redo()
    assert vm.project.element(1).area == pytest.approx(0.005)


@pytest.mark.gui
def test_unknown_field_is_silently_ignored(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Fields not in the element's model are filtered out — no exception."""
    vm = _vm_with_truss()
    vm.apply_command(UpdateElementFieldsCommand(
        vm, 1, {"section_id": 42},     # TrussElement has no section_id
    ))
    # The element is unchanged.
    assert vm.project.element(1).area == pytest.approx(0.001)
    assert vm.project.element(1).material_id == 1


@pytest.mark.gui
def test_update_multiple_fields_at_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_truss()
    vm.apply_command(UpdateElementFieldsCommand(
        vm, 1, {"area": 0.003, "rho": 7850.0},
    ))
    el = vm.project.element(1)
    assert el.area == pytest.approx(0.003)
    assert el.rho == pytest.approx(7850.0)
