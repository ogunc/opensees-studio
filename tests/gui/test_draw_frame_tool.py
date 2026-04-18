"""Unit tests for DrawFrameTool.

The tool needs a ``canvas`` reference for selection feedback, so we
substitute a tiny stub that exposes only what the tool touches:
``selection.select_node()`` and ``selection.clear()``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import AddNodesCommand  # noqa: E402
from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node  # noqa: E402
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402
from opensees_studio.views.canvas3d import SelectionState  # noqa: E402
from opensees_studio.views.tools.draw_frame import DrawFrameTool  # noqa: E402


class _CanvasStub:
    """The minimum interface DrawFrameTool reads from a ModelCanvas."""

    def __init__(self) -> None:
        self.selection = SelectionState()

    def view_xy(self) -> None:
        # Tool calls view_xy() on activate; stub accepts and ignores.
        pass


def _vm_with_two_nodes() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(3, 0, 0)),
    ]))
    return vm


# ──────────────────────────── basic flow ────────────────────────────
@pytest.mark.gui
def test_first_pick_stores_node_and_highlights(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_two_nodes()
    canvas = _CanvasStub()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    assert tool._first_node_id == 1
    assert canvas.selection.nodes == frozenset({1})
    # No element should have been created yet.
    assert vm.project.elements == []


@pytest.mark.gui
def test_second_pick_creates_element_and_resets(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_two_nodes()
    canvas = _CanvasStub()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    tool.on_node_picked(2)

    # One element + one auto-created default section, all in a single macro.
    assert len(vm.project.elements) == 1
    assert isinstance(vm.project.elements[0], ElasticBeamColumn)
    assert vm.project.elements[0].nodes == (1, 2)
    assert len(vm.project.sections) == 1
    assert isinstance(vm.project.sections[0], ElasticSection)
    # Tool should have reset and cleared the highlight.
    assert tool._first_node_id is None
    assert canvas.selection.is_empty


@pytest.mark.gui
def test_self_pick_is_ignored(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_two_nodes()
    canvas = _CanvasStub()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    tool.on_node_picked(1)   # same node — should NOT create an element
    assert vm.project.elements == []
    # First-node state preserved so user can finish the gesture.
    assert tool._first_node_id == 1


# ──────────────────────────── undo as macro ────────────────────────────
@pytest.mark.gui
def test_draw_frame_undoes_atomically(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Section + element should disappear in one Undo, not two."""
    vm = _vm_with_two_nodes()
    canvas = _CanvasStub()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    tool.on_node_picked(2)
    assert len(vm.project.sections) == 1
    assert len(vm.project.elements) == 1

    vm.undo_stack.undo()
    # Both should be gone after a single undo (macro).
    assert vm.project.sections == []
    assert vm.project.elements == []


@pytest.mark.gui
def test_subsequent_draws_reuse_existing_section(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_two_nodes()
    vm.apply_command(AddNodesCommand(vm, [Node(id=3, coords=(6, 0, 0))]))
    canvas = _CanvasStub()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    tool.on_node_picked(2)
    tool.on_node_picked(2)
    tool.on_node_picked(3)

    # Section created once; second draw reuses it.
    assert len(vm.project.sections) == 1
    assert len(vm.project.elements) == 2


# ──────────────────────────── reset ────────────────────────────
@pytest.mark.gui
def test_reset_clears_first_pick(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_two_nodes()
    canvas = _CanvasStub()
    tool = DrawFrameTool(canvas, vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    assert tool._first_node_id == 1
    tool.reset()
    assert tool._first_node_id is None
    assert canvas.selection.is_empty


# ──────────────────── empty-click → auto-node → frame ───────────────
@pytest.mark.gui
def test_empty_clicks_snap_and_create_frame(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Two clicks on empty grid intersections → 2 nodes + 1 frame."""
    from opensees_studio.core import GridSystem
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.grid_system = GridSystem(  # type: ignore[union-attr]
        x_lines=[0.0, 3.0, 6.0],
        y_lines=[0.0, 4.0],
        z_lines=[0.0],
    )
    tool = DrawFrameTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    # Canvas does the pixel-snap before emitting; tool receives exact
    # intersection coords.
    tool.on_empty_clicked(0.0, 0.0, 0.0)
    tool.on_empty_clicked(3.0, 4.0, 0.0)

    assert len(vm.project.nodes) == 2       # type: ignore[union-attr]
    assert len(vm.project.elements) == 1    # type: ignore[union-attr]
    elem = vm.project.elements[0]           # type: ignore[union-attr]
    assert isinstance(elem, ElasticBeamColumn)
    n1 = next(n for n in vm.project.nodes if n.id == elem.nodes[0])  # type: ignore[union-attr]
    n2 = next(n for n in vm.project.nodes if n.id == elem.nodes[1])  # type: ignore[union-attr]
    assert n1.coords == (0.0, 0.0, 0.0)
    assert n2.coords == (3.0, 4.0, 0.0)


@pytest.mark.gui
def test_empty_click_reuses_coincident_node(qtbot) -> None:  # type: ignore[no-untyped-def]
    """An empty click at an existing node's location must not duplicate it."""
    from opensees_studio.core import GridSystem
    vm = _vm_with_two_nodes()   # nodes 1, 2 at (0,0,0) and (3,0,0)
    vm.project.grid_system = GridSystem(  # type: ignore[union-attr]
        x_lines=[0.0, 3.0], y_lines=[0.0], z_lines=[0.0],
    )
    tool = DrawFrameTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_empty_clicked(0.0, 0.0, 0.0)   # existing node 1 at (0,0,0)
    tool.on_empty_clicked(3.0, 0.0, 0.0)   # existing node 2 at (3,0,0)

    assert len(vm.project.nodes) == 2        # type: ignore[union-attr]  (no new nodes)
    elem = vm.project.elements[0]            # type: ignore[union-attr]
    assert set(elem.nodes) == {1, 2}


@pytest.mark.gui
def test_mixed_node_pick_then_empty_click(qtbot) -> None:  # type: ignore[no-untyped-def]
    """First click picks existing node; second click creates new node + frame."""
    from opensees_studio.core import GridSystem
    vm = _vm_with_two_nodes()
    vm.project.grid_system = GridSystem(  # type: ignore[union-attr]
        x_lines=[0.0, 3.0, 6.0], y_lines=[0.0], z_lines=[0.0],
    )
    tool = DrawFrameTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)               # start at node 1 = (0,0,0)
    tool.on_empty_clicked(6.0, 0.0, 0.0)  # canvas emits exact snap

    assert len(vm.project.nodes) == 3    # type: ignore[union-attr]  (new node added)
    assert len(vm.project.elements) == 1
    new_node = vm.project.nodes[-1]      # type: ignore[union-attr]
    assert new_node.coords == (6.0, 0.0, 0.0)
    elem = vm.project.elements[0]
    assert set(elem.nodes) == {1, new_node.id}
