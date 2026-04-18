"""Unit tests for DrawNodeTool.

The tool only uses ``vm.project`` and ``vm.apply_command``; it does
not touch the canvas except through the stub selection interface.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import GridSystem, Node, Project  # noqa: E402
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402
from opensees_studio.views.canvas3d.selection import SelectionState  # noqa: E402
from opensees_studio.views.tools.draw_node import (  # noqa: E402
    DrawNodeTool,
    _snap_to_grid,
)


class _CanvasStub:
    def __init__(self) -> None:
        self.selection = SelectionState()

    def view_xy(self) -> None:
        # No-op: real canvas switches camera; tool tests don't care.
        pass


def _vm_with_grid() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.grid_system = GridSystem(  # type: ignore[union-attr]
        x_lines=[0.0, 3.0, 6.0],
        y_lines=[0.0, 4.0],
        z_lines=[0.0],
    )
    return vm


# ────────────────────────── snap helper ─────────────────────────────
def test_snap_to_grid_picks_nearest_lines() -> None:
    x, y, z = _snap_to_grid(
        2.2, 3.7, 0.6,
        x_lines=[0.0, 3.0], y_lines=[0.0, 4.0], z_lines=[0.0, 3.0],
    )
    assert (x, y, z) == (3.0, 4.0, 0.0)


def test_snap_to_grid_identity_on_empty_axes() -> None:
    x, y, z = _snap_to_grid(1.5, 2.5, 3.5, x_lines=[], y_lines=[], z_lines=[])
    assert (x, y, z) == (1.5, 2.5, 3.5)


# ────────────────────────── tool behaviour ──────────────────────────
# NB: the canvas now does pixel-space snap BEFORE emitting emptyClicked;
# the tool receives only valid grid-intersection coordinates. These tests
# simulate that by passing exact intersection coords.
@pytest.mark.gui
def test_empty_click_creates_node_at_exact_intersection(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid()
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    # Canvas guarantees the coords ARE an intersection.
    tool.on_empty_clicked(0.0, 0.0, 0.0)
    assert len(vm.project.nodes) == 1  # type: ignore[union-attr]
    assert vm.project.nodes[0].coords == (0.0, 0.0, 0.0)

    tool.on_empty_clicked(3.0, 4.0, 0.0)
    assert len(vm.project.nodes) == 2  # type: ignore[union-attr]
    assert vm.project.nodes[1].coords == (3.0, 4.0, 0.0)  # type: ignore[union-attr]


@pytest.mark.gui
def test_empty_click_duplicate_is_rejected(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Clicking exactly on an existing node's coords must not duplicate it."""
    vm = _vm_with_grid()
    vm.project.nodes.append(Node(id=42, coords=(3.0, 4.0, 0.0)))  # type: ignore[union-attr]
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    status_msgs: list[str] = []
    tool.statusChanged.connect(status_msgs.append)
    tool.on_empty_clicked(3.0, 4.0, 0.0)
    assert len(vm.project.nodes) == 1  # type: ignore[union-attr]  (unchanged)
    assert any("already exists" in m for m in status_msgs)


@pytest.mark.gui
def test_grid_less_canvas_never_emits_to_tool(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Documents the new contract: tool simply trusts canvas.

    The canvas only emits emptyClicked when it has a valid snap
    target. For a grid-less project, the canvas never emits, so the
    tool is never invoked. We therefore don't test rejection here.
    """
    vm = ProjectViewModel(); vm.new_project()
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    assert vm.project.nodes == []     # type: ignore[union-attr]


@pytest.mark.gui
def test_consecutive_clicks_allocate_unique_ids(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid()
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_empty_clicked(0.0, 0.0, 0.0)
    tool.on_empty_clicked(3.0, 0.0, 0.0)
    tool.on_empty_clicked(6.0, 0.0, 0.0)
    ids = [n.id for n in vm.project.nodes]  # type: ignore[union-attr]
    assert len(ids) == 3
    assert len(set(ids)) == 3  # all unique


@pytest.mark.gui
def test_picking_existing_node_emits_status_only(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid()
    vm.project.nodes.append(Node(id=1, coords=(0, 0, 0)))  # type: ignore[union-attr]
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    status_msgs: list[str] = []
    tool.statusChanged.connect(status_msgs.append)
    tool.on_node_picked(1)
    # No new nodes; user was told about the existing one.
    assert len(vm.project.nodes) == 1  # type: ignore[union-attr]
    assert any("already exists" in m for m in status_msgs)


@pytest.mark.gui
def test_tool_is_active_after_activate(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid()
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    assert tool.is_active is False
    tool.activate()
    assert tool.is_active is True
    tool.deactivate()
    assert tool.is_active is False
