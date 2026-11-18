"""Cylindrical grids, grid labels and the "continue the grid" helpers (core only)."""

from __future__ import annotations

import json
import math

import pytest

from opensees_studio.core.geometry import (
    GridLine,
    GridSystem,
    grid_line_ids,
    make_grid_lines,
    next_grid_id,
    next_grid_ordinate,
    regular_grid_lines,
)


def _radial(**options: object) -> GridSystem:
    return GridSystem.model_validate(
        {
            "system_type": "Cylindrical",
            "x_grid_lines": make_grid_lines("X", [5.0, 10.0]),
            "y_grid_lines": make_grid_lines("Y", [0.0, 90.0, 180.0, 270.0]),
            "z_grid_lines": make_grid_lines("Z", [0.0, 3.0]),
            **options,
        }
    )


def test_default_options_keep_old_files_identical() -> None:
    grid = GridSystem(x_grid_lines=make_grid_lines("X", [0.0, 6.0]))
    dumped = grid.model_dump(mode="json")
    for key in ("system_type", "show_labels", "label_content", "label_size", "label_color"):
        assert key not in dumped
    assert GridSystem.model_validate(json.loads(json.dumps(dumped))) == grid


def test_radial_intersections_are_ring_by_angle_at_every_level() -> None:
    points = _radial().intersections()
    assert len(points) == 2 * 4 * 2
    assert (0.0, 10.0, 3.0) in points  # r = 10, 90°, z = 3: exact, no 6e-16
    assert all(math.hypot(p[0], p[1]) in (5.0, 10.0) for p in points)


def test_radial_snap_moves_radius_and_angle_together() -> None:
    grid = _radial()
    assert grid.snap_local((6.0, 6.5, 0.2)) == (0.0, 10.0, 0.0)
    # Working plane XY: the elevation stays where it is.
    assert grid.snap_local((-4.0, 0.5, 1.2), axes=(0, 1)) == (-5.0, 0.0, 1.2)
    # Elevation (XZ): the point stays on its plane, only the level snaps.
    assert grid.snap_local((6.0, 0.0, 2.6), axes=(0, 2)) == (6.0, 0.0, 3.0)
    # Angles wrap: -80° is closest to 270°.
    snapped = grid.snap_local((1.0, -6.0, 0.0))
    assert snapped == (0.0, -5.0, 0.0)


def test_full_turn_rings_close_and_partial_rings_are_arcs() -> None:
    def ring_angles(grid: GridSystem) -> list[float]:
        ends = [p for seg in grid.segments() for p in seg if p[2] == 0.0]
        return sorted(
            {round(math.degrees(math.atan2(p[1], p[0])) % 360, 3) for p in ends if p[0] or p[1]}
        )

    closed = ring_angles(_radial())
    assert max(closed) > 350.0  # goes all the way round
    arc = _radial(y_grid_lines=make_grid_lines("Y", [0.0, 45.0, 90.0]))
    assert max(ring_angles(arc)) == pytest.approx(90.0)


def test_hidden_lines_and_hide_all() -> None:
    lines = make_grid_lines("X", [0.0, 5.0, 10.0])
    lines[1] = lines[1].model_copy(update={"visible": False})
    grid = GridSystem(x_grid_lines=lines, y_grid_lines=make_grid_lines("Y", [0.0]))
    assert [p[0] for p in grid.intersections()] == [0.0, 10.0]
    assert grid.snap_local((4.0, 0.0, 0.0))[0] == 0.0
    assert grid.shown
    assert not grid.model_copy(update={"hide_all": True}).shown
    assert not GridSystem().shown


def test_labels_content_and_both_ends() -> None:
    lines = [GridLine(id="A", ordinate=0.0, bubble_loc="Both"), GridLine(id="B", ordinate=6.0)]
    grid = GridSystem(x_grid_lines=lines, y_grid_lines=make_grid_lines("Y", [0.0, 4.0]))
    texts = [t for _p, t in grid.labels()]
    assert texts.count("A") == 2 and texts.count("B") == 1
    with_coord = grid.model_copy(update={"label_content": "ID + coordinate"})
    assert "B (6)" in [t for _p, t in with_coord.labels()]
    only = grid.model_copy(update={"label_content": "Coordinate"})
    assert "6" in [t for _p, t in only.labels()]
    assert grid.model_copy(update={"show_labels": False}).labels() == []
    # Start label sits before the first Y line, End label beyond the last one.
    a_points = sorted(p[1] for p, t in grid.labels() if t == "A")
    assert a_points[0] < 0.0 < 4.0 < a_points[1]


def test_radial_lines_are_labelled_with_degrees() -> None:
    grid = _radial(label_content="Coordinate")
    assert "90°" in [t for _p, t in grid.labels()]


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        ([], "X1"),
        (["X1", "X2"], "X3"),
        (["A", "B"], "C"),
        (["Z"], "AA"),
        (["7"], "8"),
        (["L09"], "L10"),
        (["A", "B", "foo"], "X4"),
        (["X1", "X2", "X3"], "X4"),
    ],
)
def test_next_grid_id(ids: list[str], expected: str) -> None:
    assert next_grid_id(ids, "X") == expected


def test_next_grid_id_never_repeats_a_taken_one() -> None:
    assert next_grid_id(["X2", "X1"], "X") == "X3"


def test_next_grid_ordinate_uses_the_last_spacing() -> None:
    assert next_grid_ordinate([]) == 0.0
    assert next_grid_ordinate([3.0]) == 4.0
    assert next_grid_ordinate([0.0, 6.0, 13.5]) == 21.0
    assert next_grid_ordinate([2.0, 2.0]) == 3.0


def test_regular_grid_lines_and_id_styles() -> None:
    lines = regular_grid_lines(3, 4.0, 1.0, axis="X", id_style="Letters")
    assert [(ln.id, ln.ordinate) for ln in lines] == [("A", 1.0), ("B", 5.0), ("C", 9.0)]
    assert grid_line_ids("Numbers", 2, "Y") == ["1", "2"]
    assert grid_line_ids("Axis", 2, "Z") == ["Z1", "Z2"]
    assert len(grid_line_ids("Letters", 28, "X")) == 28
    assert regular_grid_lines(0, 1.0, axis="X") == []
