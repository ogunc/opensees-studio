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

Two identical channels (``CS`` or ``CU``) can be joined into one member
(``assembly``): **box** — toe to toe, the flange tips (or the lips) touching, a
closed cell ``2 bf`` wide; **back_to_back** — web against web, an I-shape
``2 bf`` wide with a web ``2 t`` thick. The dimensions stay those of one
channel. Their properties are those of the two sheets together (both
assemblies are doubly symmetric, the shear centre at the centroid); J of the
box is Bredt's closed-cell value and its Cw is taken as zero, J of the
back-to-back pair is that of two open channels and its Cw comes from the
sectorial coordinate of the two flanges, the webs acting as one (an I of
flange width ``2 bf``).

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

from opensees_studio.core._base import omit_when_default

ColdFormedProfile = Literal["CS", "CU", "ZS", "HU", "LU"]
ColdFormedAssembly = Literal["single", "box", "back_to_back"]

#: Profiles two of which can be joined into a box or a back-to-back I.
ASSEMBLY_PROFILES = frozenset({"CS", "CU"})

#: The assemblies and what the picker calls them.
ASSEMBLY_LABELS: dict[str, str] = {
    "box": "box of two Cs, toe to toe",
    "back_to_back": "I of two Cs, back to back",
}

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
    serialize_without_defaults = omit_when_default("assembly")
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
    assembly: ColdFormedAssembly = Field(
        default="single",
        description="One profile, or two channels joined toe to toe (box) or back to back.",
    )

    @model_validator(mode="after")
    def _fits(self) -> ColdFormedShape:
        if self.profile in ("CS", "ZS") and self.lip <= self.t + self.r:
            raise ValueError("A lipped profile needs a lip longer than t + r.")
        if self.profile == "HU" and self.b2 <= self.t + self.r:
            raise ValueError("A hat needs bottom flanges wider than t + r.")
        if min(self.d, self.bf) <= 2.0 * (self.t + self.r):
            raise ValueError("The depth and the flange must exceed 2 (t + r).")
        if self.assembly != "single" and self.profile not in ASSEMBLY_PROFILES:
            raise ValueError("Only channels (CS, CU) are joined into a box or back to back.")
        return self

    @property
    def single(self) -> ColdFormedShape:
        """One of the channels an assembly is made of (the shape itself when single)."""
        if self.assembly == "single":
            return self
        return self.model_copy(update={"assembly": "single"})

    def shear_areas(self) -> tuple[float, float]:
        """Shear areas along the depth and across it (``core.section_materials``).

        Along the depth: the webs, ``d·t`` each (a hat has two). Across it:
        5/6 of the horizontal plates. An approximation, not yet checked against a
        published reference for cold-formed shapes.
        """
        t = self.t
        if self.assembly != "single":
            along, across = self.single.shear_areas()
            return 2.0 * along, 2.0 * across
        if self.profile == "HU":
            return 2.0 * self.d * t, 5.0 / 6.0 * (self.bf + 2.0 * self.b2) * t
        if self.profile == "LU":
            return 5.0 / 6.0 * self.d * t, 5.0 / 6.0 * self.bf * t
        return self.d * t, 5.0 / 6.0 * 2.0 * self.bf * t

    @property
    def designation(self) -> str:
        """The AISI-style name of a shape **in inches**, e.g. ``8CS2.5x070``.

        An assembly is named after its channel: ``2-8CS2.5x070 box`` or
        ``2-8CS2.5x070 BtB``.
        """
        name = f"{self.d:g}{self.profile}{self.bf:g}x{round(self.t * 1000):03d}"
        return f"2-{name}{_ASSEMBLY_SUFFIX[self.assembly]}" if self.assembly != "single" else name

    @property
    def dimension_name(self) -> str:
        """A name from the dimensions in any unit, e.g. ``CS 203x63.5x1.78``."""
        name = f"{self.profile} {self.d:.4g}x{self.bf:.4g}x{self.t:.3g}"
        return f"2{name}{_ASSEMBLY_SUFFIX[self.assembly]}" if self.assembly != "single" else name


_ASSEMBLY_SUFFIX = {"single": "", "box": " box", "back_to_back": " BtB"}


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


def _rounded(
    points: list[tuple[float, float]], radius: float, chords_per_quarter: int = _CHORDS_PER_QUARTER
) -> np.ndarray:
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
        n = max(2, math.ceil(chords_per_quarter * sweep / (math.pi / 2.0)))
        a0 = math.atan2(*(start - centre)[::-1])
        a1 = math.atan2(*(end - centre)[::-1])
        delta = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi
        for j in range(n + 1):
            ang = a0 + delta * j / n
            out.append(centre + radius * np.array([math.cos(ang), math.sin(ang)]))
    out.append(pts[-1])
    return np.asarray(out)


def midline(shape: ColdFormedShape, chords_per_quarter: int = _CHORDS_PER_QUARTER) -> np.ndarray:
    """The midline of ``shape`` as an ``N x 2`` array, bends followed in chords.

    ``chords_per_quarter`` sets how finely a 90° bend is followed (at least two
    chords per bend); the finite strip mesh (``core.design.fsm``) uses fewer.
    For an assembly this is its first channel; :func:`midlines` gives both.
    """
    radius = shape.r + shape.t / 2.0 if shape.r > 0.0 else 0.0
    return _rounded(_corners(shape), radius, chords_per_quarter)


def _mirror(shape: ColdFormedShape) -> float:
    """The line ``x = m`` the second channel of an assembly is the mirror image about."""
    # Back to back: the web's outer face (x = 0). Box: the flange tips (x = bf).
    return 0.0 if shape.assembly == "back_to_back" else shape.bf


def midlines(
    shape: ColdFormedShape, chords_per_quarter: int = _CHORDS_PER_QUARTER
) -> list[np.ndarray]:
    """Every sheet's midline: one for a single profile, two for an assembly."""
    first = midline(shape, chords_per_quarter)
    if shape.assembly == "single":
        return [first]
    second = first.copy()
    second[:, 0] = 2.0 * _mirror(shape) - second[:, 0]
    return [first, second]


def corner_points(shape: ColdFormedShape) -> list[tuple[float, float]]:
    """The midline with sharp corners (the flats' intersections), ``(x, y)``."""
    return _corners(shape)


def outlines(shape: ColdFormedShape) -> list[list[tuple[float, float]]]:
    """A closed polygon per sheet: one for a single profile, two for an assembly."""
    first = outline(shape)
    if shape.assembly == "single":
        return [first]
    m = _mirror(shape)
    return [first, [(2.0 * m - x, y) for x, y in reversed(first)]]


def outline(shape: ColdFormedShape) -> list[tuple[float, float]]:
    """A closed polygon of the sheet (the midline offset by ±t/2), for drawing.

    For an assembly this is its first channel; :func:`outlines` gives both.
    """
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
    jx: float = 0.0
    """Monosymmetry constant for bending about x (AISI's j with the axes swapped):
    ``(∫y³ dA + ∫x²y dA) / (2 Ix) - y₀``; zero when x is an axis of symmetry."""
    jy: float = 0.0
    """AISI's j for bending about y: ``(∫x³ dA + ∫xy² dA) / (2 Iy) - x₀``
    (AISI S100-16 F2.1.2); zero when y is an axis of symmetry."""

    @property
    def x0(self) -> float:
        """Shear centre from the centroid along x (AISI's x₀, signed)."""
        return self.xs - self.xc

    @property
    def y0(self) -> float:
        """Shear centre from the centroid along y (signed)."""
        return self.ys - self.yc

    @property
    def ro(self) -> float:
        """Polar radius of gyration about the shear centre (AISI's rₒ).

        ``rₒ² = rx² + ry² + x₀² + y₀²``; ``rx² + ry²`` does not depend on the
        orientation of the axes, so this holds for a zee's inclined axes too.
        """
        return math.sqrt((self.Ix + self.Iy) / self.A + self.x0**2 + self.y0**2)

    @property
    def principal_angle(self) -> float:
        """Angle (radians, counter-clockwise) from x to the major principal axis."""
        return 0.5 * math.atan2(-2.0 * self.Ixy, self.Ix - self.Iy)

    @property
    def I1(self) -> float:
        """Major principal moment of inertia."""
        mean, half = (self.Ix + self.Iy) / 2.0, (self.Ix - self.Iy) / 2.0
        return mean + math.hypot(half, self.Ixy)

    @property
    def I2(self) -> float:
        """Minor principal moment of inertia."""
        mean, half = (self.Ix + self.Iy) / 2.0, (self.Ix - self.Iy) / 2.0
        return mean - math.hypot(half, self.Ixy)


def _sectorial(line: np.ndarray, pole: np.ndarray) -> np.ndarray:
    """Sectorial coordinate at each midline point about ``pole``, 0 at the first."""
    rel = line - pole
    swept = rel[:-1, 0] * rel[1:, 1] - rel[1:, 0] * rel[:-1, 1]
    return np.concatenate([[0.0], np.cumsum(swept)])


def properties(shape: ColdFormedShape) -> ColdFormedProperties:
    """The gross properties of ``shape`` (AISI linear method)."""
    if shape.assembly != "single":
        return _assembly_properties(shape)
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

    def cubic_integral(f_a: np.ndarray, f_b: np.ndarray, g_a: np.ndarray, g_b: np.ndarray,
                       h_a: np.ndarray, h_b: np.ndarray) -> float:  # fmt: skip
        """∫ f g h t ds for f, g and h linear along each chord (exact)."""
        ends = 3.0 * f_a * g_a * h_a + 3.0 * f_b * g_b * h_b
        mixed = (
            f_a * g_a * h_b + f_a * g_b * h_a + f_b * g_a * h_a
            + f_a * g_b * h_b + f_b * g_a * h_b + f_b * g_b * h_a
        )  # fmt: skip
        return float(t * (lengths / 12.0 * (ends + mixed)).sum())

    x3 = cubic_integral(xa, xb, xa, xb, xa, xb)
    xy2 = cubic_integral(xa, xb, ya, yb, ya, yb)
    y3 = cubic_integral(ya, yb, ya, yb, ya, yb)
    x2y = cubic_integral(xa, xb, xa, xb, ya, yb)
    jy = (x3 + xy2) / (2.0 * iy) - (float(xs) - xc)
    jx = (y3 + x2y) / (2.0 * ix) - (float(ys) - yc)
    return ColdFormedProperties(
        area, xc, yc, ix, iy, ixy, j, cw, float(xs), float(ys), jx=float(jx), jy=float(jy)
    )


def _assembly_properties(shape: ColdFormedShape) -> ColdFormedProperties:
    """Two channels together: doubly symmetric, the shear centre at the centroid."""
    t = shape.t
    lines = midlines(shape)
    a_pts = np.vstack([line[:-1] for line in lines])
    b_pts = np.vstack([line[1:] for line in lines])
    lengths = np.linalg.norm(b_pts - a_pts, axis=1)
    area = float(t * lengths.sum())
    mids = (a_pts + b_pts) / 2.0
    xc = float(t * (lengths * mids[:, 0]).sum() / area)
    yc = float(t * (lengths * mids[:, 1]).sum() / area)

    def second_moment(f_a: np.ndarray, f_b: np.ndarray, g_a: np.ndarray, g_b: np.ndarray) -> float:
        return float(
            t * (lengths / 6.0 * (2 * f_a * g_a + f_a * g_b + f_b * g_a + 2 * f_b * g_b)).sum()
        )

    xa, ya = a_pts[:, 0] - xc, a_pts[:, 1] - yc
    xb, yb = b_pts[:, 0] - xc, b_pts[:, 1] - yc
    ix = second_moment(ya, yb, ya, yb)
    iy = second_moment(xa, xb, xa, xb)
    ixy = second_moment(xa, xb, ya, yb)
    single = properties(shape.single)
    if shape.assembly == "box":
        # Bredt: the cell between the two webs' and the flanges' midlines, its
        # four web-to-flange corners rounded to r + t/2; the lips stay open.
        radius = shape.r + t / 2.0 if shape.r > 0.0 else 0.0
        width, height = 2.0 * shape.bf - t, shape.d - t
        enclosed = width * height - (4.0 - math.pi) * radius**2
        perimeter = 2.0 * (width + height) - (8.0 - 2.0 * math.pi) * radius
        j = 4.0 * enclosed**2 * t / perimeter
        cw = 0.0
    else:
        j = 2.0 * single.J
        # The two webs fastened together act as one web (no slip between them),
        # so the sectorial coordinate is measured from each web's line: zero
        # along the web, zero where it crosses mid-depth (the axis of symmetry),
        # which is the doubly symmetric I of flange width 2 bf.
        cw = 0.0
        for line in lines:
            web = next(
                k
                for k in range(len(line) - 1)
                if (line[k, 1] - yc) * (line[k + 1, 1] - yc) <= 0.0
                and abs(line[k + 1, 1] - line[k, 1]) > 0.0
                and abs(line[k + 1, 0] - line[k, 0]) < 1e-12
            )
            omega = _sectorial(line, np.array([line[web, 0], yc]))
            frac = (yc - line[web, 1]) / (line[web + 1, 1] - line[web, 1])
            omega = omega - (omega[web] + frac * (omega[web + 1] - omega[web]))
            seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
            w_a, w_b = omega[:-1], omega[1:]
            cw += float(t * (seg / 3.0 * (w_a**2 + w_a * w_b + w_b**2)).sum())
    return ColdFormedProperties(area, xc, yc, ix, iy, ixy, float(j), float(cw), xc, yc)


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


def assemblies(sizes: list[ColdFormedShape]) -> list[ColdFormedShape]:
    """Every channel of ``sizes`` as a box and as a back-to-back pair."""
    return [
        size.model_copy(update={"assembly": assembly})
        for assembly in ("box", "back_to_back")
        for size in sizes
        if size.profile in ASSEMBLY_PROFILES
    ]


__all__ = [
    "ASSEMBLY_LABELS",
    "ASSEMBLY_PROFILES",
    "INSIDE_RADIUS_IN",
    "PROFILE_LABELS",
    "ColdFormedAssembly",
    "ColdFormedProfile",
    "ColdFormedProperties",
    "ColdFormedShape",
    "assemblies",
    "corner_points",
    "designations",
    "midline",
    "midlines",
    "outline",
    "outlines",
    "properties",
    "scaled",
]
