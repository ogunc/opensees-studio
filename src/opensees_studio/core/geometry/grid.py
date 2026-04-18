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

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GridSystem(BaseModel):
    """Axis-aligned grid lines stored per local axis.

    Each of ``x_lines`` / ``y_lines`` / ``z_lines`` is a sorted list of
    coordinates along that axis. An empty list means "no grid lines on
    that axis" — the grid degenerates to a 2D or 1D family.

    ``is_general`` tracks SAP2000's Cartesian/General toggle. Our grid
    renderer currently treats both identically; the flag is persisted
    so the Cartesian spacings editor can distinguish between them.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    x_lines: list[float] = Field(default_factory=list)
    y_lines: list[float] = Field(default_factory=list)
    z_lines: list[float] = Field(default_factory=list)
    visible: bool = Field(
        default=True,
        description="Whether the grid is drawn in the 3D canvas.",
    )
    is_general: bool = Field(
        default=False,
        description="SAP2000 'Convert to General Grid' toggle.",
    )

    @model_validator(mode="after")
    def _sort_and_dedupe(self) -> "GridSystem":
        for name in ("x_lines", "y_lines", "z_lines"):
            vals = getattr(self, name)
            vals = sorted(vals)
            cleaned: list[float] = []
            for v in vals:
                if not cleaned or abs(v - cleaned[-1]) > 1e-9:
                    cleaned.append(v)
            object.__setattr__(self, name, cleaned)
        return self

    def bounds(self) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        """Return ((xmin, xmax), (ymin, ymax), (zmin, zmax)) spanning the grid."""
        def span(vs: list[float]) -> tuple[float, float]:
            if not vs:
                return (0.0, 0.0)
            return (vs[0], vs[-1])
        return span(self.x_lines), span(self.y_lines), span(self.z_lines)


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
