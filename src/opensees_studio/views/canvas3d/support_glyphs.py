"""Support and support-spring symbols, coloured by the axis each part holds.

Pure geometry (NumPy only), so the vocabulary is testable without a render
window. A symbol is built around a joint at the origin with ``size`` as its
unit; the renderer translates one copy to every joint with the same pattern.

Shape says *what kind* of support it is, colour says *which axis*:

- Every part takes the colour of the DOF it holds, in the origin triad's
  language: X red, Y green, Z blue. A translation is held by contact (a hatched
  floor or wall, the sides of a triangle or pyramid, the rollers that stop a
  slide); a rotation by a block, a plate or a clamp square. A rotation about an
  axis uses that axis' colour (Ry, the rotation of a 2D frame, is green).
- 2D models (X-Z plane): one textbook symbol per joint — fixed block, pin
  triangle, roller, guide (plate on rollers), clamp square — and nothing in the
  Y-Z plane.
- 3D models: one solid for the usual patterns (a box when fixed, a pyramid when
  pinned, a pyramid on balls for a vertical roller, on rails for a roller guided
  along X or Y); any other pattern falls back to the 2D symbol in each
  elevation plane (X-Z from Ux/Uz/Ry, Y-Z from Uy/Uz/Rx) plus a horizontal
  square for Rz, so no support is ever left without a symbol.
- Springs (:func:`spring_glyph`): a zigzag along each sprung translation that
  ends on a hatched anchor, a spiral around each sprung rotation, in the same
  axis colours. A DOF that is also restrained ignores its spring, so it is not
  drawn.

Each cell carries a colour slot: ``X``, ``Y``, ``Z`` for lines, the matching
``X_FILL``, ``Y_FILL``, ``Z_FILL`` for faces, and ``OUTLINE`` for the edges of a
3D solid, whose faces may show two different axes.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

#: Colour slots (``cell_data`` values); the renderer maps them to the style.
X, Y, Z, X_FILL, Y_FILL, Z_FILL, OUTLINE = range(7)
N_COLOR_SLOTS = 7

Vec = tuple[float, float, float]
#: A point: a tuple or a NumPy vector.
Pt = Sequence[float] | np.ndarray


@dataclass(frozen=True)
class Glyph:
    """Line and face cells of one symbol, each with a colour slot."""

    points: np.ndarray  # (n, 3)
    lines: np.ndarray  # VTK cell array: 2, i, j, 2, ...
    faces: np.ndarray  # VTK cell array: k, i0..ik-1, ...
    line_colors: np.ndarray  # one slot per line
    face_colors: np.ndarray  # one slot per face

    @property
    def n_lines(self) -> int:
        return len(self.line_colors)

    @property
    def n_faces(self) -> int:
        return len(self.face_colors)

    @property
    def colors(self) -> np.ndarray:
        """Slots in VTK cell order (lines before polygons)."""
        return np.concatenate([self.line_colors, self.face_colors]).astype(np.int8)

    def is_empty(self) -> bool:
        return not len(self.points)


class _Builder:
    def __init__(self, size: float) -> None:
        self.size = size
        self.points: list[Vec] = []
        self.lines: list[tuple[int, int]] = []
        self.line_colors: list[int] = []
        self.faces: list[list[int]] = []
        self.face_colors: list[int] = []

    def _add(self, p: Pt) -> int:
        s = self.size
        self.points.append((float(p[0]) * s, float(p[1]) * s, float(p[2]) * s))
        return len(self.points) - 1

    def seg(self, a: Pt, b: Pt, color: int) -> None:
        self.lines.append((self._add(a), self._add(b)))
        self.line_colors.append(color)

    def polyline(self, pts: Sequence[Pt], color: int) -> None:
        for a, b in itertools.pairwise(pts):
            self.seg(a, b, color)

    def face(self, pts: Sequence[Pt], fill: int, outline: int | None = None) -> None:
        self.faces.append([self._add(p) for p in pts])
        self.face_colors.append(fill)
        if outline is not None:
            self.polyline([*pts, pts[0]], outline)

    def build(self) -> Glyph:
        points = np.asarray(self.points, dtype=float).reshape(-1, 3)
        lines = np.asarray([v for i, j in self.lines for v in (2, i, j)], dtype=np.int64)
        faces = np.asarray([v for f in self.faces for v in (len(f), *f)], dtype=np.int64)
        return Glyph(
            points,
            lines,
            faces,
            np.asarray(self.line_colors, dtype=np.int8),
            np.asarray(self.face_colors, dtype=np.int8),
        )


def _fill(color: int) -> int:
    return color + 3


# ── 2D vocabulary, in one elevation plane ───────────────────────────────────


class _Plane:
    """Draws in a vertical plane: ``h`` along ``e_h`` (X or Y), ``v`` along Z.

    ``h_color`` is the colour of the horizontal translation; ``r_color`` that of
    the rotation that turns in this plane (Ry for X-Z, Rx for Y-Z).
    """

    def __init__(self, b: _Builder, e_h: Vec, h_color: int, r_color: int) -> None:
        self.b = b
        self.e_h = np.asarray(e_h, dtype=float)
        self.h_color = h_color
        self.r_color = r_color
        self.turned = False  # True: "down" becomes "toward -h" (a wall)

    def p(self, h: float, v: float) -> np.ndarray:
        if self.turned:
            h, v = v, -h
        return np.asarray(h * self.e_h + np.array((0.0, 0.0, v)), dtype=float)

    def seg(self, h1: float, v1: float, h2: float, v2: float, color: int) -> None:
        self.b.seg(self.p(h1, v1), self.p(h2, v2), color)

    def face(self, pts: Sequence[tuple[float, float]], color: int) -> None:
        self.b.face([self.p(h, v) for h, v in pts], _fill(color), color)

    def circle(self, h: float, v: float, r: float, color: int) -> None:
        angles = np.linspace(0.0, 2.0 * math.pi, 13)[:-1]
        self.face([(h + r * math.cos(a), v + r * math.sin(a)) for a in angles], color)

    def ground(self, v: float, half: float, color: int, hatch: bool = True) -> None:
        """A floor at ``v`` (a wall when turned), hatched on the far side."""
        self.seg(-half, v, half, v, color)
        if not hatch:
            return
        for k in range(5):
            h = -half + 2.0 * half * (k + 0.5) / 5.0
            self.seg(h + 0.1, v, h - 0.1, v - 0.22, color)


def _planar(b: _Builder, plane: _Plane, h_held: bool, v_held: bool, r_held: bool) -> None:
    """The 2D symbol of one plane: block, pin, roller, guide or clamp."""
    hc, rc = plane.h_color, plane.r_color
    if h_held and v_held and r_held:  # fixed: block on a hatched floor
        plane.face([(-0.7, 0.0), (0.7, 0.0), (0.7, -0.35), (-0.7, -0.35)], rc)
        plane.seg(-0.7, 0.0, -0.7, -0.35, hc)
        plane.seg(0.7, 0.0, 0.7, -0.35, hc)
        plane.ground(-0.35, 0.85, Z)
        return
    if h_held and v_held:  # pin: triangle on a hatched floor
        plane.face([(0.0, 0.0), (-0.5, -0.75), (0.5, -0.75)], hc)
        plane.ground(-0.75, 0.8, Z)
        return
    if r_held and (h_held or v_held):  # guide: plate on rollers, slides, does not turn
        held = Z if v_held else hc
        plane.turned = not v_held
        plane.face([(-0.55, 0.0), (0.55, 0.0), (0.55, -0.22), (-0.55, -0.22)], rc)
        plane.circle(-0.3, -0.35, 0.12, held)
        plane.circle(0.3, -0.35, 0.12, held)
        plane.ground(-0.47, 0.75, held)
        plane.turned = False
        return
    if v_held or h_held:  # roller: triangle on wheels
        held = Z if v_held else hc
        plane.turned = not v_held
        plane.face([(0.0, 0.0), (-0.45, -0.58), (0.45, -0.58)], held)
        plane.circle(-0.25, -0.7, 0.11, held)
        plane.circle(0.25, -0.7, 0.11, held)
        plane.ground(-0.82, 0.75, held)
        plane.turned = False
        return
    if r_held:  # rotation only: a clamp square at the joint
        plane.face([(-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2)], rc)


# ── 3D solids ───────────────────────────────────────────────────────────────


def _plate(b: _Builder, z: float, half: float = 0.65) -> None:
    """The ground under a 3D support: a hatched square outline, no fill."""
    corners = [(-half, -half, z), (half, -half, z), (half, half, z), (-half, half, z)]
    b.polyline([*corners, corners[0]], Z)
    for k in range(4):
        t = -half + 2.0 * half * (k + 0.5) / 4.0
        b.seg((t, half, z), (t - 0.12, half, z - 0.2), Z)
        b.seg((half, t, z), (half, t - 0.12, z - 0.2), Z)
        b.seg((t, -half, z), (t - 0.12, -half, z - 0.2), Z)
        b.seg((-half, t, z), (-half, t - 0.12, z - 0.2), Z)


def _box(b: _Builder, z0: float, z1: float, half: float = 0.45) -> None:
    h = half
    for sx in (-h, h):  # faces whose normal is X
        b.face([(sx, -h, z0), (sx, h, z0), (sx, h, z1), (sx, -h, z1)], X_FILL)
    for sy in (-h, h):  # faces whose normal is Y
        b.face([(-h, sy, z0), (h, sy, z0), (h, sy, z1), (-h, sy, z1)], Y_FILL)
    for z in (z0, z1):
        b.face([(-h, -h, z), (h, -h, z), (h, h, z), (-h, h, z)], Z_FILL)
    for z in (z0, z1):
        b.polyline([(-h, -h, z), (h, -h, z), (h, h, z), (-h, h, z), (-h, -h, z)], OUTLINE)
    for x, y in ((-h, -h), (h, -h), (h, h), (-h, h)):
        b.seg((x, y, z0), (x, y, z1), OUTLINE)


def _pyramid(b: _Builder, zb: float, ux: bool, uy: bool, half: float = 0.45) -> None:
    """Apex at the joint; a face takes the colour of the translation it stops."""
    h = half
    apex = (0.0, 0.0, 0.0)
    base = [(-h, -h, zb), (h, -h, zb), (h, h, zb), (-h, h, zb)]
    x_fill = X_FILL if ux else Z_FILL
    y_fill = Y_FILL if uy else Z_FILL
    b.face([apex, base[1], base[2]], x_fill)  # +X
    b.face([apex, base[3], base[0]], x_fill)  # -X
    b.face([apex, base[2], base[3]], y_fill)  # +Y
    b.face([apex, base[0], base[1]], y_fill)  # -Y
    b.polyline([*base, base[0]], OUTLINE)
    for corner in base:
        b.seg(apex, corner, OUTLINE)


def _ball(b: _Builder, c: Vec, r: float) -> None:
    """A small octahedron: a ball that reads from every side."""
    x, y, z = c
    top, bottom = (x, y, z + r), (x, y, z - r)
    ring = [(x + r, y, z), (x, y + r, z), (x - r, y, z), (x, y - r, z)]
    for k in range(4):
        a, c2 = ring[k], ring[(k + 1) % 4]
        b.face([top, a, c2], Z_FILL)
        b.face([bottom, c2, a], Z_FILL)


def _rails(b: _Builder, zc: float, free: str, color: int, half: float = 0.42) -> None:
    """Two roller bars across the free direction: they roll along ``free``."""
    r = 0.07
    for o in (-0.27, 0.27):
        if free == "y":  # rolls along Y: the bars run along X, offset in Y
            lo, hi = (-half, o - r, zc - r), (half, o + r, zc + r)
        else:
            lo, hi = (o - r, -half, zc - r), (o + r, half, zc + r)
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        quads = (
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],
            [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
        )
        for quad in quads:
            b.face(quad, _fill(color))


def _torsion_square(b: _Builder) -> None:
    s = 0.22
    b.face([(-s, -s, 0.0), (s, -s, 0.0), (s, s, 0.0), (-s, s, 0.0)], Z_FILL, Z)


def support_glyph(
    translations: Sequence[bool],
    rotations: Sequence[bool],
    size: float,
    *,
    planar: bool = False,
) -> Glyph:
    """The symbol for a joint held in ``translations`` (Ux, Uy, Uz) and
    ``rotations`` (Rx, Ry, Rz).

    ``planar`` draws the 2D (X-Z) vocabulary only, for a 2D model; Uy, Rx and
    Rz are then ignored.
    """
    if len(translations) != 3 or len(rotations) != 3:
        raise ValueError("translations and rotations need one flag per global axis")
    ux, uy, uz = (bool(v) for v in translations)
    rx, ry, rz = (bool(v) for v in rotations)
    b = _Builder(size)
    xz = _Plane(b, (1.0, 0.0, 0.0), X, Y)
    if planar:
        _planar(b, xz, ux, uz, ry)
        return b.build()

    no_rot = not (rx or ry)
    if ux and uy and uz and rx and ry:  # fixed (Rz shown by the box itself)
        _plate(b, -0.7)
        _box(b, -0.7, 0.0)
    elif ux and uy and uz and no_rot:  # pinned
        _plate(b, -0.75)
        _pyramid(b, -0.75, True, True)
        if rz:
            _torsion_square(b)
    elif uz and no_rot and not rz and not (ux and uy):  # vertical roller, maybe guided
        _plate(b, -0.82)
        _pyramid(b, -0.6, ux, uy)
        if ux:
            _rails(b, -0.71, "y", X)
        elif uy:
            _rails(b, -0.71, "x", Y)
        else:
            for x, y in ((-0.3, -0.3), (0.3, -0.3), (0.3, 0.3), (-0.3, 0.3)):
                _ball(b, (x, y, -0.71), 0.1)
    else:  # anything else: the 2D symbol in each elevation plane
        _planar(b, xz, ux, uz, ry)
        _planar(b, _Plane(b, (0.0, 1.0, 0.0), Y, X), uy, uz, rx)
        if rz:
            _torsion_square(b)
    return b.build()


# ── springs ─────────────────────────────────────────────────────────────────

_AXES: tuple[Vec, Vec, Vec] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _zigzag(b: _Builder, axis: int, length: float = 1.3) -> None:
    """From the joint toward ``-axis``, ending on a hatched anchor."""
    d = np.asarray(_AXES[axis])
    side = np.asarray(_AXES[0] if axis == 2 else _AXES[2])  # stays in the X-Z plane for Ux/Uz
    pts = [np.zeros(3), -d * 0.15 * length]
    for k in range(8):
        f = 0.15 + 0.7 * (k + 0.5) / 8.0
        pts.append(-d * f * length + side * 0.2 * (1 if k % 2 == 0 else -1))
    end = -d * length
    pts += [-d * 0.85 * length, end]
    b.polyline([tuple(p) for p in pts], axis)
    b.seg(end - side * 0.35, end + side * 0.35, axis)
    for k in range(3):
        o = end + side * (-0.24 + 0.24 * k)
        b.seg(o + side * 0.08, o - side * 0.08 - d * 0.18, axis)


def _spiral(b: _Builder, axis: int) -> None:
    """A spiral in the plane normal to ``axis``, centred on the joint."""
    u, w = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[axis]
    pts = []
    for k in range(48):
        f = k / 47.0
        angle = f * 1.6 * 2.0 * math.pi + math.pi / 2.0
        r = 0.08 + 0.32 * f
        p = [0.0, 0.0, 0.0]
        p[u] = r * math.cos(angle)
        p[w] = r * math.sin(angle)
        pts.append(tuple(p))
    b.polyline(pts, axis)


def spring_glyph(sprung: Sequence[bool], size: float) -> Glyph:
    """Zigzags and spirals for the sprung DOFs (Ux, Uy, Uz, Rx, Ry, Rz).

    Pass only the DOFs that are sprung *and* free: a restrained DOF ignores its
    spring.
    """
    if len(sprung) != 6:
        raise ValueError("sprung needs one flag per DOF (Ux, Uy, Uz, Rx, Ry, Rz)")
    b = _Builder(size)
    for axis in range(3):
        if sprung[axis]:
            _zigzag(b, axis)
    for axis in range(3):
        if sprung[3 + axis]:
            _spiral(b, axis)
    return b.build()
