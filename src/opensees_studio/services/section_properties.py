"""Compute aggregate cross-section properties from a FiberSection.

Given a FiberSection with patches, layers, and individual fibres, this
module expands all geometry into a flat list of (y, z, area) fibres and
computes:
- Total area A
- Centroid (ȳ, z̄)
- Second moments of area Iy, Iz (about the centroid)

The expansion uses the same subdivision that OpenSees would apply
internally, so the results are exact (within the fibre approximation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from opensees_studio.core.sections import (
    CircularPatch,
    FiberSection,
    Fibre,
    RectangularPatch,
    StraightLayer,
)


@dataclass
class SectionProps:
    """Aggregate properties of a fibre section."""

    n_fibres: int
    area: float
    centroid_y: float
    centroid_z: float
    Iy: float           # about centroid
    Iz: float           # about centroid
    fibre_yz: np.ndarray   # (n, 3): y, z, area


def expand_fibres(sec: FiberSection) -> np.ndarray:
    """Expand patches + layers + explicit fibres into an (N, 3) array
    of [y, z, area] rows."""
    rows: list[tuple[float, float, float]] = []

    for p in sec.patches:
        if isinstance(p, RectangularPatch):
            dy = (p.y_j - p.y_i) / p.n_fib_y
            dz = (p.z_j - p.z_i) / p.n_fib_z
            a = abs(dy * dz)
            for iy in range(p.n_fib_y):
                yc = p.y_i + (iy + 0.5) * dy
                for iz in range(p.n_fib_z):
                    zc = p.z_i + (iz + 0.5) * dz
                    rows.append((yc, zc, a))
        elif isinstance(p, CircularPatch):
            d_theta = (p.end_angle - p.start_angle) / p.n_fib_circ
            d_r = (p.r_outer - p.r_inner) / p.n_fib_rad
            for ir in range(p.n_fib_rad):
                r_mid = p.r_inner + (ir + 0.5) * d_r
                for ic in range(p.n_fib_circ):
                    theta = math.radians(p.start_angle + (ic + 0.5) * d_theta)
                    yc = p.y_center + r_mid * math.cos(theta)
                    zc = p.z_center + r_mid * math.sin(theta)
                    # Annular sector area: (r_outer² - r_inner²) * dθ / (2·n_rad)
                    a = ((p.r_inner + (ir + 1) * d_r) ** 2
                         - (p.r_inner + ir * d_r) ** 2) \
                        * math.radians(d_theta) / 2.0
                    rows.append((yc, zc, a))

    for lay in sec.layers:
        if isinstance(lay, StraightLayer):
            for i in range(lay.n_bars):
                t = i / max(1, lay.n_bars - 1) if lay.n_bars > 1 else 0.5
                yc = lay.y_start + t * (lay.y_end - lay.y_start)
                zc = lay.z_start + t * (lay.z_end - lay.z_start)
                rows.append((yc, zc, lay.bar_area))

    for fb in sec.fibres:
        rows.append((fb.y, fb.z, fb.area))

    if not rows:
        return np.empty((0, 3), dtype=float)
    return np.asarray(rows, dtype=float)


def compute_section_props(sec: FiberSection) -> SectionProps:
    """Compute aggregate section properties from a FiberSection."""
    fibres = expand_fibres(sec)
    if fibres.size == 0:
        return SectionProps(0, 0.0, 0.0, 0.0, 0.0, 0.0, fibres)

    y, z, a = fibres[:, 0], fibres[:, 1], fibres[:, 2]
    total_a = float(np.sum(a))
    if total_a <= 0.0:
        return SectionProps(len(fibres), 0.0, 0.0, 0.0, 0.0, 0.0, fibres)

    # Centroid.
    yc = float(np.sum(a * y) / total_a)
    zc = float(np.sum(a * z) / total_a)

    # Second moments of area about centroid (parallel axis from each fibre).
    Iz = float(np.sum(a * (y - yc) ** 2))    # about z-axis
    Iy = float(np.sum(a * (z - zc) ** 2))    # about y-axis

    return SectionProps(
        n_fibres=len(fibres),
        area=total_a,
        centroid_y=yc,
        centroid_z=zc,
        Iy=Iy,
        Iz=Iz,
        fibre_yz=fibres,
    )
