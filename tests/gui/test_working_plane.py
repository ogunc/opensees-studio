"""Tests for the SAP2000-style working plane (plan / elevation level)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    CoordinateGridSystem,
    GridSystem,
    Project,
    make_grid_lines,
)


def _multi_z_project() -> Project:
    return Project(
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                    y_grid_lines=make_grid_lines("Y", [0.0, 4.0]),
                    z_grid_lines=make_grid_lines("Z", [0.0, 3.0, 6.0]),
                ),
            ),
        ],
    )


@pytest.mark.gui
def test_no_working_plane_returns_all_intersections(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_multi_z_project())
    assert canvas.working_plane_type() is None
    pts = canvas._grid_intersections_world()
    # 2 × 2 × 3 = 12 intersections
    assert pts is not None and pts.shape == (12, 3)


@pytest.mark.gui
def test_xy_plane_filters_to_single_z_level(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_multi_z_project())

    canvas.set_working_plane("XY", 3.0)
    assert canvas.working_plane_type() == "XY"
    assert canvas.working_plane_offset() == pytest.approx(3.0)
    pts = canvas._grid_intersections_world()
    # Only intersections at z=3 should remain → 2×2 = 4
    assert pts is not None and pts.shape == (4, 3)
    assert np.allclose(pts[:, 2], 3.0)


@pytest.mark.gui
def test_xz_plane_filters_to_single_y_level(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_multi_z_project())
    canvas.set_working_plane("XZ", 4.0)
    pts = canvas._grid_intersections_world()
    # 2 × 1 × 3 = 6 at y=4
    assert pts is not None and pts.shape == (6, 3)
    assert np.allclose(pts[:, 1], 4.0)


@pytest.mark.gui
def test_yz_plane_filters_to_single_x_level(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_multi_z_project())
    canvas.set_working_plane("YZ", 0.0)
    pts = canvas._grid_intersections_world()
    # 1 × 2 × 3 = 6 at x=0
    assert pts is not None and pts.shape == (6, 3)
    assert np.allclose(pts[:, 0], 0.0)


@pytest.mark.gui
def test_clear_working_plane_restores_all(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_multi_z_project())
    canvas.set_working_plane("XY", 6.0)
    canvas.clear_working_plane()
    assert canvas.working_plane_type() is None
    pts = canvas._grid_intersections_world()
    assert pts is not None and pts.shape == (12, 3)


@pytest.mark.gui
def test_invalid_plane_raises(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    with pytest.raises(ValueError):
        canvas.set_working_plane("XX", 0.0)  # type: ignore[arg-type]


@pytest.mark.gui
def test_offset_with_no_matching_grid_returns_none(qtbot) -> None:  # type: ignore[no-untyped-def]
    """If the user picks a level that doesn't match any intersection
    (e.g. typed a custom value off the grid), the snap list is empty
    so draw-click does nothing."""
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_multi_z_project())
    canvas.set_working_plane("XY", 1.234)    # not in [0, 3, 6]
    assert canvas._grid_intersections_world() is None


# ── renderer: grid overlay follows the active plane ──────────────────
@pytest.mark.gui
def test_switching_levels_rebuilds_grid_actors(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Activating a plane should rebuild the grid so only that level
    renders — ensuring the screen actually changes when the user
    switches Z=0 → Z=3."""
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_multi_z_project())

    # Without a working plane the renderer builds grid + vertical
    # connectors across all 3 Z-levels. Count aux actors as a proxy.
    base_count = len(canvas._renderer._aux_actors)
    assert base_count >= 2   # at least one grid-lines + one dots actor

    # Pick an XY plane at Z=3 → render rebuilt.
    canvas.set_working_plane("XY", 3.0)
    single_level_count = len(canvas._renderer._aux_actors)
    # Still has grid lines and intersection dots, but no vertical
    # connectors; typically fewer overall actors/points.
    assert single_level_count >= 2

    # Intersections actually filter: snap candidates drop to 2×2 = 4.
    pts = canvas._grid_intersections_world()
    assert pts is not None and pts.shape == (4, 3)
    assert np.allclose(pts[:, 2], 3.0)

    # Switching to Z=6 changes snap targets but actor count stays similar.
    canvas.set_working_plane("XY", 6.0)
    pts2 = canvas._grid_intersections_world()
    assert pts2 is not None and np.allclose(pts2[:, 2], 6.0)

    # Clearing goes back to full 3D.
    canvas.clear_working_plane()
    pts_full = canvas._grid_intersections_world()
    assert pts_full is not None and pts_full.shape == (12, 3)


# ── MainWindow wiring: Top/Front/Right populate the Level combo ───────
@pytest.mark.gui
def test_top_button_populates_level_combo_with_z_ordinates(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.project.coord_systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                y_grid_lines=make_grid_lines("Y", [0.0]),
                z_grid_lines=make_grid_lines("Z", [0.0, 3.0, 6.0]),
            ),
        ),
    ]

    # Default (iso): combo empty / disabled.
    mw._on_view_iso()
    assert not mw._level_combo.isEnabled()

    # Top view: combo fills with Z ordinates, first one active.
    mw._on_view_top()
    assert mw._level_combo.isEnabled()
    assert mw._level_combo.count() == 3
    assert mw._level_combo.itemText(0).startswith("Z = 0")
    assert mw._canvas.working_plane_type() == "XY"
    assert mw._canvas.working_plane_offset() == pytest.approx(0.0)

    # Pick Z=3.
    mw._level_combo.setCurrentIndex(1)
    assert mw._canvas.working_plane_offset() == pytest.approx(3.0)

    # Front view resets combo to Y ordinates.
    mw._on_view_front()
    assert mw._level_combo.itemText(0).startswith("Y = 0")
    assert mw._canvas.working_plane_type() == "XZ"
