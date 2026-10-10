"""Grid-system tests that need a QApplication: dialogs, undoable commands, snapping.

Moved out of ``tests/unit/test_grid_system.py``: requesting ``qtbot``
there made pytest-qt build a QApplication inside the unit suite, which
aborts without a Qt platform plugin (``QT_QPA_PLATFORM=offscreen`` on a
headless machine).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridSystem,
    default_global_system,
)


@pytest.mark.gui
def test_set_grid_system_command_is_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    """SetGridSystemCommand must preserve the previous grid for undo."""
    from opensees_studio.commands import SetGridSystemCommand
    from opensees_studio.viewmodels import ProjectViewModel

    vm = ProjectViewModel()
    vm.new_project()
    assert vm.project is not None
    # Start from an empty grid, set a new one, undo, redo.
    new_grid = GridSystem(x_lines=[0.0, 2.0, 4.0])
    vm.apply_command(SetGridSystemCommand(vm, new_grid))
    assert vm.project.grid_system.x_lines == [0.0, 2.0, 4.0]
    vm.undo_stack.undo()
    assert vm.project.grid_system.x_lines == []
    vm.undo_stack.redo()
    assert vm.project.grid_system.x_lines == [0.0, 2.0, 4.0]


@pytest.mark.gui
def test_add_node_dialog_snaps(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AddNodeDialog snaps to nearest grid line when the flag is set."""
    from opensees_studio.views.dialogs.add_node import AddNodeDialog

    grid = GridSystem(x_lines=[0.0, 3.0, 6.0], y_lines=[0.0, 4.0], z_lines=[0.0])
    dlg = AddNodeDialog(next_node_id=1, grid=grid, ndm=3)
    qtbot.addWidget(dlg)
    dlg._x.setValue(3.4)  # → should snap to 3.0
    dlg._y.setValue(3.9)  # → should snap to 4.0
    dlg._z.setValue(-0.3)  # → should snap to 0.0
    dlg._snap_cb.setChecked(True)
    node = dlg.node()
    assert node.coords == (3.0, 4.0, 0.0)


@pytest.mark.gui
def test_add_node_dialog_no_snap(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Without the snap flag, AddNodeDialog preserves entered coordinates."""
    from opensees_studio.views.dialogs.add_node import AddNodeDialog

    grid = GridSystem(x_lines=[0.0, 3.0], y_lines=[0.0])
    dlg = AddNodeDialog(next_node_id=1, grid=grid, ndm=3)
    qtbot.addWidget(dlg)
    dlg._x.setValue(1.7)
    dlg._y.setValue(0.2)
    dlg._z.setValue(5.5)
    dlg._snap_cb.setChecked(False)
    node = dlg.node()
    assert node.coords == pytest.approx((1.7, 0.2, 5.5))


@pytest.mark.gui
def test_snap_across_systems_picks_closest(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A click near Floor2's intersection must snap there, not to Global."""
    from opensees_studio.views.tools.draw_node import _snap_across_systems

    systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(x_lines=[0.0, 3.0], y_lines=[0.0], z_lines=[0.0]),
        ),
        CoordinateGridSystem(
            name="Floor2",
            coord=CoordinateSystem(origin=(0, 0, 3.0)),
            grid=GridSystem(x_lines=[0.0, 3.0], y_lines=[0.0], z_lines=[0.0]),
        ),
    ]
    # Click near Floor2 grid intersection at world (3, 0, 3) — closer to Floor2.
    result = _snap_across_systems((2.9, 0.1, 2.9), systems)
    assert result == pytest.approx((3.0, 0.0, 3.0), abs=1e-9)

    # Click near Global's (3, 0, 0) — should snap there.
    result2 = _snap_across_systems((2.9, 0.1, 0.1), systems)
    assert result2 == pytest.approx((3.0, 0.0, 0.0), abs=1e-9)


@pytest.mark.gui
def test_set_coord_systems_command_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    """SetCoordSystemsCommand atomically swaps the whole list (undoable)."""
    from opensees_studio.commands import SetCoordSystemsCommand
    from opensees_studio.viewmodels import ProjectViewModel

    vm = ProjectViewModel()
    vm.new_project()
    assert vm.project is not None
    new_list = [
        default_global_system(),
        CoordinateGridSystem(
            name="Floor2",
            coord=CoordinateSystem(origin=(0, 0, 3)),
            grid=GridSystem(x_lines=[0, 6]),
        ),
    ]
    vm.apply_command(SetCoordSystemsCommand(vm, new_list))
    assert [cs.name for cs in vm.project.coord_systems] == ["Global", "Floor2"]
    vm.undo_stack.undo()
    assert [cs.name for cs in vm.project.coord_systems] == ["Global"]
    vm.undo_stack.redo()
    assert len(vm.project.coord_systems) == 2
