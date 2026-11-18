"""Quadrature on a bilinear quadrilateral, with no model imports.

The shell self weight, the area loads and the area/edge springs all need the
same ``∫N_i dA`` of a possibly warped four-node quad. Keeping it here lets those
modules share it without importing ``core.project`` (and closing an import
cycle).
"""

from __future__ import annotations

import numpy as np

_GAUSS = (-1.0 / np.sqrt(3.0), 1.0 / np.sqrt(3.0))
_CORNERS = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))


def quad_tributary_areas(points: np.ndarray) -> np.ndarray:
    """``integral(N_i dA)`` for the four corners of a bilinear quad (4 x 3 points).

    The four values add up to the quad's area, also when it is warped.
    """
    shares = np.zeros(4)
    for xi in _GAUSS:
        for eta in _GAUSS:
            n = np.array([0.25 * (1 + a * xi) * (1 + b * eta) for a, b in _CORNERS])
            dn_dxi = np.array([0.25 * a * (1 + b * eta) for a, b in _CORNERS])
            dn_deta = np.array([0.25 * b * (1 + a * xi) for a, b in _CORNERS])
            jacobian = float(np.linalg.norm(np.cross(dn_dxi @ points, dn_deta @ points)))
            shares += n * jacobian  # Gauss weights are 1
    return shares


def triangle_area(points: np.ndarray) -> float:
    """Area of a flat triangle (3 x 3 points)."""
    return 0.5 * float(np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0])))


def face_tributary_areas(points: np.ndarray) -> np.ndarray:
    """``integral(N_i dA)`` of a shell face: a third each for a triangle, else the quad's."""
    if len(points) == 3:
        return np.full(3, triangle_area(points) / 3.0)
    return quad_tributary_areas(points)
