"""Tests for DrawTrussTool — two-click truss-bar drawing."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    CoordinateGridSystem,
    CoordinateSystem,
    ElasticUniaxial,
    GridSystem,
    Node,
    TrussElement,
    make_grid_lines,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402
from opensees_studio.views.canvas3d.selection import SelectionState  # noqa: E402
from opensees_studio.views.tools.draw_truss import DrawTrussTool  # noqa: E402


class _CanvasStub:
    def __init__(self) -> None:
        self.selection = SelectionState()

    def view_xy(self) -> None:
        pass

    def set_snap_preview_enabled(self, _enabled: bool) -> None:
        pass


def _vm_with_grid_and_nodes() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.nodes.extend([
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(3, 0, 0)),
    ])
    vm.project.coord_systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                y_grid_lines=make_grid_lines("Y", [0.0]),
                z_grid_lines=make_grid_lines("Z", [0.0]),
            ),
        ),
    ]
    return vm


@pytest.mark.gui
def test_two_clicks_create_truss(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid_and_nodes()
    tool = DrawTrussTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()

    tool.on_node_picked(1)
    tool.on_node_picked(2)

    assert len(vm.project.elements) == 1     # type: ignore[union-attr]
    el = vm.project.elements[0]              # type: ignore[union-attr]
    assert isinstance(el, TrussElement)
    assert el.nodes == (1, 2)
    assert el.area > 0
    # A default ElasticUniaxial must have been created for the material.
    assert len(vm.project.materials) == 1    # type: ignore[union-attr]
    assert isinstance(vm.project.materials[0], ElasticUniaxial)


@pytest.mark.gui
def test_draw_truss_reuses_existing_material(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid_and_nodes()
    vm.project.materials.append(ElasticUniaxial(id=1, name="Existing", E=150e9))  # type: ignore[union-attr]
    tool = DrawTrussTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_node_picked(1)
    tool.on_node_picked(2)
    el = vm.project.elements[0]              # type: ignore[union-attr]
    assert el.material_id == 1
    assert len(vm.project.materials) == 1    # type: ignore[union-attr]  (no new material)


@pytest.mark.gui
def test_empty_click_creates_node_then_truss(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Canvas-assumed: coordinates passed are already on a snap target."""
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.coord_systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                y_grid_lines=make_grid_lines("Y", [0.0]),
                z_grid_lines=make_grid_lines("Z", [0.0]),
            ),
        ),
    ]
    tool = DrawTrussTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_empty_clicked(0.0, 0.0, 0.0)
    tool.on_empty_clicked(3.0, 0.0, 0.0)

    # Two nodes created + one truss element.
    assert len(vm.project.nodes) == 2        # type: ignore[union-attr]
    assert len(vm.project.elements) == 1     # type: ignore[union-attr]
    assert isinstance(vm.project.elements[0], TrussElement)


@pytest.mark.gui
def test_self_pick_is_ignored(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_grid_and_nodes()
    tool = DrawTrussTool(_CanvasStub(), vm)  # type: ignore[arg-type]
    tool.activate()
    tool.on_node_picked(1)
    tool.on_node_picked(1)    # same node — must not create a zero-length truss
    assert vm.project.elements == []         # type: ignore[union-attr]
