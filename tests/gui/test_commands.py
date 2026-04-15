"""Unit tests for ProjectCommand subclasses.

Verify that every command's ``redo`` is exactly reversed by ``undo``,
that the undo stack auto-tracks dirty state, and that cascade-delete
removes affected elements.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (  # noqa: E402
    AddElementsCommand,
    AddNodalLoadsCommand,
    AddNodesCommand,
    DeleteElementsCommand,
    DeleteNodesCommand,
    SetRestraintCommand,
)
from opensees_studio.core import (  # noqa: E402
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Steel01,
    TrussElement,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402


# ─────────────────────────── helpers ────────────────────────────────
def _vm() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    return vm


# ─────────────────────────── AddNodesCommand ────────────────────────
@pytest.mark.gui
def test_add_nodes_then_undo(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    new_nodes = [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))]
    vm.apply_command(AddNodesCommand(vm, new_nodes))
    assert len(vm.project.nodes) == 2
    vm.undo_stack.undo()
    assert len(vm.project.nodes) == 0
    vm.undo_stack.redo()
    assert len(vm.project.nodes) == 2


@pytest.mark.gui
def test_add_nodes_emits_modelMutated(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    with qtbot.waitSignal(vm.modelMutated, timeout=500):
        vm.apply_command(AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0))]))


@pytest.mark.gui
def test_add_nodes_marks_dirty(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    assert not vm.is_dirty
    vm.apply_command(AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0))]))
    assert vm.is_dirty


@pytest.mark.gui
def test_add_nodes_duplicate_id_raises(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [Node(id=5, coords=(0, 0, 0))]))
    with pytest.raises(ValueError, match="already exists"):
        vm.apply_command(AddNodesCommand(vm, [Node(id=5, coords=(1, 0, 0))]))


# ─────────────────────────── DeleteNodesCommand (cascade) ───────────
@pytest.mark.gui
def test_delete_node_cascades_to_elements(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(1, 0, 0)),
        Node(id=3, coords=(2, 0, 0)),
    ]))
    # Add a material so the element is valid.
    vm.project.materials.append(Steel01(id=1, Fy=420e6, E0=200e9, b=0.01))
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1),
        TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
    ]))
    # Delete node 2 → both elements should disappear.
    vm.apply_command(DeleteNodesCommand(vm, {2}))
    assert {n.id for n in vm.project.nodes} == {1, 3}
    assert vm.project.elements == []
    # Undo restores everything.
    vm.undo_stack.undo()
    assert {n.id for n in vm.project.nodes} == {1, 2, 3}
    assert {e.id for e in vm.project.elements} == {1, 2}


# ─────────────────────────── SetRestraintCommand ───────────────────
@pytest.mark.gui
def test_set_restraint_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(1, 0, 0)),
    ]))
    fix = (True, True, True, True, True, True)
    vm.apply_command(SetRestraintCommand(vm, {1, 2}, fix))
    assert vm.project.node(1).restraint == fix
    assert vm.project.node(2).restraint == fix
    vm.undo_stack.undo()
    assert vm.project.node(1).restraint == (False,) * 6
    assert vm.project.node(2).restraint == (False,) * 6


# ─────────────────────────── AddNodalLoadsCommand ──────────────────
@pytest.mark.gui
def test_add_load_creates_default_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0))]))
    forces = (100.0, 0, 0, 0, 0, 0)
    vm.apply_command(AddNodalLoadsCommand(vm, {1}, forces))
    assert len(vm.project.time_series) == 1
    assert isinstance(vm.project.time_series[0], LinearTimeSeries)
    assert len(vm.project.load_patterns) == 1
    pat = vm.project.load_patterns[0]
    assert isinstance(pat, PlainLoadPattern)
    assert len(pat.nodal_loads) == 1
    assert pat.nodal_loads[0] == NodalLoad(node_id=1, forces=forces)


@pytest.mark.gui
def test_add_load_undo_removes_default_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0))]))
    vm.apply_command(AddNodalLoadsCommand(vm, {1}, (100.0, 0, 0, 0, 0, 0)))
    vm.undo_stack.undo()
    # Both the load AND the auto-created pattern + ts should be gone.
    assert vm.project.time_series == []
    assert vm.project.load_patterns == []


@pytest.mark.gui
def test_add_load_uses_existing_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0))]))
    # Pre-populate a pattern.
    vm.project.time_series.append(LinearTimeSeries(id=1))
    vm.project.load_patterns.append(PlainLoadPattern(id=1, time_series_id=1))
    vm.apply_command(AddNodalLoadsCommand(vm, {1}, (50.0, 0, 0, 0, 0, 0)))
    # No new pattern should be created.
    assert len(vm.project.time_series) == 1
    assert len(vm.project.load_patterns) == 1
    assert len(vm.project.load_patterns[0].nodal_loads) == 1


# ─────────────────────────── stack semantics ───────────────────────
@pytest.mark.gui
def test_save_marks_clean(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    vm.apply_command(AddNodesCommand(vm, [Node(id=1, coords=(0, 0, 0))]))
    assert vm.is_dirty
    vm.save(tmp_path / "x.osmodel")
    assert not vm.is_dirty
