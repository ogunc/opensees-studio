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
@pytest.mark.gui
def test_empty_click_snaps_and_creates_node(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid()
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    # Click near (0, 0) — should snap to exactly (0, 0, 0).
    tool.on_empty_clicked(0.1, -0.2, 0.0)
    assert len(vm.project.nodes) == 1  # type: ignore[union-attr]
    n = vm.project.nodes[0]  # type: ignore[union-attr]
    assert n.coords == (0.0, 0.0, 0.0)

    # Click closer to the (3, 4) intersection.
    tool.on_empty_clicked(2.6, 3.9, 0.1)
    assert len(vm.project.nodes) == 2  # type: ignore[union-attr]
    assert vm.project.nodes[1].coords == (3.0, 4.0, 0.0)  # type: ignore[union-attr]


@pytest.mark.gui
def test_empty_click_without_grid_uses_raw_coords(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()   # default: empty grid
    tool = DrawNodeTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_empty_clicked(1.7, 2.3, 0.0)
    assert vm.project.nodes[0].coords == pytest.approx((1.7, 2.3, 0.0))  # type: ignore[union-attr]


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
