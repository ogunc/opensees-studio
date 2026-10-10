"""Put four selected nodes into the order a quadrilateral element needs.

A user clicks four nodes in whatever order they like; OpenSees wants them
counter-clockwise around the element's positive normal, and a shell or a quad
built from a scrambled list is either inverted or twisted. Since the selection
carries no order, the application has to derive one, and this is where.

The plane comes from the best-fit plane of the four points (the singular
vector of the smallest singular value), **not** from Newell's method: Newell
needs the vertices in perimeter order, and a scrambled list can be a
figure-eight whose signed areas cancel to a zero normal. Sorting four square
corners that way really does produce an all-zero normal, which is how this was
found.

The in-plane basis is the other two singular vectors, so mild warping — real
hand-built meshes are rarely exactly planar — is handled without complaining,
and the winding is then chosen counter-clockwise as seen from a normal that
points up when the face is horizontal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

Point3 = tuple[float, float, float]

#: Two points closer than this are the same point (project units).
COINCIDENT_TOL = 1e-12


class QuadOrderError(ValueError):
    """The four points cannot form a quadrilateral element."""


def quad_plane(points: Sequence[Point3]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(centroid, u, v, normal)`` for the best-fit plane of ``points``.

    Raises:
        QuadOrderError: if the points are coincident or collinear, so no plane
            (and therefore no winding) exists.
    """
    if len(points) != 4:
        raise QuadOrderError(f"A quadrilateral needs exactly 4 points, got {len(points)}.")
    array = np.asarray(points, dtype=float)
    if array.shape != (4, 3):
        raise QuadOrderError("Each point needs three coordinates.")

    # Two identical points still span a plane, so the singular values cannot
    # see them: check the distances directly.
    for i in range(4):
        for j in range(i + 1, 4):
            if float(np.linalg.norm(array[i] - array[j])) <= COINCIDENT_TOL:
                raise QuadOrderError("Two of the four points coincide.")

    centroid = array.mean(axis=0)
    centered = array - centroid
    # The singular values are the extents along the principal directions: two
    # of them span the plane, the third is the out-of-plane thickness.
    _, singular, vt = np.linalg.svd(centered)
    if singular[0] <= COINCIDENT_TOL:
        raise QuadOrderError("The four points coincide.")
    if singular[1] <= 1e-9 * singular[0]:
        raise QuadOrderError("The four points are collinear; they cannot form a face.")

    u, v = vt[0], vt[1]
    normal = np.cross(u, v)
    # Canonical winding: the face's normal points up when the face is horizontal.
    if normal[2] < 0.0:
        u, normal = -u, -normal
    return centroid, u, v, normal


def order_quad_nodes(points: Sequence[Point3]) -> tuple[int, int, int, int]:
    """Return the indices of ``points`` counter-clockwise about their normal.

    Args:
        points: Exactly four distinct points, in any order.

    Returns:
        The four indices into ``points``, counter-clockwise as seen from the
        normal's tip (right-hand rule), with the normal pointing up when the
        face is horizontal.

    Raises:
        QuadOrderError: if the points coincide, are collinear, or one of them
            lies inside the triangle of the other three (which is not a
            quadrilateral).
    """
    centroid, u, v, _ = quad_plane(points)
    local = [
        ((point - centroid) @ u, (point - centroid) @ v) for point in np.asarray(points, float)
    ]

    for skipped in range(4):
        triangle = [local[i] for i in range(4) if i != skipped]
        if _point_in_triangle(local[skipped], triangle):
            raise QuadOrderError(
                "One of the four points lies inside the triangle of the other three, "
                "so they do not form a quadrilateral."
            )

    order = tuple(
        index
        for _, index in sorted(
            (math.atan2(local[index][1], local[index][0]), index) for index in range(4)
        )
    )
    return order  # type: ignore[return-value]


def _point_in_triangle(point: tuple[float, float], triangle: list[tuple[float, float]]) -> bool:
    """True when ``point`` is strictly inside ``triangle`` (2D, any winding)."""
    signs = []
    for i in range(3):
        ax, ay = triangle[i]
        bx, by = triangle[(i + 1) % 3]
        cross = (bx - ax) * (point[1] - ay) - (by - ay) * (point[0] - ax)
        if abs(cross) <= 1e-12:
            return False  # on an edge, not strictly inside
        signs.append(cross > 0.0)
    return all(signs) or not any(signs)
