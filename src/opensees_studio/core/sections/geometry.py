"""Plane geometry of a cross-section: regions, their properties and their fibres.

A section is a list of regions in the section's local ``(y, z)`` plane — closed
polygons and circles — each solid or a hole. :func:`section_properties` gives
the area, the centroid, the second moments about the centroidal axes (OpenSees'
``Iz = ∫ y² dA`` and ``Iy = ∫ z² dA``), the product ``Iyz``, the principal
moments and their angle, the extreme fibres and elastic moduli, the plastic
moduli. :func:`torsion_constant` solves Saint-Venant's torsion for ``J``, and
:func:`region_fibres` turns the regions into fibres for a ``FiberSection``.

Polygons use the shoelace sums, exact for straight edges; circles use their
closed forms. The solids are added and the holes subtracted, which is exact
when the solids do not overlap and every hole lies inside them;
:func:`section_properties` notes by how much of the area a drawing breaks that
(sampled on a grid).

The torsional constant has no closed form for an arbitrary shape: it is solved
numerically (see :func:`torsion_constant`), within a fraction of a per cent for
compact and hollow shapes and a few per cent for thin open ones.

No Qt.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class PolygonRegion:
    """A closed polygon by its vertices in ``(y, z)``; the last edge closes it."""

    points: tuple[Point, ...]
    hole: bool = False

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("A polygon needs at least three vertices.")


@dataclass(frozen=True)
class CircleRegion:
    """A full circle of ``radius`` centred at ``(y, z)``."""

    y: float
    z: float
    radius: float
    hole: bool = False

    def __post_init__(self) -> None:
        if self.radius <= 0.0:
            raise ValueError("A circle needs a positive radius.")


Region = PolygonRegion | CircleRegion


def rectangle(
    width: float, height: float, y: float = 0.0, z: float = 0.0, *, hole: bool = False
) -> PolygonRegion:
    """A rectangle ``height`` along y by ``width`` along z, centred at ``(y, z)``."""
    if width <= 0.0 or height <= 0.0:
        raise ValueError("A rectangle needs a positive width and height.")
    hy, hz = height / 2.0, width / 2.0
    return PolygonRegion(
        ((y - hy, z - hz), (y - hy, z + hz), (y + hy, z + hz), (y + hy, z - hz)), hole
    )


def circle_points(region: CircleRegion, segments: int = 72) -> list[Point]:
    """Vertices of a circle, for drawing."""
    return [
        (
            region.y + region.radius * math.cos(2.0 * math.pi * k / segments),
            region.z + region.radius * math.sin(2.0 * math.pi * k / segments),
        )
        for k in range(segments)
    ]


def outline(region: Region) -> list[Point]:
    """The region's boundary as vertices (a circle as a 72-gon)."""
    return list(region.points) if isinstance(region, PolygonRegion) else circle_points(region)


# ──────────────────────────── moments of area ────────────────────────────
@dataclass(frozen=True)
class _Moments:
    """Area moments about the origin: A, ∫y, ∫z, ∫y², ∫z², ∫yz."""

    a: float
    qy: float
    qz: float
    iyy: float
    izz: float
    iyz: float

    def __add__(self, other: _Moments) -> _Moments:
        return _Moments(
            self.a + other.a,
            self.qy + other.qy,
            self.qz + other.qz,
            self.iyy + other.iyy,
            self.izz + other.izz,
            self.iyz + other.iyz,
        )

    def scaled(self, factor: float) -> _Moments:
        return _Moments(
            *(factor * v for v in (self.a, self.qy, self.qz, self.iyy, self.izz, self.iyz))
        )


def _polygon_moments(points: Sequence[Point]) -> _Moments:
    """Shoelace moments of a polygon, made positive whatever its orientation."""
    y = np.asarray([p[0] for p in points], dtype=float)
    z = np.asarray([p[1] for p in points], dtype=float)
    y1, z1 = np.roll(y, -1), np.roll(z, -1)
    cross = y * z1 - y1 * z
    a = cross.sum() / 2.0
    qy = ((y + y1) * cross).sum() / 6.0  # ∫ y dA
    qz = ((z + z1) * cross).sum() / 6.0  # ∫ z dA
    iyy = ((y * y + y * y1 + y1 * y1) * cross).sum() / 12.0  # ∫ y² dA
    izz = ((z * z + z * z1 + z1 * z1) * cross).sum() / 12.0  # ∫ z² dA
    iyz = ((y * z1 + 2.0 * y * z + 2.0 * y1 * z1 + y1 * z) * cross).sum() / 24.0
    moments = _Moments(float(a), float(qy), float(qz), float(iyy), float(izz), float(iyz))
    return moments.scaled(-1.0) if a < 0 else moments


def _circle_moments(c: CircleRegion) -> _Moments:
    a = math.pi * c.radius**2
    own = math.pi * c.radius**4 / 4.0
    return _Moments(a, a * c.y, a * c.z, own + a * c.y**2, own + a * c.z**2, a * c.y * c.z)


def _moments(region: Region) -> _Moments:
    moments = (
        _polygon_moments(region.points)
        if isinstance(region, PolygonRegion)
        else _circle_moments(region)
    )
    return moments.scaled(-1.0) if region.hole else moments


# ──────────────────────────── properties ────────────────────────────
@dataclass(frozen=True)
class SectionProperties:
    """Properties of a section about its centroid, in the regions' units."""

    A: float
    y_c: float
    z_c: float
    Iz: float
    """∫ (y - y_c)² dA: bending about the local z axis."""
    Iy: float
    """∫ (z - z_c)² dA: bending about the local y axis."""
    Iyz: float
    I1: float
    """Major principal moment."""
    I2: float
    """Minor principal moment."""
    angle: float
    """Angle of the major principal axis from the local z axis, degrees."""
    y_range: tuple[float, float]
    z_range: tuple[float, float]
    Zz: float = 0.0
    """Plastic modulus for bending about z (0 when not computed)."""
    Zy: float = 0.0
    notes: tuple[str, ...] = field(default=())

    @property
    def Sz(self) -> float:
        """Elastic modulus about z to the farther fibre in y."""
        reach = max(self.y_range[1] - self.y_c, self.y_c - self.y_range[0])
        return self.Iz / reach if reach > 0 else 0.0

    @property
    def Sy(self) -> float:
        reach = max(self.z_range[1] - self.z_c, self.z_c - self.z_range[0])
        return self.Iy / reach if reach > 0 else 0.0

    @property
    def rz(self) -> float:
        return math.sqrt(self.Iz / self.A)

    @property
    def ry(self) -> float:
        return math.sqrt(self.Iy / self.A)


def section_properties(regions: Sequence[Region], *, plastic: bool = True) -> SectionProperties:
    """Area, centroid and second moments of the solid regions minus the holes.

    Raises:
        ValueError: no region, or the holes take all the area.
    """
    if not regions:
        raise ValueError("The section has no region.")
    total = _Moments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    for region in regions:
        total = total + _moments(region)
    if total.a <= 0.0:
        raise ValueError("The holes take all the area: nothing is left.")
    yc, zc = total.qy / total.a, total.qz / total.a
    iz = total.iyy - total.a * yc**2  # ∫ (y - yc)² dA
    iy = total.izz - total.a * zc**2
    iyz = total.iyz - total.a * yc * zc
    ys = [p[0] for r in regions for p in outline(r)]
    zs = [p[1] for r in regions for p in outline(r)]
    mean = (iz + iy) / 2.0
    radius = math.hypot((iz - iy) / 2.0, iyz)
    angle = 0.5 * math.degrees(math.atan2(-2.0 * iyz, iz - iy))
    notes: list[str] = []
    overlap = _overlap_share(regions, total.a, (min(ys), max(ys)), (min(zs), max(zs)))
    if overlap > 0.005:
        notes.append(
            "Regions overlap, or a hole reaches outside the solid, over an area of "
            f"{overlap:.1%} of the section's: the properties add solids and subtract "
            "holes, so they count that area wrong."
        )
    if abs(iyz) > 1e-9 * max(abs(iz), abs(iy)):
        notes.append(
            f"Unsymmetric: the principal axes are {angle:.1f}° from y and z; an elastic "
            "section uses Iz and Iy and leaves Iyz out."
        )
    props = SectionProperties(
        A=total.a,
        y_c=yc,
        z_c=zc,
        Iz=iz,
        Iy=iy,
        Iyz=iyz,
        I1=mean + radius,
        I2=mean - radius,
        angle=angle,
        y_range=(min(ys), max(ys)),
        z_range=(min(zs), max(zs)),
        notes=tuple(notes),
    )
    if not plastic:
        return props
    zz, zy = _plastic_moduli(regions, props)
    return SectionProperties(**{**props.__dict__, "Zz": zz, "Zy": zy})


def _overlap_share(
    regions: Sequence[Region],
    area: float,
    y_range: tuple[float, float],
    z_range: tuple[float, float],
    samples: int = 200,
) -> float:
    """Share of the area inside two solids at once, or inside a hole but no solid.

    Sampled on a grid. Both are zero, whatever the grid, for a drawing whose
    solids do not overlap and whose holes lie inside them.
    """
    if len(regions) < 2:
        return 0.0
    y = np.linspace(y_range[0], y_range[1], samples + 1)
    z = np.linspace(z_range[0], z_range[1], samples + 1)
    gy, gz = np.meshgrid((y[:-1] + y[1:]) / 2.0, (z[:-1] + z[1:]) / 2.0, indexing="ij")
    py, pz = gy.ravel(), gz.ravel()
    solids = np.zeros(py.shape, dtype=int)
    holes = np.zeros(py.shape, dtype=bool)
    for region in regions:
        if isinstance(region, CircleRegion):
            hit = (py - region.y) ** 2 + (pz - region.z) ** 2 < region.radius**2
        else:
            hit = _inside_polygon(py, pz, region.points)
        if region.hole:
            holes |= hit
        else:
            solids += hit
    bad = (solids > 1) | (holes & (solids == 0))
    cell = (y_range[1] - y_range[0]) * (z_range[1] - z_range[0]) / samples**2
    return float(bad.sum()) * cell / area


# ──────────────────────────── fibres ────────────────────────────
def _inside_polygon(y: np.ndarray, z: np.ndarray, points: Sequence[Point]) -> np.ndarray:
    """Even-odd point-in-polygon test, vectorised over the query points."""
    inside = np.zeros(y.shape, dtype=bool)
    n = len(points)
    for k in range(n):
        y1, z1 = points[k]
        y2, z2 = points[(k + 1) % n]
        crosses = (z1 > z) != (z2 > z)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = y1 + (z - z1) * (y2 - y1) / (z2 - z1)
        inside ^= crosses & (y < at)
    return inside


def _inside(y: np.ndarray, z: np.ndarray, regions: Sequence[Region]) -> np.ndarray:
    """Points inside a solid region and outside every hole."""
    solid = np.zeros(y.shape, dtype=bool)
    holes = np.zeros(y.shape, dtype=bool)
    for region in regions:
        if isinstance(region, CircleRegion):
            hit = (y - region.y) ** 2 + (z - region.z) ** 2 < region.radius**2
        else:
            hit = _inside_polygon(y, z, region.points)
        if region.hole:
            holes |= hit
        else:
            solid |= hit
    return solid & ~holes


@dataclass(frozen=True)
class FibreGrid:
    """Fibres of a section: centroid ``y``, ``z`` and ``area`` arrays."""

    y: np.ndarray
    z: np.ndarray
    area: np.ndarray


def region_fibres(
    regions: Sequence[Region], n_y: int = 30, n_z: int = 30, subdivisions: int = 4
) -> FibreGrid:
    """A grid of ``n_y × n_z`` cells over the section's bounding box, one fibre per cell.

    Each cell is sampled at ``subdivisions²`` points: its fibre takes the area
    of the cell times the share of points inside the section, at the mean of
    those points. The total area is scaled to the exact one, so the fibres
    carry the right area and nearly the right second moments (the error falls
    with the grid size). Cells with no point inside are dropped.
    """
    if n_y < 1 or n_z < 1 or subdivisions < 1:
        raise ValueError("The grid needs at least one cell and one sample per side.")
    props = section_properties(regions, plastic=False)
    (y0, y1), (z0, z1) = props.y_range, props.z_range
    dy, dz = (y1 - y0) / n_y, (z1 - z0) / n_z
    offsets = (np.arange(subdivisions) + 0.5) / subdivisions
    grid_y, grid_z = np.meshgrid(offsets * dy, offsets * dz, indexing="ij")
    sy, sz = grid_y.ravel(), grid_z.ravel()
    cy, cz = np.meshgrid(y0 + np.arange(n_y) * dy, z0 + np.arange(n_z) * dz, indexing="ij")
    py = cy.ravel()[:, None] + sy[None, :]
    pz = cz.ravel()[:, None] + sz[None, :]
    hit = _inside(py.ravel(), pz.ravel(), regions).reshape(py.shape)
    count = hit.sum(axis=1)
    keep = count > 0
    share = count[keep] / sy.size
    area = share * dy * dz
    y = (py[keep] * hit[keep]).sum(axis=1) / count[keep]
    z = (pz[keep] * hit[keep]).sum(axis=1) / count[keep]
    if area.sum() > 0:
        area = area * (props.A / area.sum())
    return FibreGrid(y=y, z=z, area=area)


def _plastic_moduli(regions: Sequence[Region], props: SectionProperties) -> tuple[float, float]:
    """Plastic moduli about the centroidal z and y axes, from a fine fibre grid.

    The plastic neutral axis splits the area in two halves; ``Z`` is the first
    moment of both halves about it.
    """
    grid = region_fibres(regions, 80, 80, 3)
    out: list[float] = []
    for coord in (grid.y, grid.z):
        order = np.argsort(coord)
        c, a = coord[order], grid.area[order]
        half = np.searchsorted(np.cumsum(a), a.sum() / 2.0)
        axis = c[min(half, c.size - 1)]
        out.append(float(np.sum(a * np.abs(c - axis))))
    del props
    return out[0], out[1]


# ──────────────────────────── torsion ────────────────────────────
#: Conductivity of a hole in the Prandtl problem: high enough to make the stress
#: function constant across it (Bredt's condition), low enough to converge.
_HOLE_CONDUCTIVITY = 1e4

#: Smallest distance from a cell centre to the boundary, in cells, before the
#: boundary coefficient is capped.
_MIN_FRACTION = 1e-3


def _labels(y: np.ndarray, z: np.ndarray, regions: Sequence[Region]) -> np.ndarray:
    """0 outside the section, 1 in its material, 2 in a hole."""
    material = _inside(y, z, regions)
    hole = np.zeros(y.shape, dtype=bool)
    for region in regions:
        if not region.hole:
            continue
        if isinstance(region, CircleRegion):
            hole |= (y - region.y) ** 2 + (z - region.z) ** 2 < region.radius**2
        else:
            hole |= _inside_polygon(y, z, region.points)
    return np.where(material, 1, np.where(hole, 2, 0))


def _crossing(
    regions: Sequence[Region],
    ya: np.ndarray,
    za: np.ndarray,
    yb: np.ndarray,
    zb: np.ndarray,
    label_a: np.ndarray,
) -> np.ndarray:
    """Fraction of the way from a to b where the label first changes (bisection)."""
    low = np.zeros(ya.shape)
    high = np.ones(ya.shape)
    for _ in range(30):
        mid = (low + high) / 2.0
        same = _labels(ya + (yb - ya) * mid, za + (zb - za) * mid, regions) == label_a
        low = np.where(same, mid, low)
        high = np.where(same, high, mid)
    return (low + high) / 2.0


def torsion_constant(
    regions: Sequence[Region], cells: int = 40_000, *, tolerance: float = 1e-10
) -> float:
    """Saint-Venant torsional constant ``J`` by finite differences on Prandtl's stress function.

    ``∇·(k ∇φ) = -2`` over the section with ``φ = 0`` on its outer boundary;
    ``J = 2 ∫ φ dA``. A hole is given a very large ``k``, which holds ``φ``
    constant across it, and keeps the source, whose integral over the hole is
    the circulation condition of its boundary; its ``φ`` counts in the integral
    (Bredt's term).

    The grid has about ``cells`` square cells over the bounding box, so a thin
    shape gets cells across its thickness, not only along its length. Where
    a link between two cell centres crosses the boundary, the crossing is found
    by bisection and the link's coefficient uses the true distance
    (Shortley-Weller at the outer boundary, conductances in series at a hole), so
    the error falls with the square of the cell size instead of its first power,
    and a wall a few cells thick is still resolved. The system is symmetric and
    solved by Jacobi-preconditioned conjugate gradients.
    """
    props = section_properties(regions, plastic=False)
    (y0, y1), (z0, z1) = props.y_range, props.z_range
    h = math.sqrt((y1 - y0) * (z1 - z0) / cells)
    ny = math.ceil((y1 - y0) / h) + 2
    nz = math.ceil((z1 - z0) / h) + 2
    gy, gz = np.meshgrid(
        y0 - h / 2.0 + np.arange(ny) * h, z0 - h / 2.0 + np.arange(nz) * h, indexing="ij"
    )
    labels = _labels(gy.ravel(), gz.ravel(), regions).reshape(ny, nz)
    domain = labels > 0
    if not (labels == 1).any():
        return 0.0
    k = np.where(labels == 2, _HOLE_CONDUCTIVITY, 1.0)
    diagonal = np.zeros((ny, nz))
    couplings: list[np.ndarray] = []
    for axis in (0, 1):
        a = (slice(None, -1), slice(None)) if axis == 0 else (slice(None), slice(None, -1))
        b = (slice(1, None), slice(None)) if axis == 0 else (slice(None), slice(1, None))
        la, lb, ka, kb = labels[a], labels[b], k[a], k[b]
        coupling = np.where((la == lb) & (la > 0), ka, 0.0)
        extra_a = np.zeros(la.shape)
        extra_b = np.zeros(la.shape)
        cross = la != lb
        if cross.any():
            theta = np.full(la.shape, 0.5)
            theta[cross] = _crossing(
                regions, gy[a][cross], gz[a][cross], gy[b][cross], gz[b][cross], la[cross]
            )
            t_a = np.maximum(theta, _MIN_FRACTION)
            t_b = np.maximum(1.0 - theta, _MIN_FRACTION)
            inner = cross & (la > 0) & (lb > 0)
            coupling = np.where(inner, 1.0 / (theta / ka + (1.0 - theta) / kb), coupling)
            extra_a = np.where(cross & (la > 0) & (lb == 0), ka / t_a, 0.0)
            extra_b = np.where(cross & (lb > 0) & (la == 0), kb / t_b, 0.0)
        diagonal[a] += coupling + extra_a
        diagonal[b] += coupling + extra_b
        couplings.append(coupling)
    diagonal = np.where(domain, diagonal, 1.0)
    ky, kz = couplings

    def apply(phi: np.ndarray) -> np.ndarray:
        out = diagonal * phi
        out[:-1, :] -= ky * phi[1:, :]
        out[1:, :] -= ky * phi[:-1, :]
        out[:, :-1] -= kz * phi[:, 1:]
        out[:, 1:] -= kz * phi[:, :-1]
        return np.where(domain, out, 0.0)

    source = np.where(domain, 2.0 * h * h, 0.0)
    phi = np.zeros((ny, nz))
    residual = source.copy()
    precond = residual / diagonal
    direction = precond.copy()
    rz = float(np.sum(residual * precond))
    scale = float(np.sum(source * source))
    for _ in range(40 * (ny + nz)):
        q = apply(direction)
        alpha = rz / float(np.sum(direction * q))
        phi += alpha * direction
        residual -= alpha * q
        if float(np.sum(residual * residual)) < tolerance**2 * scale:
            break
        precond = residual / diagonal
        rz_next = float(np.sum(residual * precond))
        direction = precond + (rz_next / rz) * direction
        rz = rz_next
    return float(2.0 * np.sum(phi[domain]) * h * h)
