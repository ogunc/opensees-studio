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
import re
from collections.abc import Sequence
from itertools import pairwise, product
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opensees_studio.core._base import omit_when_default

Point = tuple[float, float, float]
Segment = tuple[Point, Point]

#: Chords per full circle when a cylindrical grid's rings are drawn as polylines.
ARC_SEGMENTS_PER_TURN = 96


class GridLine(BaseModel):
    """One labelled grid line — matches SAP2000's Grid Data row exactly.

    Each line carries:
    - ``id``:        short label shown in the bubble (e.g. "A", "1", "X1")
    - ``ordinate``:  distance from the coord system's origin along the axis
    - ``line_type``: Primary / Secondary (Primary lines are bolder)
    - ``visible``:   per-line visibility toggle
    - ``bubble_loc``: Start | End | Both — which end(s) of the line show the label
    - ``color``:     hex colour string ("#RRGGBB")
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str = Field(..., min_length=1)
    ordinate: float
    line_type: Literal["Primary", "Secondary"] = "Primary"
    visible: bool = True
    bubble_loc: Literal["Start", "End", "Both"] = "End"
    color: str = "#808080"


class GridSystem(BaseModel):
    """Axis-aligned grid lines stored as :class:`GridLine` records.

    Each axis holds a sorted list of GridLine records — each carrying
    an ID, ordinate, line type, visibility, bubble location, and colour.
    The :attr:`x_lines` / :attr:`y_lines` / :attr:`z_lines` properties
    return the flat ordinate lists that the renderer and snap logic use.

    Old schema (``x_lines: list[float]``) is migrated to the new GridLine
    format at load time; save always emits the new format.

    A **cylindrical** system (``system_type="Cylindrical"``) reads the three
    lists as radii (``x_grid_lines``, rings about the local Z axis), angles in
    degrees from local +X towards +Y (``y_grid_lines``, radial lines) and
    elevations (``z_grid_lines``). Everything that draws or snaps goes through
    the local-frame helpers below (:meth:`segments`, :meth:`intersections`,
    :meth:`snap_local`, :meth:`labels`), so it never has to know which kind it is.
    Lines whose ``visible`` is off are left out of all of them.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default(
        "system_type", "show_labels", "label_content", "label_size", "label_color"
    )

    x_grid_lines: list[GridLine] = Field(default_factory=list)
    y_grid_lines: list[GridLine] = Field(default_factory=list)
    z_grid_lines: list[GridLine] = Field(default_factory=list)
    visible: bool = Field(default=True)
    is_general: bool = Field(default=False)
    hide_all: bool = Field(default=False)
    glue_to_grid: bool = Field(default=False)
    bubble_size: int = Field(default=20, ge=4, le=200)
    system_type: Literal["Cartesian", "Cylindrical"] = "Cartesian"
    show_labels: bool = True
    label_content: Literal["ID", "ID + coordinate", "Coordinate"] = "ID"
    label_size: int = Field(default=12, ge=4, le=72, description="Label font size (points)")
    label_color: str = "#1F1F1F"

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
                            records.append(
                                {
                                    "id": f"{prefix}{i + 1}",
                                    "ordinate": float(v),
                                }
                            )
                    data[grid_key] = records
        return data

    @model_validator(mode="after")
    def _sort_and_dedupe(self) -> GridSystem:
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

    # ── local-frame geometry (what the renderer and the snap use) ──
    @property
    def is_cylindrical(self) -> bool:
        return self.system_type == "Cylindrical"

    @property
    def shown(self) -> bool:
        """Drawn and snappable: visible, not hidden, and with some visible line."""
        return self.visible and not self.hide_all and any(self.visible_ordinates())

    def visible_ordinates(self) -> tuple[list[float], list[float], list[float]]:
        """The ordinates of the visible lines per axis (radius, angle, Z if cylindrical)."""
        return (
            [ln.ordinate for ln in self.x_grid_lines if ln.visible],
            [ln.ordinate for ln in self.y_grid_lines if ln.visible],
            [ln.ordinate for ln in self.z_grid_lines if ln.visible],
        )

    def levels(self) -> list[float]:
        """The Z ordinates the plan lines are drawn at (``[0]`` when there are none)."""
        return self.visible_ordinates()[2] or [0.0]

    def _full_turn(self, angles: list[float]) -> bool:
        """True when the radial lines go all the way round (rings drawn closed)."""
        if len(angles) < 2:
            return True
        gaps = [b - a for a, b in pairwise(angles)]
        return angles[-1] - angles[0] + min(gaps) >= 360.0 - 1e-6

    def _arc_range(self, angles: list[float]) -> tuple[float, float]:
        if self._full_turn(angles):
            start = angles[0] if angles else 0.0
            return start, start + 360.0
        return angles[0], angles[-1]

    def segments(self) -> list[Segment]:
        """Every visible grid line as local-frame straight segments.

        Cartesian: X and Y lines across the plan extent at every level, plus the
        verticals through each plan crossing. Cylindrical: rings (polylines) and
        radial lines at every level, plus the verticals through each crossing.
        """
        xs, ys, zs = self.visible_ordinates()
        levels = zs or [0.0]
        out: list[Segment] = []
        if self.is_cylindrical:
            radii = [r for r in xs if r >= 0.0]
            angles = ys or [0.0]
            a0, a1 = self._arc_range(ys)
            r_in = 0.0 if len(radii) < 2 else radii[0]
            r_out = radii[-1] if radii else 1.0
            for z in levels:
                for r in radii:
                    if r <= 0.0:
                        continue
                    n = max(4, math.ceil(ARC_SEGMENTS_PER_TURN * (a1 - a0) / 360.0))
                    pts = [_polar(r, a0 + (a1 - a0) * k / n, z) for k in range(n + 1)]
                    out.extend(pairwise(pts))
                if ys:
                    for a in angles:
                        out.append((_polar(r_in, a, z), _polar(r_out, a, z)))
            plan = [_polar(r, a, 0.0) for r in radii for a in angles] if radii and ys else []
        else:
            xmin, xmax = _span(xs)
            ymin, ymax = _span(ys)
            for z in levels:
                out.extend(((x, ymin, z), (x, ymax, z)) for x in xs)
                out.extend(((xmin, y, z), (xmax, y, z)) for y in ys)
            plan = [(x, y, 0.0) for x in xs for y in ys] if xs and ys else []
        if len(zs) >= 2:
            out.extend(((p[0], p[1], zs[0]), (p[0], p[1], zs[-1])) for p in plan)
        return out

    def intersections(self) -> list[Point]:
        """Every crossing of visible lines, in the local frame (the snap targets)."""
        xs, ys, zs = self.visible_ordinates()
        if not (xs or ys or zs):
            return []
        levels = zs or [0.0]
        if self.is_cylindrical:
            angles = ys or [0.0]
            points: set[Point] = set()
            for r, a, z in product(xs or [0.0], angles, levels):
                points.add(_round_point(_polar(r, a, z)))
            return sorted(points)
        return [(x, y, z) for z in levels for x in xs or [0.0] for y in ys or [0.0]]

    def snap_local(self, point: Point, axes: Sequence[int] = (0, 1, 2)) -> Point:
        """Move ``point`` (local frame) onto the nearest crossing of visible lines.

        ``axes`` are the local Cartesian coordinates allowed to move (the
        working plane's two in-plane axes; all three by default). A cylindrical
        grid snaps radius and angle together, and only when both X and Y may move:
        in an elevation it snaps the level alone, so the point stays on the plane.
        """
        xs, ys, zs = self.visible_ordinates()
        out = list(point)
        if self.is_cylindrical:
            if 0 in axes and 1 in axes:
                r = math.hypot(point[0], point[1])
                a = math.degrees(math.atan2(point[1], point[0]))
                r = _nearest(r, xs)
                if ys:
                    a = min(ys, key=lambda t: abs(_wrap(t - a)))
                p = _polar(r, a, point[2])
                out[0], out[1] = p[0], p[1]
            if 2 in axes:
                out[2] = _nearest(point[2], zs)
            return (out[0], out[1], out[2])
        for axis, lines in enumerate((xs, ys, zs)):
            if axis in axes:
                out[axis] = _nearest(point[axis], lines)
        return (out[0], out[1], out[2])

    def labels(self) -> list[tuple[Point, str]]:
        """The bubble labels: (local-frame anchor, text) at the end(s) each line asks for.

        Anchors sit a little beyond the line's end (a twentieth of the plan
        extent), on the lowest level, so they never cover a joint.
        """
        if not self.show_labels:
            return []
        xs, ys, zs = self.visible_ordinates()
        z0 = zs[0] if zs else 0.0
        out: list[tuple[Point, str]] = []
        if self.is_cylindrical:
            radii = [r for r in xs if r >= 0.0]
            r_out = radii[-1] if radii else 1.0
            r_in = 0.0 if len(radii) < 2 else radii[0]
            pad = 0.08 * max(r_out, 1e-9)
            a0, a1 = self._arc_range(ys)
            full = self._full_turn(ys)
            for ln in self.x_grid_lines:
                if not ln.visible or ln.ordinate <= 0.0:
                    continue
                ends = {"Start": a0, "End": a1 if not full else a0 + 180.0}
                for where in _ends(ln.bubble_loc):
                    out.append((_polar(ln.ordinate, ends[where], z0), self._text(ln, "R")))
            for ln in self.y_grid_lines:
                if not ln.visible:
                    continue
                ends = {"Start": max(r_in - pad, 0.0), "End": r_out + pad}
                for where in _ends(ln.bubble_loc):
                    out.append((_polar(ends[where], ln.ordinate, z0), self._text(ln, "°")))
        else:
            xmin, xmax = _span(xs)
            ymin, ymax = _span(ys)
            pad = 0.05 * max(xmax - xmin, ymax - ymin, 1e-9)
            for ln in self.x_grid_lines:
                if ln.visible:
                    ends = {"Start": ymin - pad, "End": ymax + pad}
                    for where in _ends(ln.bubble_loc):
                        out.append(((ln.ordinate, ends[where], z0), self._text(ln, "")))
            for ln in self.y_grid_lines:
                if ln.visible:
                    ends = {"Start": xmin - pad, "End": xmax + pad}
                    for where in _ends(ln.bubble_loc):
                        out.append(((ends[where], ln.ordinate, z0), self._text(ln, "")))
        # Z lines are levels: one label beside the plan's first corner.
        if len(zs) >= 2 or (zs and not (xs or ys)):
            corner = out[0][0] if out else (0.0, 0.0, z0)
            for ln in self.z_grid_lines:
                if ln.visible:
                    out.append(((corner[0], corner[1], ln.ordinate), self._text(ln, "")))
        return out

    def _text(self, line: GridLine, unit: str) -> str:
        value = f"{line.ordinate:g}{unit}" if unit == "°" else f"{line.ordinate:g}"
        if self.label_content == "Coordinate":
            return value
        if self.label_content == "ID + coordinate":
            return f"{line.id} ({value})"
        return line.id


def _span(values: list[float]) -> tuple[float, float]:
    """The extent the perpendicular lines are drawn across (±1 around a single value)."""
    if not values:
        return (-1.0, 1.0)
    lo, hi = min(values), max(values)
    return (lo - 1.0, hi + 1.0) if lo == hi else (lo, hi)


def _polar(r: float, angle_deg: float, z: float) -> Point:
    a = math.radians(angle_deg)
    # Rounded so a line at 90° lands on x = 0, not on 6e-16.
    return (round(r * math.cos(a), 12) + 0.0, round(r * math.sin(a), 12) + 0.0, z)


def _round_point(p: Point) -> Point:
    return (round(p[0], 9) + 0.0, round(p[1], 9) + 0.0, round(p[2], 9) + 0.0)


def _wrap(delta_deg: float) -> float:
    """An angle difference folded into (-180, 180]."""
    return (delta_deg + 180.0) % 360.0 - 180.0


def _nearest(value: float, lines: list[float]) -> float:
    return min(lines, key=lambda c: abs(c - value)) if lines else value


def _ends(loc: str) -> tuple[str, ...]:
    return ("Start", "End") if loc == "Both" else (loc,)


_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")


def next_grid_id(ids: Sequence[str], axis: str) -> str:
    """The id after the last one: ``X3`` → ``X4``, ``C`` → ``D``, ``Z`` → ``AA``.

    Falls back to ``<axis><n+1>`` when the last id follows no pattern or the
    guess is taken already.
    """
    taken = set(ids)
    guess = f"{axis}{len(ids) + 1}"
    if ids:
        last = ids[-1]
        match = _TRAILING_NUMBER.match(last)
        if match:
            digits = match.group(2)
            guess = f"{match.group(1)}{int(digits) + 1:0{len(digits)}d}"
        elif last.isalpha() and last.isupper():
            guess = _next_letters(last)
    n = len(ids) + 1
    while guess in taken:
        guess = f"{axis}{n}"
        n += 1
    return guess


def _next_letters(text: str) -> str:
    chars = list(text)
    i = len(chars) - 1
    while i >= 0:
        if chars[i] != "Z":
            chars[i] = chr(ord(chars[i]) + 1)
            return "".join(chars)
        chars[i] = "A"
        i -= 1
    return "A" + "".join(chars)


def next_grid_ordinate(ordinates: Sequence[float], default_step: float = 1.0) -> float:
    """Where a new line goes: the last ordinate plus the last spacing.

    With one line the step is ``default_step``; with none the line goes at 0.
    """
    if not ordinates:
        return 0.0
    if len(ordinates) == 1:
        return ordinates[0] + default_step
    step = ordinates[-1] - ordinates[-2]
    return ordinates[-1] + (step if step != 0 else default_step)


def grid_line_ids(style: str, count: int, axis: str, start: int = 1) -> list[str]:
    """Ids for ``count`` new lines: ``"Letters"`` (A, B, …), ``"Numbers"`` (1, 2, …) or
    ``"Axis"`` (X1, X2, …)."""
    if style == "Letters":
        ids = ["A"]
        while len(ids) < count:
            ids.append(_next_letters(ids[-1]))
        return ids[:count]
    if style == "Numbers":
        return [str(start + k) for k in range(count)]
    return [f"{axis}{start + k}" for k in range(count)]


def make_grid_lines(
    axis: Literal["X", "Y", "Z"],
    ordinates: list[float],
) -> list[GridLine]:
    """Helper: build default-metadata GridLine records from flat ordinates."""
    return [GridLine(id=f"{axis}{i + 1}", ordinate=float(v)) for i, v in enumerate(ordinates)]


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
            [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
            [-sy, sx * cy, cx * cy],
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


def regular_grid_lines(
    count: int, spacing: float, first: float = 0.0, *, axis: str, id_style: str = "Axis"
) -> list[GridLine]:
    """``count`` equally spaced lines from ``first``, with ids in ``id_style``
    (see :func:`grid_line_ids`). Zero lines gives an empty list."""
    ids = grid_line_ids(id_style, count, axis)
    return [GridLine(id=ids[k], ordinate=first + k * spacing) for k in range(max(count, 0))]
