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
