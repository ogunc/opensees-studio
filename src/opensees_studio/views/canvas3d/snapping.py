"""Object snaps on frame members.

The canvas projects the rendered members to screen space and asks this
module for the snap point nearest the pointer. Three modes are supported:

``MIDPOINT``
    the middle of a member;
``PERPENDICULAR``
    the foot of the perpendicular from the current drawing point to a
    member (only meaningful once a first point exists);
``ON_ELEMENT``
    the point of the member nearest the pointer.

The maths is kept free of Qt and VTK so the rules can be tested without a
viewport; :class:`~opensees_studio.views.canvas3d.model_canvas.ModelCanvas`
supplies the projected coordinates.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


class SnapMode(enum.Enum):
    """A kind of object snap offered on a frame member."""

    MIDPOINT = "midpoint"
    PERPENDICULAR = "perpendicular"
    ON_ELEMENT = "on_element"


@dataclass(frozen=True)
class FrameSnap:
    """A snap target found on one member."""

    element_id: int
    mode: SnapMode
    point: tuple[float, float, float]
    distance_px: float


#: When two modes land on the same point, the more specific one wins.
_MODE_PRIORITY = {
    SnapMode.MIDPOINT: 0,
    SnapMode.PERPENDICULAR: 1,
    SnapMode.ON_ELEMENT: 2,
}

_EPS = 1e-12


def _nearest_on_segment(
    a_world: np.ndarray,
    b_world: np.ndarray,
    a_screen: np.ndarray,
    b_screen: np.ndarray,
    cursor: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Closest point on one member: world and screen coordinates."""
    ab_screen = b_screen - a_screen
    denominator = float(np.dot(ab_screen, ab_screen))
    if denominator <= _EPS:
        return a_world, a_screen
    t = float(np.dot(cursor - a_screen, ab_screen) / denominator)
    t = min(max(t, 0.0), 1.0)
    return a_world + t * (b_world - a_world), a_screen + t * ab_screen


def _perpendicular_foot(
    a_world: np.ndarray,
    b_world: np.ndarray,
    a_screen: np.ndarray,
    b_screen: np.ndarray,
    reference: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Foot of the perpendicular from ``reference``, when it lies on the member."""
    direction = b_world - a_world
    denominator = float(np.dot(direction, direction))
    if denominator <= _EPS:
        return None
    reference_world = np.asarray(reference, dtype=float)
    t = float(np.dot(reference_world - a_world, direction) / denominator)
    if t < -1e-9 or t > 1.0 + 1e-9:
        return None
    t = min(max(t, 0.0), 1.0)
    return a_world + t * direction, a_screen + t * (b_screen - a_screen)


def frame_snap_candidates(
    element_ids: Sequence[int],
    a_world: np.ndarray,
    b_world: np.ndarray,
    a_screen: np.ndarray,
    b_screen: np.ndarray,
    cursor: tuple[float, float],
    modes: Iterable[SnapMode],
    reference: tuple[float, float, float] | None,
    tolerance_px: float,
) -> FrameSnap | None:
    """Return the best enabled snap within ``tolerance_px`` of ``cursor``.

    All arrays are indexed per member: ``a_*`` and ``b_*`` are its two ends
    (world ``N x 3``, screen ``N x 2``). ``cursor`` is in the same screen
    pixels as ``a_screen``/``b_screen``. ``reference`` is the world point
    the perpendicular is measured from (the first point of a draw gesture),
    or ``None`` when no gesture has started.
    """
    active = set(modes)
    if not active or not len(element_ids):
        return None
    if not (len(a_world) == len(b_world) == len(a_screen) == len(b_screen) == len(element_ids)):
        raise ValueError("Frame snap arrays must have one row per element.")

    cursor_array = np.asarray(cursor, dtype=float)
    best: FrameSnap | None = None
    best_key: tuple[float, int] | None = None

    def consider(
        element_id: int, mode: SnapMode, point_world: np.ndarray, point_screen: np.ndarray
    ) -> None:
        nonlocal best, best_key
        distance = float(np.linalg.norm(cursor_array - point_screen))
        if distance > tolerance_px:
            return
        key = (distance, _MODE_PRIORITY[mode])
        if best_key is None or key < best_key:
            best_key = key
            best = FrameSnap(
                element_id=element_id,
                mode=mode,
                point=(float(point_world[0]), float(point_world[1]), float(point_world[2])),
                distance_px=distance,
            )

    for index, element_id in enumerate(element_ids):
        a_w = a_world[index]
        b_w = b_world[index]
        a_s = a_screen[index]
        b_s = b_screen[index]

        if SnapMode.MIDPOINT in active:
            consider(element_id, SnapMode.MIDPOINT, (a_w + b_w) * 0.5, (a_s + b_s) * 0.5)

        if SnapMode.PERPENDICULAR in active and reference is not None:
            foot = _perpendicular_foot(a_w, b_w, a_s, b_s, reference)
            if foot is not None:
                consider(element_id, SnapMode.PERPENDICULAR, foot[0], foot[1])

        if SnapMode.ON_ELEMENT in active:
            world_point, screen_point = _nearest_on_segment(a_w, b_w, a_s, b_s, cursor_array)
            consider(element_id, SnapMode.ON_ELEMENT, world_point, screen_point)

    return best
