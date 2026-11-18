"""Line-diagram geometry for distributed member loads."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("pyvista")

from opensees_studio.views.canvas3d.model_renderer import distributed_load_glyphs


def test_uniform_load_has_a_shaft_and_v_head_per_station_and_one_top_line() -> None:
    bases = [np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])]
    directions = [np.array([0.0, 0.0, -1.0])] * 3
    points, polylines = distributed_load_glyphs(
        bases, directions, [0.5, 0.5, 0.5], np.array([1.0, 0.0, 0.0])
    )

    # Three stations: shaft + two head strokes each, plus the top line.
    assert len(polylines) == 10
    top = polylines[-1]
    assert len(top) == 3
    # A downward load draws its top line above the member (opposite the load).
    np.testing.assert_allclose(
        np.asarray(points)[top],
        [[0.0, 0.0, 0.5], [1.0, 0.0, 0.5], [2.0, 0.0, 0.5]],
        atol=1e-12,
    )


def test_triangular_load_keeps_its_zero_end_on_the_top_line() -> None:
    bases = [np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])]
    directions = [np.zeros(3), np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, -1.0])]
    points, polylines = distributed_load_glyphs(
        bases, directions, [0.0, 0.5, 1.0], np.array([1.0, 0.0, 0.0])
    )

    # No shaft/head at the zero end: 3 + 3 + the top line.
    assert len(polylines) == 7
    top = np.asarray(points)[polylines[-1]]
    np.testing.assert_allclose(
        top,
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.5], [2.0, 0.0, 1.0]],
        atol=1e-12,
    )


@pytest.mark.parametrize(
    "direction",
    [
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    ],
)
def test_every_axis_arrow_points_from_the_top_line_onto_the_member(
    direction: tuple[float, float, float],
) -> None:
    """The shaft runs from the top line to the base, in the load direction."""
    load_direction = np.asarray(direction)
    base = np.zeros(3)
    length = 1.0
    axis = np.array([0.0, 0.0, 1.0])
    if abs(load_direction[2]) > 0.9:
        axis = np.array([1.0, 0.0, 0.0])

    points, polylines = distributed_load_glyphs([base], [load_direction], [length], axis)

    shaft = polylines[0]
    tail = points[shaft[1]]
    shaft_direction = (base - tail) / np.linalg.norm(base - tail)
    np.testing.assert_allclose(shaft_direction, load_direction, atol=1e-12)
    assert np.dot(tail - base, load_direction) == pytest.approx(-length)

    # Both head strokes end behind the tip (the base): the V opens away from
    # the direction the arrow points.
    for head_line in polylines[1:3]:
        head = points[head_line[1]]
        assert np.dot(head - base, load_direction) < 0.0
        perpendicular = head - base - load_direction * np.dot(head - base, load_direction)
        assert np.linalg.norm(perpendicular) > 0.0


def test_a_horizontal_load_on_a_vertical_column_offsets_against_x() -> None:
    """A +X wind load on a Z column puts its top line on the -X side."""
    points, polylines = distributed_load_glyphs(
        [np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])],
        [np.array([1.0, 0.0, 0.0])] * 2,
        [0.5, 0.5],
        np.array([0.0, 0.0, 1.0]),
    )
    top = np.asarray(points)[polylines[-1]]
    np.testing.assert_allclose(
        top,
        [[-0.5, 0.0, 0.0], [-0.5, 0.0, 1.0]],
        atol=1e-12,
    )


def test_arrowheads_stay_finite_when_the_load_runs_along_the_member() -> None:
    points, polylines = distributed_load_glyphs(
        [np.array([0.0, 0.0, 0.0])],
        [np.array([1.0, 0.0, 0.0])],
        [0.5],
        np.array([1.0, 0.0, 0.0]),
    )
    assert points.size > 0
    assert np.isfinite(points).all()
    assert len(polylines) == 3  # shaft + two head strokes
