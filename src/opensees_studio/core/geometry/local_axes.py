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

from collections.abc import Sequence

import numpy as np

Vector3 = tuple[float, float, float]


def frame_vecxz(p_i: Sequence[float], p_j: Sequence[float]) -> Vector3:
    """The ``vecxz`` the runner gives a 3D frame element.

    A member closer to global Z than to global X (a column) gets ``(1, 0, 0)``;
    anything else (a beam, a sloped brace) and a zero-length member get
    ``(0, 0, 1)``.
    """
    axis = np.asarray(p_j, dtype=float) - np.asarray(p_i, dtype=float)
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    axis /= length
    if abs(axis[2]) > abs(axis[0]):
        return (1.0, 0.0, 0.0)
    return (0.0, 0.0, 1.0)


def frame_local_axes(
    ndm: int, p_i: Sequence[float], p_j: Sequence[float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Unit local ``(x, y, z)`` in global coordinates, None for a zero-length member."""
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
    y = np.cross(np.asarray(frame_vecxz(p_i, p_j)), x)
    norm = float(np.linalg.norm(y))
    if norm < 1e-12:
        return None
    y /= norm
    return x, y, np.cross(x, y)
