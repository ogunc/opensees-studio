"""Compute the axis-aligned bounding box of a cross-section.

The bbox is used by the 3D canvas to draw an "extruded" view of a
frame element — a rectangular box the size of the section swept
along the element axis (SAP2000's Display → Show Extruded View
feature). Only width_y and height_z are returned because bar-like
elements don't have a bounding 'length' in local-x.

- :class:`ElasticSection`: assumes a rectangular cross-section and
  back-solves b, h from A and Iz (``Iz = b·h³/12``).
- :class:`FiberSection`: unions the patches' and layers' extents.
- :class:`SectionAggregator`: delegates to its base section.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opensees_studio.core import Project


def bbox_for_section(section: object, project: "Project | None" = None,
                     ) -> tuple[float, float] | None:
    """Return ``(width_y, height_z)`` of the section's local bounding box.

    ``None`` means "size could not be inferred" — the caller should skip
    drawing this section rather than guessing.
    """
    from opensees_studio.core import (
        CircularPatch,
        ElasticSection,
        FiberSection,
        RectangularPatch,
        SectionAggregator,
        StraightLayer,
    )
    # ── ElasticSection: assume rectangular, back-solve b·h from A, Iz.
    if isinstance(section, ElasticSection):
        if section.A <= 0 or section.Iz <= 0:
            return None
        # Iz = b·h³/12 and A = b·h → h = sqrt(12·Iz/A), b = A/h.
        try:
            h = math.sqrt(12.0 * section.Iz / section.A)
            b = section.A / h
        except (ValueError, ZeroDivisionError):
            return None
        return (b, h)

    # ── FiberSection: collect the union of every patch / layer extent.
    if isinstance(section, FiberSection):
        ys: list[float] = []
        zs: list[float] = []
        for p in section.patches:
            if isinstance(p, RectangularPatch):
                ys.extend([p.y_i, p.y_j])
                zs.extend([p.z_i, p.z_j])
            elif isinstance(p, CircularPatch):
                ys.extend([p.y_center - p.r_outer, p.y_center + p.r_outer])
                zs.extend([p.z_center - p.r_outer, p.z_center + p.r_outer])
        for lay in section.layers:
            if isinstance(lay, StraightLayer):
                ys.extend([lay.y_start, lay.y_end])
                zs.extend([lay.z_start, lay.z_end])
        for fb in section.fibres:
            ys.append(fb.y)
            zs.append(fb.z)
        if not ys or not zs:
            return None
        return (max(ys) - min(ys), max(zs) - min(zs))

    # ── SectionAggregator: transparent — use the wrapped section's bbox.
    if isinstance(section, SectionAggregator) and project is not None:
        if section.section_id is not None:
            try:
                base = project.section(section.section_id)
            except KeyError:
                return None
            return bbox_for_section(base, project)

    return None
