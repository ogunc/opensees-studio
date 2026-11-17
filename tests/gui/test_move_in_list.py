"""View → Move Up / Move Down in List: the next level, showing only its objects."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (
    CoordinateGridSystem,
    ElasticBeamColumn,
    GridSystem,
    Node,
    make_grid_lines,
)

pytestmark = pytest.mark.gui


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    vm = window._vm
    vm.new_project()
    project = vm.project
    project.coord_systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", [0.0, 6.0]),
                y_grid_lines=make_grid_lines("Y", [0.0]),
                z_grid_lines=make_grid_lines("Z", [0.0, 3.0, 6.0]),
            ),
        )
    ]
    # A column stack: 1-2 below Z = 3, 2-3 above, and a beam 2-4 at Z = 3.
    project.nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(0.0, 0.0, 3.0)),
        Node(id=3, coords=(0.0, 0.0, 6.0)),
        Node(id=4, coords=(6.0, 0.0, 3.0)),
    ]
    project.elements = [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ElasticBeamColumn(id=3, nodes=(2, 4), section_id=1),
    ]
    vm.projectChanged.emit(project)
    return window


def test_the_arrows_step_through_the_levels_of_a_plan(qtbot) -> None:
    window = _window(qtbot)
    try:
        assert not window._act_level_up.isEnabled()  # 3D view: no levels
        window._act_view_top.trigger()
        assert window._act_level_up.isEnabled()
        assert window._canvas.working_plane_offset() == 0.0

        window._act_level_up.trigger()
        assert window._canvas.working_plane_offset() == 3.0
        assert window._grid_view is not None and "Z2" in window._grid_view[0]
        assert window._act_show_all_objects.isEnabled()

        # Picking a level in the combo keeps showing one level at a time.
        window._level_combo.setCurrentIndex(2)
        assert window._canvas.working_plane_offset() == 6.0
        assert "Z3" in window._grid_view[0]

        window._act_level_up.trigger()  # already at the top
        assert window._canvas.working_plane_offset() == 6.0
        assert "No further level" in window.statusBar().currentMessage()

        window._act_level_down.trigger()
        assert window._canvas.working_plane_offset() == 3.0

        window._act_show_all_objects.trigger()
        assert window._grid_view is None
    finally:
        window._help_controller.uninstall()


def test_an_elevation_steps_through_its_grid_lines(qtbot) -> None:
    window = _window(qtbot)
    try:
        window._act_view_right.trigger()  # YZ: the X lines
        assert window._canvas.working_plane_offset() == 0.0
        window._act_level_up.trigger()
        assert window._canvas.working_plane_offset() == 6.0
        assert "X2" in window._grid_view[0]
    finally:
        window._help_controller.uninstall()
