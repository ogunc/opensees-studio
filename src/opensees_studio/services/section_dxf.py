"""Read a cross-section drawn in a DXF file (Section Designer → Import DXF).

The drawing's closed outlines become the section's regions: closed
``LWPOLYLINE`` / ``POLYLINE`` (arcs from bulges included), ``CIRCLE``, closed
``ELLIPSE`` and ``SPLINE``. Curved edges are flattened to straight segments no
farther than a small fraction of the drawing's size from the true curve; a
circle stays an exact circle. Which outline is a hole is read from nesting: an
outline inside an odd number of others is a hole (the inside of a tube, the
cores of a hollow slab).

The drawing's x runs along the section's local **z** and its y along local
**y**, so the section reads as drawn. Lines, open polylines, text and the rest
are counted and reported, never guessed into outlines. Units come from
``$INSUNITS`` as for the bar import (:mod:`services.dxf_import`).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ezdxf import path as dxf_path
from ezdxf.filemanagement import readfile

from opensees_studio.core.sections.geometry import (
    CircleRegion,
    PolygonRegion,
    Region,
    outline,
)
from opensees_studio.core.units import UnitSystem, metres_per_unit
from opensees_studio.services.dxf_import import (
    _DXF_UNIT_NAMES,
    _DXF_UNITS_IN_METRES,
    DxfImportError,
)

#: Largest distance of a flattened curve from the true one, over the drawing's size.
FLATTENING = 1e-4

_CLOSED_KINDS = {"LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE"}


@dataclass
class SectionDrawing:
    """The outlines a file holds, in its own units and coordinates."""

    regions: list[Region]
    layers: list[str]
    insunits: int
    unit_name: str
    unit_in_metres: float | None
    skipped: dict[str, int] = field(default_factory=dict)
    open_outlines: int = 0

    def summary(self) -> str:
        holes = sum(1 for r in self.regions if r.hole)
        text = f"{len(self.regions) - holes} outline(s) and {holes} hole(s), in {self.unit_name}"
        if self.open_outlines:
            text += f"; {self.open_outlines} open polyline(s) left out"
        if self.skipped:
            other = ", ".join(f"{n} {kind}" for kind, n in sorted(self.skipped.items()))
            text += f"; skipped {other}"
        return text + "."


def _points(entity: Any, tolerance: float) -> list[tuple[float, float]]:
    """Flattened vertices of a closed curve, as section (y, z) = drawing (y, x)."""
    vertices = list(dxf_path.make_path(entity).flattening(tolerance))
    if len(vertices) > 1 and vertices[0].isclose(vertices[-1]):
        vertices = vertices[:-1]
    return [(float(v.y), float(v.x)) for v in vertices]


def _is_closed(entity: Any, kind: str) -> bool:
    if kind == "LWPOLYLINE":
        return bool(entity.closed) or _ends_meet(list(entity.get_points("xy")))
    if kind == "POLYLINE":
        points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        return bool(entity.is_closed) or _ends_meet(points)
    if kind == "ELLIPSE":
        return math.isclose(abs(entity.dxf.end_param - entity.dxf.start_param), 2 * math.pi)
    if kind == "SPLINE":
        return bool(entity.closed)
    return True


def _ends_meet(points: list[Any]) -> bool:
    return (
        len(points) > 2
        and math.isclose(points[0][0], points[-1][0])
        and math.isclose(points[0][1], points[-1][1])
    )


def _extent(entities: list[Any]) -> float:
    """A size of the drawing, for the flattening tolerance."""
    xs: list[float] = []
    ys: list[float] = []
    for entity in entities:
        try:
            box = dxf_path.bbox([dxf_path.make_path(entity)])
        except Exception:
            continue
        if box.has_data:
            xs += [box.extmin.x, box.extmax.x]
            ys += [box.extmin.y, box.extmax.y]
    if not xs:
        return 1.0
    return max(max(xs) - min(xs), max(ys) - min(ys), 1e-12)


def _inside(point: tuple[float, float], region: Region) -> bool:
    y, z = point
    if isinstance(region, CircleRegion):
        return (y - region.y) ** 2 + (z - region.z) ** 2 < region.radius**2
    inside = False
    points = region.points
    for k in range(len(points)):
        y1, z1 = points[k]
        y2, z2 = points[(k + 1) % len(points)]
        if (z1 > z) != (z2 > z) and y < y1 + (z - z1) * (y2 - y1) / (z2 - z1):
            inside = not inside
    return inside


def _probe(region: Region) -> tuple[float, float]:
    """A point on the region's boundary, to test whether it lies inside another."""
    return outline(region)[0]


def _with_holes(regions: list[Region]) -> list[Region]:
    """Mark the outlines inside an odd number of others as holes."""
    out: list[Region] = []
    for k, region in enumerate(regions):
        depth = sum(
            1 for j, other in enumerate(regions) if j != k and _inside(_probe(region), other)
        )
        hole = depth % 2 == 1
        if isinstance(region, CircleRegion):
            out.append(CircleRegion(region.y, region.z, region.radius, hole))
        else:
            out.append(PolygonRegion(region.points, hole))
    return out


def read_section_drawing(path: str | Path, *, layers: list[str] | None = None) -> SectionDrawing:
    """The closed outlines of ``path`` (optionally only on ``layers``).

    Raises:
        DxfImportError: the file is missing or is not a readable DXF.
    """
    source = Path(path)
    if not source.is_file():
        raise DxfImportError(f"No such file: {source}")
    try:
        document = readfile(source)
    except Exception as exc:  # ezdxf raises its own family of errors
        raise DxfImportError(f"{source.name} is not a readable DXF file ({exc}).") from exc
    wanted = set(layers) if layers else None
    skipped: Counter[str] = Counter()
    candidates: list[Any] = []
    found_layers: set[str] = set()
    open_outlines = 0
    for graphic in document.modelspace():
        entity: Any = graphic
        kind = entity.dxftype()
        layer = str(entity.dxf.get("layer", "0"))
        if wanted is not None and layer not in wanted:
            continue
        if kind not in _CLOSED_KINDS:
            skipped[kind] += 1
            continue
        if not _is_closed(entity, kind):
            open_outlines += 1
            continue
        candidates.append(entity)
        found_layers.add(layer)
    tolerance = FLATTENING * _extent(candidates)
    regions: list[Region] = []
    for entity in candidates:
        if entity.dxftype() == "CIRCLE":
            centre = entity.dxf.center
            regions.append(CircleRegion(float(centre.y), float(centre.x), float(entity.dxf.radius)))
            continue
        points = _points(entity, tolerance)
        if len(points) >= 3:
            regions.append(PolygonRegion(tuple(points)))
    units = int(document.header.get("$INSUNITS", 0) or 0)
    return SectionDrawing(
        regions=_with_holes(regions),
        layers=sorted(found_layers),
        insunits=units,
        unit_name=_DXF_UNIT_NAMES.get(units, f"code {units}"),
        unit_in_metres=_DXF_UNITS_IN_METRES.get(units),
        skipped=dict(skipped),
        open_outlines=open_outlines,
    )


def drawing_scale(drawing: SectionDrawing, units: UnitSystem) -> float:
    """Factor from the drawing's unit to the project's length unit (1 when unitless)."""
    if drawing.unit_in_metres is None:
        return 1.0
    return drawing.unit_in_metres / metres_per_unit(units)


def scaled(regions: list[Region], factor: float) -> list[Region]:
    """``regions`` with every coordinate multiplied by ``factor``."""
    out: list[Region] = []
    for region in regions:
        if isinstance(region, CircleRegion):
            out.append(
                CircleRegion(
                    region.y * factor, region.z * factor, region.radius * factor, region.hole
                )
            )
        else:
            out.append(
                PolygonRegion(
                    tuple((y * factor, z * factor) for y, z in region.points), region.hole
                )
            )
    return out
