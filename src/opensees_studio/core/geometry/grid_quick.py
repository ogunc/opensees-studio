"""Quick draw on the grid: the grid segment or the grid bay under a point.

SAP2000 draws a regular frame by clicking grid lines, not their crossings:
a click on a grid line between two crossings is the member between them, a
click inside a bay is the panel it bounds. These functions find that segment
or that bay on the working plane from the point where a click met it.

Only grid systems without rotation are used (their origin is added), and
only visible lines; a point outside the grid has no segment or bay.

No Qt.
"""

from __future__ import annotations

import bisect
from typing import Any

Point = tuple[float, float, float]

#: For each working plane: (first in-plane axis, second in-plane axis, normal axis).
PLANE_AXES = {"XY": (0, 1, 2), "XZ": (0, 2, 1), "YZ": (1, 2, 0)}


def grid_ordinates(project: Any) -> tuple[list[float], list[float], list[float]]:
    """Sorted, de-duplicated X, Y and Z ordinates of the visible grid lines."""
    axes: tuple[set[float], set[float], set[float]] = (set(), set(), set())
    for system in getattr(project, "coord_systems", []):
        coord = getattr(system, "coord", None)
        if coord is not None and any(abs(a) > 1e-12 for a in coord.rotation_deg):
            continue  # a rotated system's lines are not axis-aligned here
        origin = coord.origin if coord is not None else (0.0, 0.0, 0.0)
        grid = system.grid
        if not grid.shown or grid.is_cylindrical:
            continue
        for axis, values in enumerate(grid.visible_ordinates()):
            axes[axis].update(round(float(v) + float(origin[axis]), 9) for v in values)
    return sorted(axes[0]), sorted(axes[1]), sorted(axes[2])


def _span(values: list[float], x: float) -> tuple[float, float] | None:
    """The two consecutive values around ``x``, or None outside the range."""
    if len(values) < 2 or x < values[0] or x > values[-1]:
        return None
    i = min(bisect.bisect_right(values, x), len(values) - 1)
    return values[i - 1], values[i]


def _point(plane: str, offset: float, u: float, v: float) -> Point:
    a, b, n = PLANE_AXES[plane]
    out = [0.0, 0.0, 0.0]
    out[a], out[b], out[n] = u, v, offset
    return (out[0], out[1], out[2])


def grid_segment(
    project: Any, plane: str, offset: float, point: Point, *, tolerance: float
) -> tuple[Point, Point] | None:
    """The grid segment nearest ``point`` (within ``tolerance``) between two crossings."""
    ordinates = grid_ordinates(project)
    a, b, _ = PLANE_AXES[plane]
    us, vs = ordinates[a], ordinates[b]
    pu, pv = point[a], point[b]
    best: tuple[float, tuple[Point, Point]] | None = None
    # Along a line u = const, the segment spans two consecutive v's, and the other way round.
    for line_u in us:
        span = _span(vs, pv)
        if span is not None and abs(pu - line_u) <= tolerance:
            seg = (_point(plane, offset, line_u, span[0]), _point(plane, offset, line_u, span[1]))
            if best is None or abs(pu - line_u) < best[0]:
                best = (abs(pu - line_u), seg)
    for line_v in vs:
        span = _span(us, pu)
        if span is not None and abs(pv - line_v) <= tolerance:
            seg = (_point(plane, offset, span[0], line_v), _point(plane, offset, span[1], line_v))
            if best is None or abs(pv - line_v) < best[0]:
                best = (abs(pv - line_v), seg)
    return None if best is None else best[1]


def grid_bay(project: Any, plane: str, offset: float, point: Point) -> list[Point] | None:
    """The four corners of the grid bay containing ``point``, counter-clockwise in plane."""
    ordinates = grid_ordinates(project)
    a, b, _ = PLANE_AXES[plane]
    span_u = _span(ordinates[a], point[a])
    span_v = _span(ordinates[b], point[b])
    if span_u is None or span_v is None:
        return None
    (u0, u1), (v0, v1) = span_u, span_v
    return [
        _point(plane, offset, u0, v0),
        _point(plane, offset, u1, v0),
        _point(plane, offset, u1, v1),
        _point(plane, offset, u0, v1),
    ]
