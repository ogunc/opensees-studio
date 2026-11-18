"""Grid Wizard, Add Row continuing the grid, grid labels, hiding grids, right-click menu."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from opensees_studio.core import CoordinateGridSystem, GridSystem, make_grid_lines


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    return mw


@pytest.mark.gui
def test_wizard_builds_a_radial_grid(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.grid_wizard import NEW_SYSTEM, GridWizardDialog

    dlg = GridWizardDialog([CoordinateGridSystem(name="Global")])
    qtbot.addWidget(dlg)
    assert dlg.target() == "Global"  # the empty Global grid is offered first
    dlg.target_combo.setCurrentIndex(0)
    assert dlg.target() == NEW_SYSTEM
    dlg.type_combo.setCurrentText("Cylindrical")
    dlg.counts[0].setValue(2)
    dlg.spacings[0].setValue(4.0)
    dlg.firsts[0].setValue(4.0)
    dlg.counts[1].setValue(6)
    dlg.spacings[1].setValue(60.0)
    dlg.label_position.setCurrentText("Both")
    system = dlg.system()
    assert system.grid.is_cylindrical
    assert system.grid.x_lines == [4.0, 8.0]
    assert system.grid.y_lines == [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]
    assert {ln.bubble_loc for ln in system.grid.y_grid_lines} == {"Both"}
    assert "Radial lines" in dlg.preview.text()


@pytest.mark.gui
def test_wizard_rejects_more_than_a_full_turn(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.grid_wizard import GridWizardDialog

    dlg = GridWizardDialog([CoordinateGridSystem(name="Global")])
    qtbot.addWidget(dlg)
    dlg.type_combo.setCurrentText("Cylindrical")
    dlg.counts[1].setValue(9)
    dlg.spacings[1].setValue(45.0)
    with pytest.raises(ValueError, match="full turn"):
        dlg.grid_system()
    dlg.accept()
    assert dlg.result() == 0


@pytest.mark.gui
def test_wizard_cartesian_names(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.grid_wizard import GridWizardDialog

    dlg = GridWizardDialog([], ndm=2)
    qtbot.addWidget(dlg)
    grid = dlg.grid_system()
    assert [ln.id for ln in grid.x_grid_lines] == ["A", "B", "C", "D"]
    assert grid.y_grid_lines == []  # a 2D model has no Y lines
    assert not dlg.type_combo.isEnabled()


@pytest.mark.gui
def test_add_row_continues_spacing_and_ids(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.define_grid_data import _AxisGridTable

    table = _AxisGridTable("X")
    qtbot.addWidget(table)
    table.load_lines(make_grid_lines("X", [0.0, 6.0, 13.0]))
    table._on_add_row()
    lines = table.collect_lines()
    assert (lines[-1].id, lines[-1].ordinate) == ("X4", 20.0)
    table.set_display_spacing(True)
    table._on_add_row()
    assert [ln.ordinate for ln in table.collect_lines()][-1] == 27.0
    table.set_all_bubble_locations("Both")
    assert {ln.bubble_loc for ln in table.collect_lines()} == {"Both"}


@pytest.mark.gui
def test_grid_dialog_round_trips_type_and_labels(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.define_grid_data import DefineGridSystemDataDialog

    grid = GridSystem.model_validate(
        {
            "system_type": "Cylindrical",
            "x_grid_lines": make_grid_lines("R", [5.0]),
            "y_grid_lines": make_grid_lines("T", [0.0, 90.0]),
            "visible": False,
            "label_content": "ID + coordinate",
            "label_size": 18,
            "label_color": "#AA0000",
            "show_labels": False,
        }
    )
    dlg = DefineGridSystemDataDialog(existing=CoordinateGridSystem(name="Ring", grid=grid))
    qtbot.addWidget(dlg)
    assert dlg._tabs.tabText(0).startswith("R")
    assert dlg.system().grid == grid


@pytest.mark.gui
def test_hide_grids_from_view_menu_is_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    project = mw._vm.project
    systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", [0.0, 5.0]),
                y_grid_lines=make_grid_lines("Y", [0.0, 5.0]),
            ),
        ),
        CoordinateGridSystem(name="B", grid=GridSystem(x_grid_lines=make_grid_lines("X", [1.0]))),
    ]
    project.coord_systems = systems
    assert mw._has_grid_lines()
    mw._act_show_grids.trigger()
    assert all(cs.grid.hide_all for cs in mw._vm.project.coord_systems)
    assert not mw._has_grid_lines()  # hidden grids do not snap either
    assert not mw._act_show_grids.isChecked()
    mw._vm.undo_stack.undo()
    assert not any(cs.grid.hide_all for cs in mw._vm.project.coord_systems)
    assert mw._act_show_grids.isChecked()  # the tick follows Ctrl+Z
    mw._set_grids_shown(False, "B")
    hidden = {cs.name: cs.grid.hide_all for cs in mw._vm.project.coord_systems}
    assert hidden == {"Global": False, "B": True}
    mw._act_show_grid_labels.trigger()
    assert not any(cs.grid.show_labels for cs in mw._vm.project.coord_systems)


@pytest.mark.gui
def test_grid_wizard_fills_the_empty_global_grid(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.grid_wizard import GridWizardDialog

    mw = _window(qtbot)
    monkeypatch.setattr(GridWizardDialog, "exec", lambda self: 1)
    mw._on_grid_wizard()
    (global_cs,) = mw._vm.project.coord_systems
    assert global_cs.name == "Global"
    assert len(global_cs.grid.x_grid_lines) == 4
    mw._vm.undo_stack.undo()
    assert mw._vm.project.coord_systems[0].grid.x_grid_lines == []


def _mouse(kind, pos: QPointF):  # type: ignore[no-untyped-def]
    return QMouseEvent(
        kind,
        pos,
        pos,
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )


@pytest.mark.gui
def test_right_click_requests_the_context_menu_but_a_drag_does_not(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    canvas = mw._canvas
    seen: list[QPoint] = []
    canvas.contextMenuRequested.disconnect()
    canvas.contextMenuRequested.connect(seen.append)
    canvas.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, QPointF(50, 50)))
    canvas.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, QPointF(52, 51)))
    assert len(seen) == 1
    canvas.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, QPointF(50, 50)))
    canvas.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, QPointF(50, 150)))
    assert len(seen) == 1  # a right drag is a zoom


@pytest.mark.gui
def test_context_menu_lists_grid_switches(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._vm.project.coord_systems = [
        CoordinateGridSystem(name="Global"),
        CoordinateGridSystem(name="Other"),
    ]
    menu = mw._canvas_context_menu()
    texts = [a.text() for a in menu.actions()]
    for expected in ("Show &Grids", "Grids by system", "Show Grid &Labels", "Grid &Wizard…"):
        assert expected in texts
    menu.deleteLater()


# ───────────────────── Grid Line View and the selection menu ─────────────────────
def _building(qtbot):  # type: ignore[no-untyped-def]
    from pathlib import Path

    mw = _window(qtbot)
    mw._vm.open(Path(__file__).parents[2] / "examples" / "building_3storey_diaphragm.osmodel")
    return mw


@pytest.mark.gui
def test_grid_line_view_shows_only_one_frame_line(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.grid_line_view import GridLineViewDialog

    mw = _building(qtbot)
    project = mw._vm.project

    def pick(self):  # type: ignore[no-untyped-def]
        self.line_combo.setCurrentIndex(self.line_combo.findData("Global: X X2 (6)"))
        assert self.tolerance() == pytest.approx(0.05)  # 50 mm in a model in m
        assert "joint(s)" in self.count.text()
        return 1

    monkeypatch.setattr(GridLineViewDialog, "exec", pick)
    mw._on_grid_line_view()
    shown = mw._canvas._renderer._project
    assert shown is not None and shown is not project
    assert shown.nodes and all(abs(n.coords[0] - 6.0) <= 0.05 for n in shown.nodes)
    assert len(shown.elements) < len(project.elements)
    assert mw._canvas.working_plane_type() == "YZ"  # an X line is seen from the right
    assert mw._act_show_all_objects.isEnabled()
    # The model is untouched, and Show All brings everything back.
    assert len(mw._vm.project.elements) == len(project.elements)
    mw._act_show_all_objects.trigger()
    assert len(mw._canvas._renderer._project.elements) == len(project.elements)
    assert not mw._act_show_all_objects.isEnabled()


@pytest.mark.gui
def test_grid_line_view_level_and_window(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.grid_line_view import GridLineViewDialog

    mw = _building(qtbot)

    def pick(self):  # type: ignore[no-untyped-def]
        self.line_combo.setCurrentIndex(self.line_combo.findData("Global: Z Z2 (3.5)"))
        self.window_field.setValue(0.2)
        return 1

    monkeypatch.setattr(GridLineViewDialog, "exec", pick)
    mw._on_grid_line_view()
    shown = mw._canvas._renderer._project
    assert {round(n.coords[2], 6) for n in shown.nodes} == {3.5}
    assert mw._canvas.working_plane_type() == "XY"
    assert mw._grid_view == ("Global: Z Z2 (3.5)", 0.2)
    # The window is remembered for the next time.
    seen: list[float] = []
    monkeypatch.setattr(GridLineViewDialog, "exec", lambda self: seen.append(self.tolerance()) or 0)
    mw._on_grid_line_view()
    assert seen == [0.2]


@pytest.mark.gui
def test_selection_menu_lists_joint_options(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _building(qtbot)
    node = mw._vm.project.nodes[0].id
    mw._canvas.selection.set_selection({node}, set())
    menu = mw._canvas_context_menu()
    texts = [a.text() for a in menu.actions()]
    assert texts[0] == "1 joint(s) selected"
    assert mw._act_assign_support.text() in texts
    assert mw._act_assign_section.text() not in texts
    assert mw._act_delete.text() in texts
    assert mw._act_show_grids.text() not in texts
    menu.deleteLater()


@pytest.mark.gui
def test_selection_menu_with_joints_and_frames_uses_submenus(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _building(qtbot)
    project = mw._vm.project
    mw._canvas.selection.set_selection({project.nodes[0].id}, {project.elements[0].id})
    menu = mw._canvas_context_menu()
    texts = [a.text() for a in menu.actions()]
    assert texts[0] == "1 joint(s), 1 element(s) selected"
    assert "Joint" in texts and "Frame" in texts
    menu.deleteLater()
    mw._canvas.selection.clear()
    menu = mw._canvas_context_menu()
    assert mw._act_show_grids.text() in [a.text() for a in menu.actions()]
    menu.deleteLater()
