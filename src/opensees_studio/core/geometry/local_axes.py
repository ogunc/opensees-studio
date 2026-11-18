"""Local axes of a frame element, as OpenSees builds them.

The runner picks the ``geomTransf`` orientation vector (``vecxz``) here, and
anything that turns a global direction into local load components (the self
weight) reads the same axes, so the two cannot drift apart.

OpenSees conventions:

* 2D: local x runs from node i to node j and local y is x turned +90° in the
  XY plane.
* 3D: ``y = vecxz × x`` and ``z = x × y`` (``vecxz`` lies in the local x-z
  plane).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

Vector3 = tuple[float, float, float]


def rotate_about_axis(vector: np.ndarray, axis: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate ``vector`` about the unit ``axis`` by ``angle_deg`` (right-hand rule)."""
    if angle_deg == 0.0:
        return vector
    angle = math.radians(angle_deg)
    c, s = math.cos(angle), math.sin(angle)
    return vector * c + np.cross(axis, vector) * s + axis * float(axis @ vector) * (1.0 - c)


def frame_vecxz(p_i: Sequence[float], p_j: Sequence[float], angle_deg: float = 0.0) -> Vector3:
    """The ``vecxz`` the runner gives a 3D frame element.

    A member closer to global Z than to global X (a column) gets ``(1, 0, 0)``;
    anything else (a beam, a sloped brace) and a zero-length member get
    ``(0, 0, 1)``. ``angle_deg`` turns that vector about the member axis
    (positive right-hand rule about local x, i to j).
    """
    axis = np.asarray(p_j, dtype=float) - np.asarray(p_i, dtype=float)
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    axis /= length
    vecxz = np.array([1.0, 0.0, 0.0]) if abs(axis[2]) > abs(axis[0]) else np.array([0.0, 0.0, 1.0])
    vecxz = rotate_about_axis(vecxz, axis, angle_deg)
    return (float(vecxz[0]), float(vecxz[1]), float(vecxz[2]))


def frame_local_axes(
    ndm: int,
    p_i: Sequence[float],
    p_j: Sequence[float],
    angle_deg: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Unit local ``(x, y, z)`` in global coordinates, None for a zero-length member.

    ``angle_deg`` rotates the local y/z axes about local x (3D). In 2D the
    plane fixes the axes; the runner refuses a non-zero angle there.
    """
    pi = np.asarray(p_i, dtype=float)
    axis = np.asarray(p_j, dtype=float) - pi
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        return None
    x = axis / length
    if ndm == 2:
        # The model is in the X-Z plane; OpenSees' local y is (-Y) x local x
        # (see core.plane), so a horizontal member's local y points up (+Z).
        y = np.array([-x[2], 0.0, x[0]])
        return x, y, np.array([0.0, -1.0, 0.0])
    y = np.cross(np.asarray(frame_vecxz(p_i, p_j, angle_deg)), x)
    norm = float(np.linalg.norm(y))
    if norm < 1e-12:
        return None
    y /= norm
    return x, y, np.cross(x, y)
