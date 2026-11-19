"""Cold-formed steel shapes (AISI): lipped and plain channels, zees, hats and angles.

A cold-formed member is a sheet bent along its length, so its properties come
from its **midline**: the centre of the sheet, a chain of flat elements joined
by bends of inside radius ``r``. This is the linear method of the AISI Manual:
every property is a line integral along the midline times the thickness
``t``; the bends are arcs of radius ``r + t/2``, followed in short chords.

Dimensions are out-to-out, as a manufacturer lists them:

======  ===========================  =========================================
Code    Shape                        Dimensions
======  ===========================  =========================================
``CS``  C with lips (C-stud, purlin) depth ``d``, flange ``bf``, lip ``lip``
``CU``  C without lips (track)       depth ``d``, flange ``bf``
``ZS``  Z with lips (purlin)         depth ``d``, flange ``bf``, lip ``lip``
                                     at ``lip_angle`` to the flange (AISI 50°)
``HU``  Hat                          depth ``d``, top ``bf``, bottom flanges
                                     ``b2`` each
``LU``  Angle, equal or unequal      legs ``d`` (vertical) and ``bf``
======  ===========================  =========================================

:func:`properties` returns A, the centroid, Ix, Iy, Ixy about the centroid
(``x`` across the depth, ``y`` along it), J = Σ L t³/3, the shear centre and
the warping constant Cw, from the sectorial coordinates of the midline. The
elastic section (``core.section_materials``) takes Ix as the strong axis; a
zee's product of inertia is shown but OpenSees' elastic section has none, as
for every section here.

:func:`designations` generates a list of common sizes **by formula** (depth,
flange, lip and gauge in inches, named the AISI way: ``8CS2.5x070`` is an 8 in
lipped C with 2.5 in flanges, 0.070 in thick). Nothing is copied from the AISI
Manual's tables; the properties are always computed here.

No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, model_validator

ColdFormedProfile = Literal["CS", "CU", "ZS", "HU", "LU"]

#: The profiles and what the picker calls them.
PROFILE_LABELS: dict[str, str] = {
    "CS": "C with lips (purlin, stud)",
    "CU": "C without lips (track)",
    "ZS": "Z with lips (purlin)",
    "HU": "Hat",
    "LU": "Angle",
}

#: Chords per 90° of bend when the midline is followed.
_CHORDS_PER_QUARTER = 6


class ColdFormedShape(BaseModel):
    """A cold-formed profile by its out-to-out dimensions (a section's drawing hint)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["cold_formed"] = "cold_formed"
    profile: ColdFormedProfile
    d: PositiveFloat = Field(..., description="Overall depth (web, out-to-out).")
    bf: PositiveFloat = Field(
        ..., description="Flange width out-to-out (a hat's top, an angle's other leg)."
    )
    t: PositiveFloat = Field(..., description="Sheet thickness.")
    r: float = Field(default=0.0, ge=0.0, description="Inside bend radius.")
    lip: float = Field(default=0.0, ge=0.0, description="Lip length out-to-out (CS, ZS).")
    lip_angle: float = Field(
        default=90.0, gt=0.0, le=90.0, description="Lip angle to the flange, degrees (ZS)."
    )
    b2: float = Field(default=0.0, ge=0.0, description="A hat's bottom flange width, each side.")

    @model_validator(mode="after")
    def _fits(self) -> ColdFormedShape:
        if self.profile in ("CS", "ZS") and self.lip <= self.t + self.r:
            raise ValueError("A lipped profile needs a lip longer than t + r.")
        if self.profile == "HU" and self.b2 <= self.t + self.r:
            raise ValueError("A hat needs bottom flanges wider than t + r.")
        if min(self.d, self.bf) <= 2.0 * (self.t + self.r):
            raise ValueError("The depth and the flange must exceed 2 (t + r).")
        return self

    def shear_areas(self) -> tuple[float, float]:
        """Shear areas along the depth and across it (``core.section_materials``).

        Along the depth: the webs, ``d·t`` each (a hat has two). Across it:
        5/6 of the horizontal plates. An approximation, not yet checked against a
        published reference for cold-formed shapes.
        """
        t = self.t
        if self.profile == "HU":
            return 2.0 * self.d * t, 5.0 / 6.0 * (self.bf + 2.0 * self.b2) * t
        if self.profile == "LU":
            return 5.0 / 6.0 * self.d * t, 5.0 / 6.0 * self.bf * t
        return self.d * t, 5.0 / 6.0 * 2.0 * self.bf * t

    @property
    def designation(self) -> str:
        """The AISI-style name of a shape **in inches**, e.g. ``8CS2.5x070``."""
        return f"{self.d:g}{self.profile}{self.bf:g}x{round(self.t * 1000):03d}"

    @property
    def dimension_name(self) -> str:
        """A name from the dimensions in any unit, e.g. ``CS 203x63.5x1.78``."""
        return f"{self.profile} {self.d:.4g}x{self.bf:.4g}x{self.t:.3g}"


# ─────────────────────────────── midline ───────────────────────────────
def _corners(shape: ColdFormedShape) -> list[tuple[float, float]]:
    """The midline with sharp corners, ``(x, y)``: x across the depth, y along it."""
    t = shape.t
    h = shape.d / 2.0 - t / 2.0  # flange midline height from mid-depth
    if shape.profile in ("CS", "CU"):
        web = t / 2.0
        if shape.profile == "CU":
            # A plain flange ends at its free edge, bf from the web's outer face.
            return [(shape.bf, h), (web, h), (web, -h), (shape.bf, -h)]
        tip = shape.bf - t / 2.0  # the lip's midline
        lip_end = shape.d / 2.0 - shape.lip
        return [(tip, lip_end), (tip, h), (web, h), (web, -h), (tip, -h), (tip, -lip_end)]
    if shape.profile == "ZS":
        tip = shape.bf - t  # web midline at x = 0, flanges out-to-out from -t/2
        angle = math.radians(shape.lip_angle)
        reach = shape.lip - t / 2.0
        dx, dy = reach * math.cos(angle), reach * math.sin(angle)
        return [
            (tip + dx, h - dy),
            (tip, h),
            (0.0, h),
            (0.0, -h),
            (-tip, -h),
            (-tip - dx, -h + dy),
        ]
    if shape.profile == "HU":
        half = shape.bf / 2.0 - t / 2.0
        out = half - t / 2.0 + shape.b2  # b2 from the web's inner face to the free edge
        return [(-out, -h), (-half, -h), (-half, h), (half, h), (half, -h), (out, -h)]
    # LU: the corner at the origin, one leg up and one across.
    return [(0.0, shape.d - t / 2.0), (0.0, 0.0), (shape.bf - t / 2.0, 0.0)]


def _rounded(points: list[tuple[float, float]], radius: float) -> np.ndarray:
    """The polyline with every interior corner replaced by an arc of ``radius``."""
    pts = np.asarray(points, dtype=float)
    if radius <= 0.0 or len(pts) < 3:
        return pts
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        a, b, c = pts[k - 1], pts[k], pts[k + 1]
        u = (a - b) / np.linalg.norm(a - b)
        v = (c - b) / np.linalg.norm(c - b)
        turn = math.acos(float(np.clip(np.dot(u, v), -1.0, 1.0)))  # interior angle
        back = radius / math.tan(turn / 2.0)  # tangent length from the corner
        start, end = b + u * back, b + v * back
        bisector = (u + v) / np.linalg.norm(u + v)
        centre = b + bisector * radius / math.sin(turn / 2.0)
        sweep = math.pi - turn
        n = max(2, math.ceil(_CHORDS_PER_QUARTER * sweep / (math.pi / 2.0)))
        a0 = math.atan2(*(start - centre)[::-1])
        a1 = math.atan2(*(end - centre)[::-1])
        delta = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi
        for j in range(n + 1):
            ang = a0 + delta * j / n
            out.append(centre + radius * np.array([math.cos(ang), math.sin(ang)]))
    out.append(pts[-1])
    return np.asarray(out)


def midline(shape: ColdFormedShape) -> np.ndarray:
    """The midline of ``shape`` as an ``N x 2`` array, bends followed in chords."""
    return _rounded(_corners(shape), shape.r + shape.t / 2.0 if shape.r > 0.0 else 0.0)


def outline(shape: ColdFormedShape) -> list[tuple[float, float]]:
    """A closed polygon of the sheet (the midline offset by ±t/2), for drawing."""
    line = midline(shape)
    half = shape.t / 2.0
    normals = []
    for k in range(len(line)):
        a = line[max(k - 1, 0)]
        b = line[min(k + 1, len(line) - 1)]
        tangent = (b - a) / np.linalg.norm(b - a)
        normals.append(np.array([-tangent[1], tangent[0]]))
    left = [tuple(p + n * half) for p, n in zip(line, normals, strict=True)]
    right = [tuple(p - n * half) for p, n in zip(line, normals, strict=True)]
    return [(float(x), float(y)) for x, y in [*left, *reversed(right)]]


# ────────────────────────────── properties ──────────────────────────────
@dataclass(frozen=True)
class ColdFormedProperties:
    """Gross properties by the linear method, about the centroid (x across, y along the depth)."""

    A: float
    xc: float
    yc: float
    Ix: float
    Iy: float
    Ixy: float
    J: float
    Cw: float
    xs: float
    """Shear centre, in the shape's coordinates."""
    ys: float

    @property
    def x0(self) -> float:
        """Shear centre from the centroid along x (AISI's x₀, signed)."""
        return self.xs - self.xc


def _sectorial(line: np.ndarray, pole: np.ndarray) -> np.ndarray:
    """Sectorial coordinate at each midline point about ``pole``, 0 at the first."""
    rel = line - pole
    swept = rel[:-1, 0] * rel[1:, 1] - rel[1:, 0] * rel[:-1, 1]
    return np.concatenate([[0.0], np.cumsum(swept)])


def properties(shape: ColdFormedShape) -> ColdFormedProperties:
    """The gross properties of ``shape`` (AISI linear method)."""
    line = midline(shape)
    t = shape.t
    a_pts, b_pts = line[:-1], line[1:]
    lengths = np.linalg.norm(b_pts - a_pts, axis=1)
    area = float(t * lengths.sum())
    mids = (a_pts + b_pts) / 2.0
    xc = float(t * (lengths * mids[:, 0]).sum() / area)
    yc = float(t * (lengths * mids[:, 1]).sum() / area)
    xa, ya = a_pts[:, 0] - xc, a_pts[:, 1] - yc
    xb, yb = b_pts[:, 0] - xc, b_pts[:, 1] - yc

    def line_integral(f_a: np.ndarray, f_b: np.ndarray, g_a: np.ndarray, g_b: np.ndarray) -> float:
        """∫ f g t ds for f and g linear along each chord (exact)."""
        return float(
            t * (lengths / 6.0 * (2 * f_a * g_a + f_a * g_b + f_b * g_a + 2 * f_b * g_b)).sum()
        )

    ix = line_integral(ya, yb, ya, yb)
    iy = line_integral(xa, xb, xa, xb)
    ixy = line_integral(xa, xb, ya, yb)
    j = float((lengths * t**3).sum() / 3.0)

    # Shear centre from the sectorial coordinate about the centroid (Vlasov):
    # the pole that makes ∫ω x dA and ∫ω y dA vanish.
    omega = _sectorial(line, np.array([xc, yc]))
    w_a, w_b = omega[:-1], omega[1:]
    i_wx = line_integral(w_a, w_b, ya, yb)  # ∫ ω y dA
    i_wy = line_integral(w_a, w_b, xa, xb)  # ∫ ω x dA
    det = ix * iy - ixy**2
    xs = xc + (iy * i_wx - ixy * i_wy) / det
    ys = yc - (ix * i_wy - ixy * i_wx) / det

    # Warping constant: the sectorial coordinate about the shear centre,
    # normalised to a zero mean, squared over the area.
    omega_s = _sectorial(line, np.array([xs, ys]))
    s_a, s_b = omega_s[:-1], omega_s[1:]
    mean = float(t * (lengths * (s_a + s_b) / 2.0).sum() / area)
    s_a, s_b = s_a - mean, s_b - mean
    cw = line_integral(s_a, s_b, s_a, s_b)
    return ColdFormedProperties(area, xc, yc, ix, iy, ixy, j, cw, float(xs), float(ys))


# ──────────────────────────── designations ────────────────────────────
#: Inside bend radius of the generated sizes, inches (a common roll-forming radius).
INSIDE_RADIUS_IN = 0.1875

#: Common gauges, inches: 0.048, 0.059, 0.070, 0.085 and 0.105 (18 to 12 gauge).
_GAUGES = (0.048, 0.059, 0.070, 0.085, 0.105)


def _lip_for(flange: float) -> float:
    """A lip in proportion to the flange: about 0.3 bf, rounded to 1/8 in, at least 1/2 in."""
    return max(0.5, round(0.3 * flange * 8) / 8)


def designations() -> list[ColdFormedShape]:
    """Common sizes, in inches, generated by formula (none is read from a table)."""
    out: list[ColdFormedShape] = []
    r = INSIDE_RADIUS_IN
    c_sizes = {4.0: (1.625, 2.0), 6.0: (1.625, 2.0, 2.5), 8.0: (2.0, 2.5, 3.0),
               10.0: (2.5, 3.0, 3.5), 12.0: (2.5, 3.0, 3.5)}  # fmt: skip
    for depth, flanges in c_sizes.items():
        for flange in flanges:
            for gauge in _GAUGES:
                out.append(
                    ColdFormedShape(
                        profile="CS", d=depth, bf=flange, t=gauge, r=r, lip=_lip_for(flange)
                    )
                )
    for depth in (4.0, 6.0, 8.0, 10.0, 12.0):
        for flange in (1.25, 2.0):
            for gauge in _GAUGES[:4]:
                out.append(ColdFormedShape(profile="CU", d=depth, bf=flange, t=gauge, r=r))
    z_sizes = {
        6.0: (2.0, 2.25),
        7.0: (2.25, 2.5),
        8.0: (2.25, 2.5),
        10.0: (2.5, 3.0),
        12.0: (2.5, 3.0),
    }
    for depth, flanges in z_sizes.items():
        for flange in flanges:
            for gauge in _GAUGES[1:]:
                out.append(
                    ColdFormedShape(
                        profile="ZS", d=depth, bf=flange, t=gauge, r=r, lip=0.91, lip_angle=50.0
                    )
                )
    for depth, top, bottom in (
        (1.5, 1.25, 0.75),
        (2.0, 1.5, 1.0),
        (3.0, 2.0, 1.25),
        (4.0, 2.5, 1.5),
    ):
        for gauge in _GAUGES[:3]:
            out.append(ColdFormedShape(profile="HU", d=depth, bf=top, t=gauge, r=r, b2=bottom))
    for leg in (1.5, 2.0, 2.5, 3.0, 4.0):
        for gauge in _GAUGES:
            out.append(ColdFormedShape(profile="LU", d=leg, bf=leg, t=gauge, r=r))
    return out


def scaled(shape: ColdFormedShape, factor: float) -> ColdFormedShape:
    """``shape`` with every length multiplied by ``factor`` (inches to project units)."""
    return shape.model_copy(
        update={name: getattr(shape, name) * factor for name in ("d", "bf", "t", "r", "lip", "b2")}
    )


__all__ = [
    "INSIDE_RADIUS_IN",
    "PROFILE_LABELS",
    "ColdFormedProfile",
    "ColdFormedProperties",
    "ColdFormedShape",
    "designations",
    "midline",
    "outline",
    "properties",
    "scaled",
]
