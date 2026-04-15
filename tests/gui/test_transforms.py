"""Unit tests for geometric transform commands."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (  # noqa: E402
    AddElementsCommand,
    AddNodesCommand,
    MirrorCommand,
    MoveNodesCommand,
    ReplicateCommand,
)
from opensees_studio.core import Node, Steel01, TrussElement  # noqa: E402
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402


def _populated_vm() -> ProjectViewModel:
    """A small VM with 4 corner nodes + 4 truss elements forming a square."""
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
        Node(id=2, coords=(1, 0, 0)),
        Node(id=3, coords=(1, 1, 0)),
        Node(id=4, coords=(0, 1, 0)),
    ]))
    vm.project.materials.append(Steel01(id=1, Fy=420e6, E0=200e9, b=0.01))
    vm.apply_command(AddElementsCommand(vm, [
        TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1),
        TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
        TrussElement(id=3, nodes=(3, 4), area=1e-3, material_id=1),
        TrussElement(id=4, nodes=(4, 1), area=1e-3, material_id=1),
    ]))
    return vm


# ──────────────────────────── Move ────────────────────────────
@pytest.mark.gui
def test_move_translates_in_place(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    vm.apply_command(MoveNodesCommand(vm, {1, 2, 3, 4}, (10.0, 0.0, 0.0)))
    assert vm.project.node(1).coords == (10.0, 0.0, 0.0)
    assert vm.project.node(2).coords == (11.0, 0.0, 0.0)
    assert len(vm.project.nodes) == 4   # no copies created


@pytest.mark.gui
def test_move_undo_restores_original_coords(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    vm.apply_command(MoveNodesCommand(vm, {1}, (5.0, 0.0, 0.0)))
    assert vm.project.node(1).coords == (5.0, 0.0, 0.0)
    vm.undo_stack.undo()
    assert vm.project.node(1).coords == (0.0, 0.0, 0.0)


@pytest.mark.gui
def test_move_preserves_restraint(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    fix6 = (True,) * 6
    vm.apply_command(MoveNodesCommand(vm, {1}, (5.0, 0.0, 0.0)))
    assert vm.project.node(1).restraint == fix6


# ──────────────────────────── Replicate ────────────────────────────
@pytest.mark.gui
def test_replicate_creates_n_copies(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    vm.apply_command(ReplicateCommand(vm, {1, 2, 3, 4}, {1, 2, 3, 4},
                                      offset=(0, 0, 3.0), n_copies=2))
    # Original 4 + 2*4 copies = 12 nodes; original 4 + 2*4 elements = 12 elements
    assert len(vm.project.nodes) == 12
    assert len(vm.project.elements) == 12
    # Replica 1 sits at z=3, replica 2 at z=6.
    z_values = sorted({n.coords[2] for n in vm.project.nodes})
    assert z_values == [0.0, 3.0, 6.0]


@pytest.mark.gui
def test_replicate_undo_removes_only_copies(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    vm.apply_command(ReplicateCommand(vm, {1, 2, 3, 4}, {1, 2, 3, 4},
                                      offset=(0, 0, 3.0), n_copies=2))
    vm.undo_stack.undo()
    assert len(vm.project.nodes) == 4
    assert len(vm.project.elements) == 4
    # Original ids preserved.
    assert {n.id for n in vm.project.nodes} == {1, 2, 3, 4}


@pytest.mark.gui
def test_replicate_skips_elements_with_unselected_endpoints(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    # Select only node 1 and 2; elements 1 (1↔2) is fully covered, others aren't.
    vm.apply_command(ReplicateCommand(vm, {1, 2}, {1, 2, 3, 4},
                                      offset=(0, 0, 3.0), n_copies=1))
    # 2 new nodes + 1 new element (only element 1 was fully bracketed).
    assert len(vm.project.nodes) == 6
    assert len(vm.project.elements) == 5


@pytest.mark.gui
def test_replicate_zero_copies_rejected(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    with pytest.raises(ValueError):
        ReplicateCommand(vm, {1}, set(), offset=(0, 0, 1), n_copies=0)


# ──────────────────────────── Mirror ────────────────────────────
@pytest.mark.gui
def test_mirror_yz_flips_x(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    vm.apply_command(MirrorCommand(vm, {1, 2, 3, 4}, {1, 2, 3, 4}, plane="YZ"))
    assert len(vm.project.nodes) == 8
    assert len(vm.project.elements) == 8
    # The mirrored copies should have negative x for original-non-zero x.
    new_node_ids = {n.id for n in vm.project.nodes} - {1, 2, 3, 4}
    new_xs = {vm.project.node(nid).coords[0] for nid in new_node_ids}
    assert -1.0 in new_xs


@pytest.mark.gui
def test_mirror_xy_flips_z(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    # Move the square up first so z=2 (mirroring across z=0 gives -2).
    vm.apply_command(MoveNodesCommand(vm, {1, 2, 3, 4}, (0, 0, 2.0)))
    vm.apply_command(MirrorCommand(vm, {1, 2, 3, 4}, {1, 2, 3, 4}, plane="XY"))
    new_node_ids = {n.id for n in vm.project.nodes} - {1, 2, 3, 4}
    new_zs = {vm.project.node(nid).coords[2] for nid in new_node_ids}
    assert new_zs == {-2.0}


@pytest.mark.gui
def test_mirror_undo_removes_copies(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _populated_vm()
    vm.apply_command(MirrorCommand(vm, {1, 2, 3, 4}, {1, 2, 3, 4}, plane="YZ"))
    vm.undo_stack.undo()
    assert len(vm.project.nodes) == 4
    assert len(vm.project.elements) == 4
