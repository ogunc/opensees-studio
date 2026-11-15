"""Quick draw: the grid segment or bay under a point on the working plane."""

from __future__ import annotations

from opensees_studio.core import CoordinateGridSystem, GridSystem, Project, make_grid_lines
from opensees_studio.core.geometry.grid_quick import grid_bay, grid_ordinates, grid_segment


def _project() -> Project:
    project = Project()
    project.coord_systems = [
        CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", [0.0, 6.0, 12.0]),
                y_grid_lines=make_grid_lines("Y", [0.0, 5.0]),
                z_grid_lines=make_grid_lines("Z", [0.0, 3.0, 6.0]),
            ),
        )
    ]
    return project


def test_the_ordinates_are_the_visible_lines() -> None:
    assert grid_ordinates(_project()) == ([0.0, 6.0, 12.0], [0.0, 5.0], [0.0, 3.0, 6.0])


def test_a_point_near_a_line_is_the_segment_between_its_crossings() -> None:
    project = _project()
    # Plan at Z = 3: near the line Y = 0, between X = 6 and X = 12 (a beam).
    assert grid_segment(project, "XY", 3.0, (8.0, 0.2, 3.0), tolerance=0.5) == (
        (6.0, 0.0, 3.0),
        (12.0, 0.0, 3.0),
    )
    # Elevation Y = 0: near the line X = 6, between Z = 3 and Z = 6 (a column).
    assert grid_segment(project, "XZ", 0.0, (5.9, 0.0, 4.0), tolerance=0.5) == (
        (6.0, 0.0, 3.0),
        (6.0, 0.0, 6.0),
    )
    # Mid-bay, far from every line: no segment; outside the grid: none either.
    assert grid_segment(project, "XY", 0.0, (3.0, 2.5, 0.0), tolerance=0.5) is None
    assert grid_segment(project, "XY", 0.0, (20.0, 0.0, 0.0), tolerance=0.5) is None


def test_a_point_inside_a_bay_is_its_four_corners() -> None:
    project = _project()
    assert grid_bay(project, "XY", 3.0, (8.0, 2.0, 3.0)) == [
        (6.0, 0.0, 3.0),
        (12.0, 0.0, 3.0),
        (12.0, 5.0, 3.0),
        (6.0, 5.0, 3.0),
    ]
    assert grid_bay(project, "XY", 3.0, (-1.0, 2.0, 3.0)) is None
