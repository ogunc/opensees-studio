"""Grid system — SAP2000-style coordinate/grid systems.

A :class:`GridSystem` holds the axis-aligned grid lines for one
system. A :class:`CoordinateSystem` is the location + orientation of
a local frame. A :class:`CoordinateGridSystem` is the named pairing
of the two — this is the entity shown in SAP2000's
"Define → Coordinate System/Grids" dialog.

An unlimited number of :class:`CoordinateGridSystem` objects can be
defined in a :class:`Project`. One of them is always named ``Global``
and sits at the world origin with identity orientation — it cannot be
deleted (the dialog layer enforces that).

Grid lines are **visual references only**; they do NOT create nodes.
Users create nodes by snapping to grid intersections in the canvas
tools, by typing coordinates in Add Node, or via the optional bulk
"create nodes at every intersection" checkbox.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GridLine(BaseModel):
    """One labelled grid line — matches SAP2000's Grid Data row exactly.

    Each line carries:
    - ``id``:        short label shown in the bubble (e.g. "A", "1", "X1")
    - ``ordinate``:  distance from the coord system's origin along the axis
    - ``line_type``: Primary / Secondary (Primary lines are bolder)
    - ``visible``:   per-line visibility toggle
    - ``bubble_loc``: Start | End — which end of the line shows the ID
    - ``color``:     hex colour string ("#RRGGBB")
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str = Field(..., min_length=1)
    ordinate: float
    line_type: Literal["Primary", "Secondary"] = "Primary"
    visible: bool = True
    bubble_loc: Literal["Start", "End"] = "End"
    color: str = "#808080"


class GridSystem(BaseModel):
    """Axis-aligned grid lines stored as :class:`GridLine` records.

    Each axis holds a sorted list of GridLine records — each carrying
    an ID, ordinate, line type, visibility, bubble location, and colour.
    The :attr:`x_lines` / :attr:`y_lines` / :attr:`z_lines` properties
    return the flat ordinate lists that the renderer and snap logic use.

    Old schema (``x_lines: list[float]``) is migrated to the new GridLine
    format at load time; save always emits the new format.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    x_grid_lines: list[GridLine] = Field(default_factory=list)
    y_grid_lines: list[GridLine] = Field(default_factory=list)
    z_grid_lines: list[GridLine] = Field(default_factory=list)
    visible: bool = Field(default=True)
    is_general: bool = Field(default=False)
    hide_all: bool = Field(default=False)
    glue_to_grid: bool = Field(default=False)
    bubble_size: int = Field(default=20, ge=4, le=200)

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_lists(cls, data: Any) -> Any:
        """Back-compat: convert old ``x_lines: list[float]`` into GridLine records."""
        if not isinstance(data, dict):
            return data
        for prefix, axis in [("X", "x"), ("Y", "y"), ("Z", "z")]:
            flat_key = f"{axis}_lines"
            grid_key = f"{axis}_grid_lines"
            if flat_key in data:
                flat = data.pop(flat_key)
                if grid_key not in data:
                    records: list[dict] = []
                    for i, v in enumerate(flat or []):
                        if isinstance(v, dict):
                            records.append(v)
                        else:
                            records.append({
                                "id": f"{prefix}{i + 1}",
                                "ordinate": float(v),
                            })
                    data[grid_key] = records
        return data

    @model_validator(mode="after")
    def _sort_and_dedupe(self) -> "GridSystem":
        for name in ("x_grid_lines", "y_grid_lines", "z_grid_lines"):
            lines: list[GridLine] = list(getattr(self, name))
            lines.sort(key=lambda ln: ln.ordinate)
            cleaned: list[GridLine] = []
            for ln in lines:
                if not cleaned or abs(ln.ordinate - cleaned[-1].ordinate) > 1e-9:
                    cleaned.append(ln)
            object.__setattr__(self, name, cleaned)
        return self

    # ── ordinate accessors (what the renderer + snap helpers consume) ──
    @property
    def x_lines(self) -> list[float]:
        return [ln.ordinate for ln in self.x_grid_lines]

    @property
    def y_lines(self) -> list[float]:
        return [ln.ordinate for ln in self.y_grid_lines]

    @property
    def z_lines(self) -> list[float]:
        return [ln.ordinate for ln in self.z_grid_lines]

    def bounds(self) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        """Return ((xmin, xmax), (ymin, ymax), (zmin, zmax)) spanning the grid."""
        def span(vs: list[float]) -> tuple[float, float]:
            if not vs:
                return (0.0, 0.0)
            return (vs[0], vs[-1])
        return span(self.x_lines), span(self.y_lines), span(self.z_lines)


def make_grid_lines(
    axis: Literal["X", "Y", "Z"], ordinates: list[float],
) -> list[GridLine]:
    """Helper: build default-metadata GridLine records from flat ordinates."""
    return [
        GridLine(id=f"{axis}{i + 1}", ordinate=float(v))
        for i, v in enumerate(ordinates)
    ]


class CoordinateSystem(BaseModel):
    """Location + orientation of a local coordinate frame relative to Global.

    ``rotation_deg`` are XYZ Euler angles in degrees, applied in the
    order Rx → Ry → Rz (matching SAP2000's "about X, then Y, then Z"
    convention as shown in the Coord System Location and Orientation
    form). All angles default to 0 → identity orientation.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def rotation_matrix(self) -> list[list[float]]:
        """Return the 3×3 rotation matrix for ``rotation_deg`` (XYZ order)."""
        rx, ry, rz = (math.radians(a) for a in self.rotation_deg)
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        # Rz · Ry · Rx  (applied right-to-left: Rx first, then Ry, then Rz).
        return [
            [cy * cz,  sx * sy * cz - cx * sz,  cx * sy * cz + sx * sz],
            [cy * sz,  sx * sy * sz + cx * cz,  cx * sy * sz - sx * cz],
            [-sy,      sx * cy,                  cx * cy],
        ]

    def local_to_world(self, p_local: tuple[float, float, float]) -> tuple[float, float, float]:
        """Transform a point from this system's local frame to world."""
        m = self.rotation_matrix()
        x, y, z = p_local
        ox, oy, oz = self.origin
        return (
            m[0][0] * x + m[0][1] * y + m[0][2] * z + ox,
            m[1][0] * x + m[1][1] * y + m[1][2] * z + oy,
            m[2][0] * x + m[2][1] * y + m[2][2] * z + oz,
        )

    def world_to_local(self, p_world: tuple[float, float, float]) -> tuple[float, float, float]:
        """Transform a point from world to this system's local frame."""
        m = self.rotation_matrix()
        # Inverse of a pure rotation is its transpose.
        dx = p_world[0] - self.origin[0]
        dy = p_world[1] - self.origin[1]
        dz = p_world[2] - self.origin[2]
        return (
            m[0][0] * dx + m[1][0] * dy + m[2][0] * dz,
            m[0][1] * dx + m[1][1] * dy + m[2][1] * dz,
            m[0][2] * dx + m[1][2] * dy + m[2][2] * dz,
        )


class CoordinateGridSystem(BaseModel):
    """A named (coordinate system + grid system) pair — SAP2000 equivalent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = Field(..., min_length=1)
    coord: CoordinateSystem = Field(default_factory=CoordinateSystem)
    grid: GridSystem = Field(default_factory=GridSystem)

    def is_global(self) -> bool:
        """``True`` iff this is the immutable Global system."""
        return self.name == "Global"


def default_global_system() -> CoordinateGridSystem:
    """Return a fresh ``Global`` coordinate/grid system (identity + empty grid)."""
    return CoordinateGridSystem(name="Global")
