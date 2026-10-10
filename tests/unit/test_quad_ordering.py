"""``order_quad_nodes``: derive a counter-clockwise winding from four points.

A shell or quad built from a scrambled node list is inverted or twisted, and a
click selection carries no order, so the winding has to be derived from the
coordinates. These tests pin the geometry, including the figure-eight order
that made Newell's method return an all-zero normal.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from opensees_studio.core.geometry.ordering import (
    COINCIDENT_TOL,
    QuadOrderError,
    order_quad_nodes,
    quad_plane,
)

Point = tuple[float, float, float]


def _winding(points: list[Point], order: tuple[int, ...], normal: np.ndarray) -> float:
    """Signed area of the ordered polygon about ``normal`` (positive = CCW)."""
    total = 0.0
    for i in range(4):
        a = np.asarray(points[order[i]], dtype=float)
        b = np.asarray(points[order[(i + 1) % 4]], dtype=float)
        total += float(np.dot(np.cross(a, b), normal))
    return total


def _assert_valid(points: list[Point], order: tuple[int, ...]) -> None:
    assert sorted(order) == [0, 1, 2, 3], "the order must be a permutation"
    _, _, _, normal = quad_plane(points)
    assert math.isclose(float(np.linalg.norm(normal)), 1.0, rel_tol=1e-9)
    assert _winding(points, order, normal) > 0.0, "the winding must be counter-clockwise"


SQUARE: list[Point] = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
# The same four corners, described by the index of the corner they are.
TILTED: list[Point] = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 1.0, 1.0), (1.0, 2.0, 2.0)]
VERTICAL: list[Point] = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)]


# ──────────────────────────── the plane ────────────────────────────
def test_quad_plane_normal_is_unit_and_follows_right_hand_rule() -> None:
    centroid, u, v, normal = quad_plane(SQUARE)
    assert np.allclose(centroid, [0.5, 0.5, 0.0])
    assert np.allclose(normal, [0.0, 0.0, 1.0], atol=1e-9)
    assert np.allclose(np.cross(u, v), normal, atol=1e-9)


def test_quad_plane_raises_on_wrong_point_count() -> None:
    with pytest.raises(QuadOrderError, match="exactly 4 points"):
        quad_plane(SQUARE[:3])
    with pytest.raises(QuadOrderError, match="exactly 4 points"):
        quad_plane([*SQUARE, (2.0, 2.0, 0.0)])


# ──────────────────────────── the winding ────────────────────────────
@pytest.mark.parametrize("permutation", list(itertools.permutations(range(4))))
def test_every_permutation_of_a_square_yields_a_counter_clockwise_order(
    permutation: tuple[int, int, int, int],
) -> None:
    """All 24 click orders must produce the same face, up to a cyclic rotation."""
    points = [SQUARE[i] for i in permutation]
    order = order_quad_nodes(points)
    _assert_valid(points, order)
    assert np.allclose(quad_plane(points)[3], [0.0, 0.0, 1.0], atol=1e-9)


def test_scrambled_figure_eight_order_still_returns_a_plane() -> None:
    """The regression: Newell's method cancels on this order and returns zero."""
    points = [SQUARE[0], SQUARE[2], SQUARE[1], SQUARE[3]]
    order = order_quad_nodes(points)
    _assert_valid(points, order)


def test_canonical_order_when_the_square_is_given_counter_clockwise() -> None:
    order = order_quad_nodes(SQUARE)
    _assert_valid(SQUARE, order)
    # The sequence is a cyclic rotation of 0,1,2,3, whichever corner SVD starts at.
    rotated = [tuple(order[i:] + order[:i]) for i in range(4)]
    assert (0, 1, 2, 3) in rotated


def test_tilted_face_winding_follows_its_own_normal() -> None:
    for permutation in [(0, 1, 2, 3), (3, 2, 1, 0), (0, 2, 1, 3), (1, 3, 0, 2)]:
        points = [TILTED[i] for i in permutation]
        order = order_quad_nodes(points)
        _assert_valid(points, order)


def test_vertical_face_has_a_horizontal_normal() -> None:
    order = order_quad_nodes(VERTICAL)
    _assert_valid(VERTICAL, order)
    normal = quad_plane(VERTICAL)[3]
    assert math.isclose(float(normal[2]), 0.0, abs_tol=1e-9)


def test_slightly_warped_quad_is_accepted() -> None:
    """Hand-built meshes are rarely exactly planar; a small warp is not an error."""
    points: list[Point] = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.01),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
    ]
    order = order_quad_nodes(points)
    assert sorted(order) == [0, 1, 2, 3]
    assert _winding(points, order, quad_plane(points)[3]) > 0.0


def test_negative_coordinates_are_ordered_like_positive_ones() -> None:
    points = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)]
    order = order_quad_nodes(points)
    _assert_valid(points, order)


# ──────────────────────────── rejections ────────────────────────────
def test_coincident_points_are_rejected() -> None:
    points = [SQUARE[0], SQUARE[0], SQUARE[1], SQUARE[2]]
    with pytest.raises(QuadOrderError, match="coincide"):
        order_quad_nodes(points)


def test_points_closer_than_the_tolerance_count_as_coincident() -> None:
    epsilon = COINCIDENT_TOL / 10.0
    points = [(0.0, 0.0, 0.0), (epsilon, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    with pytest.raises(QuadOrderError, match="coincide"):
        order_quad_nodes(points)


def test_three_collinear_points_with_a_fourth_off_the_line_are_rejected() -> None:
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 1e-14, 0.0)]
    with pytest.raises(QuadOrderError, match="collinear"):
        order_quad_nodes(points)


def test_a_point_inside_the_triangle_of_the_others_is_rejected() -> None:
    points = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.25, 0.25, 0.0)]
    with pytest.raises(QuadOrderError, match="inside the triangle"):
        order_quad_nodes(points)


def test_quad_order_error_is_a_value_error() -> None:
    assert issubclass(QuadOrderError, ValueError)
