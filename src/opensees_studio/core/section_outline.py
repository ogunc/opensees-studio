"""The cross section of a frame member as drawn: regions in its local ``(y, z)``.

View → Show Extruded Sections sweeps these outlines along each member. The
coordinates are the solver's local axes (``core.geometry.local_axes``), so what
is drawn is what OpenSees bends:

* A shape hint (pipe, angle, rectangle, I, channel, tee, rectangular tube)
  gives the true profile, about its centroid. A hint stands with its depth
  along local z in a 3D model (``core.aisc.shape_to_elastic_section`` swaps Iz
  and Iy there) and along local y in a 2D one, as ``core.frame_members`` reads it.
* A fibre section draws its rectangular and circular patches as they are.
* Anything else whose size is known (an elastic section without a hint, a
  fibre section of single fibres, a beam with hinges, an aggregator's base
  section) draws the rectangle of :func:`core.frame_members.member_extents`.
* A truss with only an area draws the round bar of that area.

No Qt.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from opensees_studio.core.frame_members import SectionExtents, member_extents
from opensees_studio.core.sections import (
    AngleShape,
    ChannelShape,
    CircularPatch,
    ElasticSection,
    FiberSection,
    PipeShape,
    RectangularPatch,
    RectShape,
    SectionAggregator,
    SectionShape,
    TeeShape,
    TubeShape,
    WideFlangeShape,
)
from opensees_studio.core.sections.drawing import profile_outline
from opensees_studio.core.sections.geometry import (
    CircleRegion,
    Point,
    PolygonRegion,
    Region,
    rectangle,
    section_properties,
)

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

#: Segments of a full circle in a circular patch's arc.
ARC_SEGMENTS = 48


def hint_regions(shape: SectionShape, ndm: int) -> list[Region]:
    """The profile of a shape hint about its centroid, in local ``(y, z)``."""
    regions: list[Region]
    if isinstance(shape, PipeShape):
        r = shape.od / 2.0
        regions = [CircleRegion(0.0, 0.0, r)]
        if shape.t < r:
            regions.append(CircleRegion(0.0, 0.0, r - shape.t, hole=True))
    elif isinstance(shape, RectShape):
        regions = [rectangle(shape.b, shape.d)]
    elif isinstance(shape, TubeShape):
        regions = [rectangle(shape.b, shape.d)]
        if 2.0 * shape.t < min(shape.b, shape.d):
            regions.append(rectangle(shape.b - 2 * shape.t, shape.d - 2 * shape.t, hole=True))
    elif isinstance(shape, AngleShape):
        d, b, t = shape.d, shape.b, min(shape.t, 0.999 * min(shape.d, shape.b))
        regions = [PolygonRegion(((0.0, 0.0), (0.0, b), (t, b), (t, t), (d, t), (d, 0.0)))]
    else:
        kind = {WideFlangeShape: "ishape", ChannelShape: "channel", TeeShape: "tee"}[type(shape)]
        regions = [
            PolygonRegion(tuple(profile_outline(kind, shape.d, shape.bf, shape.tf, shape.tw)))
        ]
    props = section_properties(regions, plastic=False)
    regions = [_transformed(r, -props.y_c, -props.z_c, turn=False) for r in regions]
    if ndm == 3:
        regions = [_transformed(r, 0.0, 0.0, turn=True) for r in regions]
    return regions


def _transformed(region: Region, dy: float, dz: float, *, turn: bool) -> Region:
    """``region`` moved by ``(dy, dz)``; ``turn`` then rotates it +90° (the depth y onto z)."""

    def at(y: float, z: float) -> Point:
        y, z = y + dy, z + dz
        return (-z, y) if turn else (y, z)

    if isinstance(region, CircleRegion):
        y, z = at(region.y, region.z)
        return CircleRegion(y, z, region.radius, region.hole)
    return PolygonRegion(tuple(at(y, z) for y, z in region.points), region.hole)


def patch_regions(section: FiberSection) -> list[Region]:
    """The rectangular and circular patches of a fibre section, as regions."""
    regions: list[Region] = []
    for patch in section.patches:
        if isinstance(patch, RectangularPatch):
            y0, y1 = sorted((patch.y_i, patch.y_j))
            z0, z1 = sorted((patch.z_i, patch.z_j))
            if y1 > y0 and z1 > z0:
                regions.append(rectangle(z1 - z0, y1 - y0, (y0 + y1) / 2.0, (z0 + z1) / 2.0))
        elif isinstance(patch, CircularPatch):
            regions += _circular_patch(patch)
    return regions


def _circular_patch(patch: CircularPatch) -> list[Region]:
    yc, zc, r_in, r_out = patch.y_center, patch.z_center, patch.r_inner, patch.r_outer
    sweep = patch.end_angle - patch.start_angle
    if abs(sweep) >= 360.0 - 1e-9:
        rings: list[Region] = [CircleRegion(yc, zc, r_out)]
        if r_in > 0.0:
            rings.append(CircleRegion(yc, zc, r_in, hole=True))
        return rings
    steps = max(2, math.ceil(ARC_SEGMENTS * abs(sweep) / 360.0))
    angles = [math.radians(patch.start_angle + sweep * k / steps) for k in range(steps + 1)]
    outer = [(yc + r_out * math.cos(a), zc + r_out * math.sin(a)) for a in angles]
    if r_in > 0.0:
        inner = [(yc + r_in * math.cos(a), zc + r_in * math.sin(a)) for a in reversed(angles)]
    else:
        inner = [(yc, zc)]
    return [PolygonRegion(tuple(outer + inner))]


def _box(extents: SectionExtents) -> list[Region]:
    height = extents.y_max - extents.y_min
    width = extents.z_max - extents.z_min
    if height <= 0.0 or width <= 0.0:
        return []
    y = (extents.y_min + extents.y_max) / 2.0
    z = (extents.z_min + extents.z_max) / 2.0
    return [rectangle(width, height, y, z)]


def member_regions(project: Project, element: Any) -> list[Region]:
    """The cross section of frame member ``element`` in its local ``(y, z)``; [] if unknown."""
    section_id = getattr(element, "section_id", None)
    section = next((s for s in project.sections if s.id == section_id), None)
    seen: set[int] = set()
    while isinstance(section, SectionAggregator) and section.id not in seen:
        seen.add(section.id)
        section = next((s for s in project.sections if s.id == section.section_id), None)
    if isinstance(section, ElasticSection) and section.shape is not None:
        return hint_regions(section.shape, project.ndm)
    if isinstance(section, FiberSection):
        patches = patch_regions(section)
        if patches:
            return patches
    extents = member_extents(project, element)
    if extents is not None:
        return _box(extents)
    area = getattr(element, "area", None)
    if isinstance(area, (int, float)) and area > 0.0:
        # A truss: the round bar of its area.
        return [CircleRegion(0.0, 0.0, math.sqrt(area / math.pi))]
    return []
