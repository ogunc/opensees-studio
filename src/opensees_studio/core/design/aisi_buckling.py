"""Hand formulas for the local buckling of a cold-formed section: a check on the finite strips.

The finite strip method (:mod:`core.design.fsm`) is the rational analysis the
Direct Strength Method uses. These closed forms are its independent check, and
a fallback when a signature curve has no clear local minimum:

* :func:`plate_buckling_stress` — the elastic buckling stress of a long flat
  plate, ``k π² E / (12 (1 - ν²)) (t / w)²``.
* :func:`element_local_buckling` — the "element model" of the section in
  compression: every flat buckles on its own, the interior flats as plates
  supported on both long edges (``k = 4``) and the two end flats (a lip, the
  free flange of a track, an angle's leg) as plates with one free edge
  (``k = 0.43``). The lowest element stress times the gross area estimates
  ``Pcrl``. It ignores the rotational restraint the flats give each other, so
  it is usually below the finite strip result.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from opensees_studio.core.sections.cold_formed import (
    ColdFormedShape,
    corner_points,
    properties,
)

#: Plate buckling coefficient of a flat supported along both long edges.
K_STIFFENED = 4.0
#: Plate buckling coefficient of a flat with one long edge free.
K_UNSTIFFENED = 0.43


def plate_buckling_stress(k: float, elastic_modulus: float, nu: float, t: float, w: float) -> float:
    """Elastic buckling stress of a long plate of width ``w`` and thickness ``t``."""
    return k * math.pi**2 * elastic_modulus / (12.0 * (1.0 - nu**2)) * (t / w) ** 2


def flat_widths(shape: ColdFormedShape) -> list[float]:
    """The flat width of each straight element, end to end along the midline.

    A sharp corner of the midline is replaced by an arc of radius ``r + t/2``; the
    flat stops where that arc starts, ``(r + t/2) tan(φ/2)`` from the corner, φ
    being the angle the midline turns through.
    """
    pts = np.asarray(corner_points(shape), dtype=float)
    radius = shape.r + shape.t / 2.0 if shape.r > 0.0 else 0.0
    back = [0.0]
    for k in range(1, len(pts) - 1):
        u = pts[k] - pts[k - 1]
        v = pts[k + 1] - pts[k]
        cos_turn = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))
        turn = math.acos(max(-1.0, min(1.0, cos_turn)))
        back.append(radius * math.tan(turn / 2.0))
    back.append(0.0)
    lengths = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    return [float(lengths[k] - back[k] - back[k + 1]) for k in range(len(lengths))]


@dataclass(frozen=True)
class ElementBuckling:
    """The element model of a section in compression."""

    widths: tuple[float, ...]
    k: tuple[float, ...]
    stresses: tuple[float, ...]
    governing: int
    """Index of the flat with the lowest buckling stress."""
    pcr: float
    """``A × min(stress)``."""


def element_local_buckling(
    shape: ColdFormedShape, elastic_modulus: float, nu: float = 0.3
) -> ElementBuckling:
    """Local buckling load of ``shape`` in compression by the element model."""
    widths = flat_widths(shape)
    ks = [K_UNSTIFFENED if k in (0, len(widths) - 1) else K_STIFFENED for k in range(len(widths))]
    stresses = [
        plate_buckling_stress(k, elastic_modulus, nu, shape.t, w)
        for k, w in zip(ks, widths, strict=True)
    ]
    governing = int(np.argmin(stresses))
    return ElementBuckling(
        widths=tuple(widths),
        k=tuple(ks),
        stresses=tuple(stresses),
        governing=governing,
        pcr=properties(shape).A * stresses[governing],
    )


__all__ = [
    "K_STIFFENED",
    "K_UNSTIFFENED",
    "ElementBuckling",
    "element_local_buckling",
    "flat_widths",
    "plate_buckling_stress",
]
