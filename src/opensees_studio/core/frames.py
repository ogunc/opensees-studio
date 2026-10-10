"""Parametric 2D portal frames: a roof line, columns under it, and supports.

A "marco" here is the classic plane frame: columns on a grid of bay widths,
carrying a roof that is flat, single-pitched (mono-pitch) or double-pitched
(gable). Everything is derived from a handful of numbers, so the wizard's
preview, the geometry and the tests all read the same specification instead of
re-deriving it.

Two rules do all the work:

* **The roof line is a function of the span coordinate.** A mono-pitch roof
  rises from the low eave to the high eave across the whole width; a gable
  rises from each eave (or, with interior columns, from the roof's own profile)
  towards the ridge at mid-span. The line is ``eave + slope * distance from the
  nearest eave``, so a gable is two mono-pitches meeting at the middle.
* **Column tops sit on that line.** An interior column is therefore as tall as
  the roof is above its base — which is what makes a multi-bay frame with
  interior columns work without the user typing each height.

With a gable roof and an odd number of bays the ridge falls in the middle of a
bay, so a crown node is inserted there and that bay's rafter becomes two
elements. With an even number of bays the ridge lands on a column and no extra
node is needed.

The module is pure: it builds :mod:`opensees_studio.core` models and computes
the restraint vectors from ``(ndm, ndf)``, so a 2D project (``ndm=2, ndf=3``,
frame in the XY plane, Y up) and a 3D project (``ndm=3, ndf=6``) are both
described here rather than in the dialog.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Literal

from opensees_studio.core.geometry.elements import ElasticBeamColumn
from opensees_studio.core.geometry.grid import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridSystem,
    make_grid_lines,
)
from opensees_studio.core.geometry.node import Node, Restraint6

#: Frames are plane frames: a span axis, a height axis, and the axis normal to
#: the plane. Names match the canvas working planes (Z is up).
PLANE_AXES: dict[str, tuple[int, int, int]] = {
    "XY": (0, 1, 2),  # span x, height y, out of plane z
    "XZ": (0, 2, 1),  # span x, height z, out of plane y
    "YZ": (1, 2, 0),  # span y, height z, out of plane x
}

#: The out-of-plane DOF indices (canonical 6-DOF storage) per plane.
_OUT_OF_PLANE_DOFS: dict[str, tuple[int, ...]] = {
    "XY": (2, 3, 4),  # Uz, Rx, Ry
    "XZ": (1, 3, 5),  # Uy, Rx, Rz
    "YZ": (0, 4, 5),  # Ux, Ry, Rz
}

#: (ndm, ndf) pairs a beam-column portal frame can be built in.
SUPPORTED_NDF: frozenset[tuple[int, int]] = frozenset({(2, 3), (3, 6)})

Plane = Literal["XY", "XZ", "YZ"]


class RoofType(enum.Enum):
    """Roof profile of the frame."""

    MONO_PITCH = "mono"  #: one slope, eave to eave (slope 0 is a flat roof)
    GABLE = "gable"  #: two slopes meeting at the ridge


class SupportCondition(enum.Enum):
    """What the column bases are fixed against."""

    FIXED = "fixed"  #: translations and rotations
    PINNED = "pinned"  #: translations only


class PortalFrameError(ValueError):
    """The specification cannot describe a frame."""


@dataclass(frozen=True)
class PortalFrameSpec:
    """Everything the wizard asks for.

    Dimensions are in project units; ``slope`` is a ratio (rise over run), so
    10 % is ``0.10`` and 45° is ``1.0``.
    """

    bay_width: float
    eave_height: float
    column_section_id: int
    rafter_section_id: int
    roof: RoofType = RoofType.GABLE
    slope: float = 0.10
    n_bays: int = 1
    support: SupportCondition = SupportCondition.FIXED
    plane: Plane = "XZ"
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    restrain_out_of_plane: bool = True

    def __post_init__(self) -> None:
        if self.n_bays < 1:
            raise PortalFrameError("A frame needs at least one bay.")
        if self.bay_width <= 0.0:
            raise PortalFrameError("The bay width must be positive.")
        if self.eave_height <= 0.0:
            raise PortalFrameError("The eave height must be positive.")
        if self.slope < 0.0:
            raise PortalFrameError("The roof slope cannot be negative.")
        if self.slope >= 1.0:
            raise PortalFrameError("A slope of 100 % or more is not a roof.")
        if self.column_section_id < 1 or self.rafter_section_id < 1:
            raise PortalFrameError("Both member groups need a section.")
        if self.plane not in PLANE_AXES:
            raise PortalFrameError(f"Unknown plane {self.plane!r}.")
        if len(self.origin) != 3:
            raise PortalFrameError("The origin needs three coordinates.")

    # ── derived geometry ────────────────────────────────────────────
    @property
    def span(self) -> float:
        """Total width of the frame."""
        return self.n_bays * self.bay_width

    @property
    def ridge_height(self) -> float:
        """Highest point of the roof: the ridge, or the high eave of a mono-pitch."""
        return self.eave_height + self.slope * self._rise_span()

    def _rise_span(self) -> float:
        """The run the roof climbs over: the whole width, or half of it for a gable."""
        return self.span if self.roof is RoofType.MONO_PITCH else self.span / 2.0

    @property
    def has_ridge_node(self) -> bool:
        """True when the ridge falls between two columns (odd number of bays)."""
        return self.roof is RoofType.GABLE and self.n_bays % 2 == 1

    def roof_height(self, x: float) -> float:
        """Height of the roof line ``x`` along the span, measured from the origin."""
        if x <= 0.0:
            run = 0.0
        elif self.roof is RoofType.MONO_PITCH:
            run = x
        else:
            run = min(x, self.span - x)
        return self.eave_height + self.slope * run

    def column_heights(self) -> list[float]:
        """Roof height at each column line, left to right."""
        return [self.roof_height(i * self.bay_width) for i in range(self.n_bays + 1)]

    # ── restraint vectors ───────────────────────────────────────────
    def restraint(self, *, is_base: bool, ndm: int, ndf: int) -> Restraint6:
        """The 6-DOF restraint vector for a node of this frame.

        Only the DOF the ``(ndm, ndf)`` pair actually uses are ever set (see
        ``core.modal.dof_indices``); the rest stay free so a 2D model does not
        carry meaningless flags.
        """
        if (ndm, ndf) not in SUPPORTED_NDF:
            raise PortalFrameError(f"Unsupported (ndm, ndf): ({ndm}, {ndf}).")
        flags = [False] * 6
        in_plane_translations, in_plane_rotation = self._in_plane_dofs(ndm)
        if is_base:
            for dof in in_plane_translations:
                flags[dof] = True
            if self.support is SupportCondition.FIXED and in_plane_rotation is not None:
                flags[in_plane_rotation] = True
            if ndf == 6:
                # A base also holds the frame down out of its plane; the other
                # two translations are the in-plane ones set above.
                flags[_OUT_OF_PLANE_DOFS[self.plane][0]] = True
        if self.restrain_out_of_plane and ndf == 6:
            for dof in _OUT_OF_PLANE_DOFS[self.plane]:
                flags[dof] = True
        return (flags[0], flags[1], flags[2], flags[3], flags[4], flags[5])

    def _in_plane_dofs(self, ndm: int) -> tuple[tuple[int, int], int | None]:
        """The two in-plane translations and the in-plane rotation, if any."""
        if ndm == 2:
            return (0, 1), 5  # X, Y and Rz
        span_axis, height_axis, _ = PLANE_AXES[self.plane]
        return (span_axis, height_axis), {0: 3, 1: 4, 2: 5}[PLANE_AXES[self.plane][2]]


@dataclass(frozen=True)
class PortalFrame:
    """The built frame: models ready to be inserted, plus what it came out as."""

    nodes: list[Node]
    elements: list[ElasticBeamColumn]
    spec: PortalFrameSpec
    base_node_ids: list[int]
    top_node_ids: list[int]
    ridge_node_id: int | None

    @property
    def n_columns(self) -> int:
        return self.spec.n_bays + 1

    def summary(self) -> str:
        """One line for the log: what was created."""
        roof = {
            RoofType.MONO_PITCH: "1 slope",
            RoofType.GABLE: "2 slopes",
        }[self.spec.roof]
        rafters = self.spec.n_bays + int(self.spec.has_ridge_node)
        return (
            f"Portal frame in {self.spec.plane}: {self.spec.n_bays} bay(s) x "
            f"{self.spec.bay_width:g} = {self.spec.span:g}, "
            f"eave {self.spec.eave_height:g}, ridge {self.spec.ridge_height:g} "
            f"({roof}, {self.spec.slope * 100:g} %) - {self.n_columns} columns, "
            f"{rafters} rafters, {len(self.nodes)} nodes."
        )


def build_portal_frame(
    spec: PortalFrameSpec,
    *,
    ndm: int,
    ndf: int,
    first_node_id: int,
    first_element_id: int,
) -> PortalFrame:
    """Build the nodes and beam-column elements of ``spec``.

    Ids are allocated from ``first_node_id`` / ``first_element_id`` upwards, in
    the order the elements are listed, so a caller can insert the result with
    the plain "add nodes" and "add elements" commands and get one undo step.

    Raises:
        PortalFrameError: if ``(ndm, ndf)`` cannot carry a plane frame.
    """
    if (ndm, ndf) not in SUPPORTED_NDF:
        raise PortalFrameError(f"Unsupported (ndm, ndf): ({ndm}, {ndf}).")
    if ndm == 2 and spec.plane != "XY":
        # A 2D model has no third axis to put the frame in.
        raise PortalFrameError("A 2D project builds its frames in the XY plane.")

    span_axis, height_axis, _ = PLANE_AXES[spec.plane]
    origin = list(spec.origin)

    def point(span: float, height: float) -> tuple[float, float, float]:
        coords = list(origin)
        coords[span_axis] += span
        coords[height_axis] += height
        return (coords[0], coords[1], coords[2])

    nodes: list[Node] = []
    elements: list[ElasticBeamColumn] = []
    next_node = first_node_id
    next_element = first_element_id

    bases: list[int] = []
    tops: list[int] = []
    for i in range(spec.n_bays + 1):
        x = i * spec.bay_width
        base_id, top_id = next_node, next_node + 1
        next_node += 2
        bases.append(base_id)
        tops.append(top_id)
        nodes.append(
            Node(
                id=base_id,
                coords=point(x, 0.0),
                restraint=spec.restraint(is_base=True, ndm=ndm, ndf=ndf),
            )
        )
        nodes.append(
            Node(
                id=top_id,
                coords=point(x, spec.roof_height(x)),
                restraint=spec.restraint(is_base=False, ndm=ndm, ndf=ndf),
            )
        )
        elements.append(
            ElasticBeamColumn(
                id=next_element,
                nodes=(base_id, top_id),
                section_id=spec.column_section_id,
            )
        )
        next_element += 1

    ridge_id: int | None = None
    if spec.has_ridge_node:
        # Odd bay count: the ridge sits mid-bay, so crown it with a node and
        # split that bay's rafter in two. The crown is the highest point.
        middle = spec.n_bays // 2
        ridge_id = next_node
        next_node += 1
        nodes.append(
            Node(
                id=ridge_id,
                coords=point(
                    span=middle * spec.bay_width + spec.bay_width / 2.0,
                    height=spec.ridge_height,
                ),
                restraint=spec.restraint(is_base=False, ndm=ndm, ndf=ndf),
            )
        )

    for i in range(spec.n_bays):
        left, right = tops[i], tops[i + 1]
        if ridge_id is not None and i == spec.n_bays // 2:
            elements.append(
                ElasticBeamColumn(
                    id=next_element,
                    nodes=(left, ridge_id),
                    section_id=spec.rafter_section_id,
                )
            )
            next_element += 1
            elements.append(
                ElasticBeamColumn(
                    id=next_element,
                    nodes=(ridge_id, right),
                    section_id=spec.rafter_section_id,
                )
            )
        else:
            elements.append(
                ElasticBeamColumn(
                    id=next_element,
                    nodes=(left, right),
                    section_id=spec.rafter_section_id,
                )
            )
        next_element += 1

    return PortalFrame(
        nodes=nodes,
        elements=elements,
        spec=spec,
        base_node_ids=bases,
        top_node_ids=tops,
        ridge_node_id=ridge_id,
    )


#: Two ordinates closer than this are the same grid line.
GRID_TOLERANCE = 1e-9


def _distinct(values: list[float]) -> list[float]:
    """Sorted ordinates with near-equal ones collapsed (the roof line repeats)."""
    result: list[float] = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > GRID_TOLERANCE:
            result.append(value)
    return result


def frame_grid(spec: PortalFrameSpec, *, name: str = "Portal Frame") -> CoordinateGridSystem:
    """A grid whose lines are the frame's columns, roof levels and plane.

    Started from ``File → New 2D Frame`` so the user keeps drawing on the lines
    the wizard just used: one line per column position (plus the crown line when
    the ridge falls mid-bay), one per distinct height on the roof line, and one
    on the plane's own level. Lines are labelled the way every other grid in the
    application is (``X1``, ``X2``…), and the ordinates are relative to the
    frame's origin, which is where the coordinate system sits.
    """
    span_axis, height_axis, _ = PLANE_AXES[spec.plane]

    span_ordinates = [i * spec.bay_width for i in range(spec.n_bays + 1)]
    if spec.has_ridge_node:
        middle = spec.n_bays // 2
        span_ordinates.append(middle * spec.bay_width + spec.bay_width / 2.0)
    height_ordinates = [0.0, *spec.column_heights(), spec.ridge_height]

    per_axis: list[list[float]] = [[0.0], [0.0], [0.0]]
    per_axis[span_axis] = _distinct(span_ordinates)
    per_axis[height_axis] = _distinct(height_ordinates)

    return CoordinateGridSystem(
        name=name,
        coord=CoordinateSystem(origin=spec.origin),
        grid=GridSystem(
            x_grid_lines=make_grid_lines("X", per_axis[0]),
            y_grid_lines=make_grid_lines("Y", per_axis[1]),
            z_grid_lines=make_grid_lines("Z", per_axis[2]),
        ),
    )
