"""Import a bar layout from a DXF drawing.

The drawing is read for what it is: a set of straight bars. ``LINE`` entities
are members, open and closed ``LWPOLYLINE`` / ``POLYLINE`` entities are chains
of members, and anything else in the file (circles, text, hatches, blocks) is
counted and reported rather than silently dropped — a drawing that imports four
members where the user expected two hundred is a mistake they have to see.

Three decisions the importer refuses to make on the user's behalf:

* **units.** ``$INSUNITS`` says what the file is in, and that is turned into a
  factor to the project's own unit (shown in the dialog, never guessed at
  silently). A unitless file gets factor 1 and a note saying so;
* **which plane.** Drawings are two-dimensional and models are not: the caller
  says whether the drawing's x/y are a plan (XY), an elevation (XZ, YZ), or
  genuinely three-dimensional (``3D``, coordinates kept as they are), plus the
  level the drawing plane sits at;
* **which layers.** A drawing carries construction lines and axes; the caller
  passes the layers to keep, and the rest are reported.

Endpoints that land on the same point become one node (drawings do not share
vertices, they repeat coordinates), with the tolerance in the caller's hands and
the number of merged endpoints in the result.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ezdxf.filemanagement import readfile

from opensees_studio.core.frames import PLANE_AXES
from opensees_studio.core.geometry.elements import ElasticBeamColumn
from opensees_studio.core.geometry.node import Node, Restraint6

if TYPE_CHECKING:
    from opensees_studio.core.units import UnitSystem

#: ``$INSUNITS`` code → metres. Only the lengths a structural drawing uses;
#: anything else is treated as unitless and reported as such.
_DXF_UNITS_IN_METRES: dict[int, float] = {
    1: 0.0254,  # inches
    2: 0.3048,  # feet
    3: 1609.344,  # miles
    4: 1e-3,  # millimetres
    5: 1e-2,  # centimetres
    6: 1.0,  # metres
    7: 1e3,  # kilometres
    9: 2.54e-5,  # mils
    10: 0.9144,  # yards
    13: 1e-6,  # microns
    14: 0.1,  # decimetres
    15: 10.0,  # decametres
    16: 100.0,  # hectometres
    21: 1200.0 / 3937.0,  # US survey feet
    22: 100.0 / 3937.0,  # US survey inches
    23: 3600.0 / 3937.0,  # US survey yards
    24: 5280.0 * 1200.0 / 3937.0,  # US survey miles
}

_DXF_UNIT_NAMES: dict[int, str] = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "millimetres",
    5: "centimetres",
    6: "metres",
    7: "kilometres",
    9: "mils",
    10: "yards",
    13: "microns",
    14: "decimetres",
    15: "decametres",
    16: "hectometres",
    21: "US survey feet",
    22: "US survey inches",
    23: "US survey yards",
    24: "US survey miles",
}

#: Planes the drawing's x/y can be read as. ``3D`` keeps the file's own axes.
PLANE_CHOICES: list[tuple[str, str]] = [
    ("XY — plan (2D frame, Z from the level below)", "XY"),
    ("XZ — front elevation (Y from the level below)", "XZ"),
    ("YZ — side elevation (X from the level below)", "YZ"),
    ("3D — keep the drawing's own X, Y and Z", "3D"),
]

#: Tolerance used to decide two endpoints are the same node, relative to the
#: drawing's own size (a DXF is as likely to be in metres as in millimetres).
RELATIVE_MERGE_TOLERANCE = 1e-6

#: Drawings carry no supports: every imported node arrives free.
FREE_RESTRAINT = (False, False, False, False, False, False)


class DxfImportError(RuntimeError):
    """The file cannot be read as a bar drawing."""


Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class DxfSegment:
    """One straight bar, in the file's own coordinates and units."""

    start: Point3
    end: Point3
    layer: str


@dataclass(frozen=True)
class DxfDrawing:
    """What the file had to offer."""

    segments: list[DxfSegment]
    layers: list[str]
    insunits: int
    unit_name: str
    unit_in_metres: float | None
    skipped: dict[str, int] = field(default_factory=dict)
    chorded: int = 0
    """Polylines with a bulge: curved segments, imported as straight chords."""

    @property
    def is_empty(self) -> bool:
        return not self.segments

    def skipped_summary(self) -> str:
        parts = []
        if self.skipped:
            counts = ", ".join(f"{count} {name}" for name, count in sorted(self.skipped.items()))
            parts.append(f"Not imported (not straight bars): {counts}.")
        if self.chorded:
            parts.append(f"{self.chorded} curved polyline segment(s) imported as straight chords.")
        return " ".join(parts)


@dataclass(frozen=True)
class ImportedBars:
    """The models an import produces, plus what had to be decided on the way."""

    nodes: list[Node]
    elements: list[ElasticBeamColumn]
    dropped_segments: int = 0
    merged_endpoints: int = 0

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def n_members(self) -> int:
        return len(self.elements)

    def summary(self) -> str:
        text = f"{self.n_members} member(s) and {self.n_nodes} node(s)"
        if self.dropped_segments:
            text += f"; {self.dropped_segments} zero-length segment(s) dropped"
        if self.merged_endpoints:
            text += f"; {self.merged_endpoints} repeated endpoint(s) merged into shared nodes"
        return text + "."


# ──────────────────────────── reading ────────────────────────────
def _line_segments(entity: Any) -> list[tuple[Point3, Point3]]:
    start = entity.dxf.start
    end = entity.dxf.end
    return [
        (
            (float(start.x), float(start.y), float(start.z)),
            (float(end.x), float(end.y), float(end.z)),
        )
    ]


def _chain_segments(points: list[Point3], *, closed: bool) -> list[tuple[Point3, Point3]]:
    segments = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    if closed and len(points) > 2:
        segments.append((points[-1], points[0]))
    return segments


def read_drawing(path: str | Path, *, layers: list[str] | None = None) -> DxfDrawing:
    """Read the straight bars of ``path``, optionally only from ``layers``.

    The result may be empty (a drawing with no bars at all is a legitimate
    answer); the caller decides whether that is a refusal.

    Raises:
        DxfImportError: if the file is missing or is not a readable DXF.
    """
    source = Path(path)
    if not source.is_file():
        raise DxfImportError(f"No such file: {source}")
    try:
        document = readfile(source)
    except Exception as exc:  # ezdxf raises its own family of errors
        raise DxfImportError(f"{source.name} is not a readable DXF file ({exc}).") from exc

    wanted = set(layers) if layers else None
    segments: list[DxfSegment] = []
    skipped: Counter[str] = Counter()
    chorded = 0
    for graphic in document.modelspace():
        entity: Any = graphic  # ezdxf's entity API is per-type, not on the base class
        kind = entity.dxftype()
        layer = str(entity.dxf.get("layer", "0"))
        if wanted is not None and layer not in wanted:
            continue
        if kind == "LINE":
            pairs = _line_segments(entity)
        elif kind == "LWPOLYLINE":
            # Lightweight polylines are flat: x, y, a width and a bulge
            # (curvature) per vertex, with one elevation for the whole entity.
            elevation = float(entity.dxf.get("elevation", 0.0))
            vertices = list(entity.get_points("xyseb"))
            chorded += sum(1 for *_rest, bulge in vertices if bulge)
            pairs = _chain_segments(
                [(float(vertex[0]), float(vertex[1]), elevation) for vertex in vertices],
                closed=bool(entity.closed),
            )
        elif kind == "POLYLINE":
            pairs = _chain_segments(
                [
                    (float(v.dxf.location.x), float(v.dxf.location.y), float(v.dxf.location.z))
                    for v in entity.vertices
                ],
                closed=bool(entity.is_closed),
            )
        else:
            skipped[kind] += 1
            continue
        segments.extend(DxfSegment(start=start, end=end, layer=layer) for start, end in pairs)

    units = int(document.header.get("$INSUNITS", 0) or 0)
    return DxfDrawing(
        segments=segments,
        layers=sorted({segment.layer for segment in segments}),
        insunits=units,
        unit_name=_DXF_UNIT_NAMES.get(units, f"code {units}"),
        unit_in_metres=_DXF_UNITS_IN_METRES.get(units),
        skipped=dict(skipped),
        chorded=chorded,
    )


def select_layers(drawing: DxfDrawing, layers: list[str] | None) -> DxfDrawing:
    """The same drawing restricted to ``layers``; ``None`` keeps everything."""
    if layers is None:
        return drawing
    wanted = set(layers)
    return DxfDrawing(
        segments=[segment for segment in drawing.segments if segment.layer in wanted],
        layers=sorted({segment.layer for segment in drawing.segments if segment.layer in wanted}),
        insunits=drawing.insunits,
        unit_name=drawing.unit_name,
        unit_in_metres=drawing.unit_in_metres,
        skipped=drawing.skipped,
        chorded=drawing.chorded,
    )


def unit_scale(drawing: DxfDrawing, project_units: UnitSystem) -> float:
    """Factor taking a length in the drawing to the project's own unit.

    A unitless file gets 1 — the caller shows that, so nobody is left thinking a
    conversion happened.
    """
    from opensees_studio.core.units import metres_per_unit

    if drawing.unit_in_metres is None:
        return 1.0
    return drawing.unit_in_metres / metres_per_unit(project_units)


def merge_tolerance(drawing: DxfDrawing, *, relative: float = RELATIVE_MERGE_TOLERANCE) -> float:
    """Default endpoint-merge tolerance: a fraction of the drawing's own size."""
    if not drawing.segments:
        return relative
    xs = [value for segment in drawing.segments for value in (segment.start[0], segment.end[0])]
    ys = [value for segment in drawing.segments for value in (segment.start[1], segment.end[1])]
    zs = [value for segment in drawing.segments for value in (segment.start[2], segment.end[2])]
    diagonal = (
        float((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2) ** 0.5
    )
    scaled = relative * diagonal
    return scaled if scaled > 1e-12 else 1e-12


# ──────────────────────────── building the model ────────────────────────────
class _NodeIndex:
    """Endpoints that land on the same point become one node.

    Drawings repeat coordinates instead of sharing vertices, so this is where
    the "one node per corner" happens. The tolerance is in the caller's hands.
    """

    def __init__(self, *, tolerance: float, first_id: int) -> None:
        self._tolerance = max(tolerance, 0.0)
        self._next_id = first_id
        self._cells: dict[tuple[int, int, int], list[int]] = {}
        self._points: dict[int, Point3] = {}
        self.nodes: list[Node] = []
        self.merged = 0

    def _key(self, point: Point3) -> tuple[int, int, int]:
        step = self._tolerance or 1.0
        return (
            round(point[0] / step),
            round(point[1] / step),
            round(point[2] / step),
        )

    def _near(self, point: Point3) -> int | None:
        key = self._key(point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for node_id in self._cells.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                        stored = self._points[node_id]
                        if (
                            abs(stored[0] - point[0]) <= self._tolerance
                            and abs(stored[1] - point[1]) <= self._tolerance
                            and abs(stored[2] - point[2]) <= self._tolerance
                        ):
                            return node_id
        return None

    def node_id(self, point: Point3, *, restraint: Restraint6) -> int:
        existing = self._near(point)
        if existing is not None:
            self.merged += 1
            return existing
        node_id = self._next_id
        self._next_id += 1
        self.nodes.append(Node(id=node_id, coords=point, restraint=restraint))
        self._cells.setdefault(self._key(point), []).append(node_id)
        self._points[node_id] = point
        return node_id


def bars_from_drawing(
    drawing: DxfDrawing,
    *,
    section_id: int,
    plane: str = "XZ",
    scale: float = 1.0,
    level: float = 0.0,
    origin: Point3 = (0.0, 0.0, 0.0),
    tolerance: float | None = None,
    first_node_id: int = 1,
    first_element_id: int = 1,
) -> ImportedBars:
    """Turn the drawing's segments into nodes and beam-column elements.

    ``plane`` is ``XY``, ``XZ``, ``YZ`` or ``3D``: the first three read the
    drawing's x and y as those two axes and put the plane at ``level``, the last
    keeps the file's own coordinates (and then ``level`` is ignored). ``scale``
    converts the drawing's units to the project's, and ``origin`` is where the
    drawing's own (0, 0, 0) ends up — ``level`` is measured from it along the
    plane's normal.

    Segments shorter than the merge tolerance are dropped: they would be nodes on
    top of each other, which the solver cannot take.
    """
    if plane not in (*PLANE_AXES, "3D"):
        raise DxfImportError(f"Unknown plane {plane!r}.")
    merge = merge_tolerance(drawing) if tolerance is None else tolerance
    index = _NodeIndex(tolerance=merge, first_id=first_node_id)
    elements: list[ElasticBeamColumn] = []
    next_element = first_element_id
    dropped = 0

    def place(point: Point3) -> Point3:
        x, y, z = (value * scale for value in point)
        if plane == "3D":
            placed = (x + origin[0], y + origin[1], z + origin[2])
        else:
            span_axis, height_axis, _ = PLANE_AXES[plane]
            coords = list(origin)
            coords[span_axis] += x
            coords[height_axis] += y
            coords[PLANE_AXES[plane][2]] = level + origin[PLANE_AXES[plane][2]]
            placed = (coords[0], coords[1], coords[2])
        return placed

    for segment in drawing.segments:
        start, end = place(segment.start), place(segment.end)
        if all(abs(a - b) <= merge for a, b in zip(start, end, strict=True)):
            dropped += 1
            continue
        # Drawings have no supports: everything arrives free, and the user
        # restrains what the drawing cannot say.
        first = index.node_id(start, restraint=FREE_RESTRAINT)
        second = index.node_id(end, restraint=FREE_RESTRAINT)
        if first == second:
            dropped += 1
            continue
        elements.append(
            ElasticBeamColumn(id=next_element, nodes=(first, second), section_id=section_id)
        )
        next_element += 1

    return ImportedBars(
        nodes=index.nodes,
        elements=elements,
        dropped_segments=dropped,
        merged_endpoints=index.merged,
    )
