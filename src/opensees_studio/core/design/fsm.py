"""Elastic buckling of a thin-walled section by the finite strip method (signature curve).

The Direct Strength Method of AISI S100-16 (Chapters E and F) takes the elastic
buckling loads of the section, local (``Pcrl``, ``Mcrl``) and distortional
(``Pcrd``, ``Mcrd``), from a rational analysis (Appendix 2, 2.2). This module is
that analysis: the semi-analytical finite strip method for a member with simply
supported, warping-free ends and one half sine wave along its length, written
from the published theory (Y. K. Cheung, *Finite Strip Method in Structural
Analysis*, 1976; B. W. Schafer and S. Ádány, "Buckling analysis of cold-formed
steel members using CUFSM", 2006). No code is taken from CUFSM.

The section is a chain of flat strips along its midline (:func:`strip_model`).
Each strip carries plane stress (``u`` across the strip, ``v`` along the
member: linear across) and plate bending (``w`` out of the strip, ``θ`` about
the member's axis: cubic across). Along the member ``u`` and ``w`` vary as
``sin(πy/a)`` and ``v`` as ``cos(πy/a)``, so for a half-wavelength ``a`` the
problem is a small generalised eigenvalue problem ``K_e d = λ K_g d``. The
stiffness matrices are integrated across the strip by Gauss quadrature, exact
for these polynomials; the integrals along the member are ``a/2``.

The reference stress is the longitudinal stress at each node, **compression
positive**: λ times the reference is the buckling stress. Solving over a range
of half-wavelengths gives the *signature curve*. Its first interior minimum is
local buckling and the next one, when there is one, distortional buckling
(Appendix 2, 2.3.1.3 and Commentary). A section whose curve has no second
minimum (a plain channel, an angle, often a short lip) reports no distortional
load; the constrained finite strip method that separates the modes there is a
later step.

Pure NumPy. No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from opensees_studio.core.sections.cold_formed import (
    ColdFormedProperties,
    ColdFormedShape,
    midline,
    outline,
    properties,
)

#: Gauss-Legendre points across a strip: 4 points integrate degree 7 exactly
#: (a cubic squared times the linear stress); 5 leaves a margin.
_GAUSS_X, _GAUSS_W = np.polynomial.legendre.leggauss(5)

#: Half-wavelengths of a signature curve, as multiples of the section's largest
#: dimension: short enough for the local minimum of a narrow lip, long enough to
#: reach global buckling.
DEFAULT_LENGTH_RANGE = (0.05, 100.0)
DEFAULT_LENGTH_COUNT = 90


@dataclass(frozen=True)
class StripModel:
    """A section as nodes along its midline joined by flat strips of thickness ``t``."""

    nodes: np.ndarray
    """``N x 2`` node coordinates (the section's x and y)."""
    strips: np.ndarray
    """``M x 2`` node indices of each strip's ends."""
    t: float
    E: float
    nu: float

    @property
    def dof_count(self) -> int:
        """Four degrees of freedom per node: X, Y, the member's axis and the rotation."""
        return 4 * len(self.nodes)


def strip_model(
    shape: ColdFormedShape,
    elastic_modulus: float,
    nu: float = 0.3,
    *,
    strips_per_flat: int = 4,
    chords_per_quarter: int = 2,
) -> StripModel:
    """The finite strip mesh of ``shape``: its midline, flats subdivided, bends in chords.

    The widest flat gets ``strips_per_flat`` strips and the others as many strips
    of that width as fit, at least two for any flat wider than a bend (a lip needs
    two to bend in distortional buckling).
    """
    if shape.assembly != "single":
        raise ValueError(
            "The finite strip model of a box or back-to-back pair is not available yet; "
            "analyse one of its channels (shape.single)."
        )
    line = midline(shape, chords_per_quarter=chords_per_quarter)
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    widest = float(seg.max())
    target = widest / strips_per_flat
    bend = (shape.r + shape.t) * math.pi / 2.0 / chords_per_quarter
    points = [line[0]]
    for k, length in enumerate(seg):
        n = max(1, math.ceil(length / target - 1e-9))
        if length > 1.5 * bend:
            n = max(n, 2)
        for j in range(1, n + 1):
            points.append(line[k] + (line[k + 1] - line[k]) * j / n)
    nodes = np.asarray(points, dtype=float)
    strips = np.column_stack([np.arange(len(nodes) - 1), np.arange(1, len(nodes))])
    return StripModel(nodes=nodes, strips=strips, t=shape.t, E=elastic_modulus, nu=nu)


# ───────────────────────────── strip matrices ─────────────────────────────
def _strip_matrices(
    width: float, t: float, elastic_modulus: float, nu: float, k: float, stress: tuple[float, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Elastic and geometric stiffness of one strip in its own axes.

    Degrees of freedom: ``[u1, v1, w1, θ1, u2, v2, w2, θ2]``; ``u`` across the
    strip, ``v`` along the member, ``w`` normal to the strip, ``θ = ∂w/∂x``.
    ``k = π / a``; ``stress`` is the compression at the two edges.
    """
    b = width
    E = elastic_modulus
    membrane = E / (1.0 - nu**2) * np.array([[1.0, nu, 0.0], [nu, 1.0, 0.0], [0.0, 0.0, 0.0]])
    membrane[2, 2] = E / (2.0 * (1.0 + nu))
    bending = (
        E
        * t**3
        / (12.0 * (1.0 - nu**2))
        * np.array([[1.0, nu, 0.0], [nu, 1.0, 0.0], [0.0, 0.0, (1.0 - nu) / 2.0]])
    )
    u_dof, v_dof, w_dof = [0, 4], [1, 5], [2, 3, 6, 7]
    ke = np.zeros((8, 8))
    kg = np.zeros((8, 8))
    for gx, gw in zip(_GAUSS_X, _GAUSS_W, strict=True):
        xi = (gx + 1.0) / 2.0
        weight = gw * b / 2.0
        lin = np.array([1.0 - xi, xi])
        dlin = np.array([-1.0, 1.0]) / b
        herm = np.array(
            [1 - 3 * xi**2 + 2 * xi**3, b * (xi - 2 * xi**2 + xi**3), 3 * xi**2 - 2 * xi**3,
             b * (-(xi**2) + xi**3)]
        )  # fmt: skip
        dherm = np.array(
            [(-6 * xi + 6 * xi**2) / b, 1 - 4 * xi + 3 * xi**2, (6 * xi - 6 * xi**2) / b,
             -2 * xi + 3 * xi**2]
        )  # fmt: skip
        ddherm = np.array(
            [(-6 + 12 * xi) / b**2, (-4 + 6 * xi) / b, (6 - 12 * xi) / b**2, (-2 + 6 * xi) / b]
        )
        # Membrane strains (amplitudes): εx, εy (with sin), γxy (with cos).
        bm = np.zeros((3, 8))
        bm[0, u_dof] = dlin
        bm[1, v_dof] = -k * lin
        bm[2, u_dof] = k * lin
        bm[2, v_dof] = dlin
        # Curvatures: -w,xx and -w,yy (with sin), 2 w,xy (with cos).
        bb = np.zeros((3, 8))
        bb[0, w_dof] = -ddherm
        bb[1, w_dof] = k**2 * herm
        bb[2, w_dof] = 2.0 * k * dherm
        ke += weight * (t * bm.T @ membrane @ bm + bb.T @ bending @ bb)
        sigma = stress[0] * (1.0 - xi) + stress[1] * xi
        g = np.zeros((8, 8))
        g[np.ix_(u_dof, u_dof)] = np.outer(lin, lin)
        g[np.ix_(v_dof, v_dof)] = np.outer(lin, lin)
        g[np.ix_(w_dof, w_dof)] = np.outer(herm, herm)
        kg += weight * t * sigma * k**2 * g
    return ke, kg


def _rotation(c: float, s: float) -> np.ndarray:
    """Global ``[X, Y, V, Θ]`` per node to the strip's ``[u, v, w, θ]``."""
    node = np.array(
        [[c, s, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [-s, c, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    )
    out = np.zeros((8, 8))
    out[:4, :4] = node
    out[4:, 4:] = node
    return out


def assemble(
    model: StripModel, stress: np.ndarray, half_wavelength: float
) -> tuple[np.ndarray, np.ndarray]:
    """Global elastic and geometric stiffness for one half-wavelength."""
    k = math.pi / half_wavelength
    n = model.dof_count
    ke = np.zeros((n, n))
    kg = np.zeros((n, n))
    for i, j in model.strips:
        delta = model.nodes[j] - model.nodes[i]
        width = float(np.hypot(*delta))
        c, s = delta / width
        local_e, local_g = _strip_matrices(
            width, model.t, model.E, model.nu, k, (float(stress[i]), float(stress[j]))
        )
        rot = _rotation(float(c), float(s))
        idx = [*range(4 * i, 4 * i + 4), *range(4 * j, 4 * j + 4)]
        ke[np.ix_(idx, idx)] += rot.T @ local_e @ rot
        kg[np.ix_(idx, idx)] += rot.T @ local_g @ rot
    return ke, kg


def buckling_factor(
    model: StripModel,
    stress: np.ndarray,
    half_wavelength: float,
    *,
    fixed_dofs: Sequence[int] = (),
) -> tuple[float, np.ndarray]:
    """The smallest positive λ with ``K_e d = λ K_g d``, and its mode ``d`` (global DOFs).

    ``fixed_dofs`` are global degree-of-freedom indices held at zero (node ``n``:
    ``4n`` X, ``4n+1`` Y, ``4n+2`` along the member, ``4n+3`` rotation). Returns
    ``inf`` and a zero mode when no positive factor exists (the stress is tension
    everywhere).
    """
    ke, kg = assemble(model, stress, half_wavelength)
    free = np.setdiff1d(np.arange(model.dof_count), np.asarray(fixed_dofs, dtype=int))
    ke, kg = ke[np.ix_(free, free)], kg[np.ix_(free, free)]
    lower = np.linalg.cholesky(ke)
    inv = np.linalg.inv(lower)
    mu, vectors = np.linalg.eigh(inv @ kg @ inv.T)
    best = int(np.argmax(mu))
    mode = np.zeros(model.dof_count)
    if mu[best] <= 0.0:
        return math.inf, mode
    mode[free] = inv.T @ vectors[:, best]
    return float(1.0 / mu[best]), mode


@dataclass(frozen=True)
class SignatureCurve:
    """Buckling factor over half-wavelength, with the minima that name the modes."""

    lengths: np.ndarray
    factors: np.ndarray

    def minima(self) -> list[tuple[float, float]]:
        """Interior local minima ``(half-wavelength, factor)``, shortest first.

        A minimum is refined by a parabola through it and its neighbours on a
        log-length axis.
        """
        out: list[tuple[float, float]] = []
        f = self.factors
        for i in range(1, len(f) - 1):
            if f[i] < f[i - 1] and f[i] <= f[i + 1]:
                x = np.log(self.lengths[i - 1 : i + 2])
                coeffs = np.polyfit(x, f[i - 1 : i + 2], 2)
                if coeffs[0] > 0.0:
                    x_min = -coeffs[1] / (2.0 * coeffs[0])
                    x_min = float(np.clip(x_min, x[0], x[2]))
                    out.append((math.exp(x_min), float(np.polyval(coeffs, x_min))))
                else:
                    out.append((float(self.lengths[i]), float(f[i])))
        return out


def signature_curve(
    model: StripModel, stress: np.ndarray, lengths: Sequence[float] | np.ndarray | None = None
) -> SignatureCurve:
    """λ at each half-wavelength (by default spaced evenly on a log scale)."""
    if lengths is None:
        size = float(np.ptp(model.nodes, axis=0).max())
        low, high = DEFAULT_LENGTH_RANGE
        lengths = np.geomspace(low * size, high * size, DEFAULT_LENGTH_COUNT)
    values = np.asarray(lengths, dtype=float)
    factors = np.array([buckling_factor(model, stress, float(a))[0] for a in values])
    return SignatureCurve(lengths=values, factors=factors)


# ───────────────────────────── reference stresses ─────────────────────────────
def axial_stress(model: StripModel) -> np.ndarray:
    """Uniform compression of 1 at every node (λ is then the buckling stress ``Pcr / A``)."""
    return np.ones(len(model.nodes))


def bending_stress(
    model: StripModel,
    props: ColdFormedProperties,
    axis: str = "x",
    *,
    restrained: bool = True,
    positive: bool = True,
) -> np.ndarray:
    """Bending stress at the nodes, scaled to 1 at the extreme midline node.

    ``axis`` ``"x"`` bends about the x axis (the strong axis of a C or Z: the
    flanges at ±y), ``positive`` compresses +y (``"y"``: compresses +x).
    ``restrained`` bends about that geometric axis as if the other were held (a
    zee purlin braced by its sheeting); otherwise the zee bends biaxially, the
    neutral axis inclined by its product of inertia.
    """
    x = model.nodes[:, 0] - props.xc
    y = model.nodes[:, 1] - props.yc
    if axis == "x":
        if restrained or props.Ixy == 0.0:
            sigma = y / props.Ix
        else:
            sigma = (props.Iy * y - props.Ixy * x) / (props.Ix * props.Iy - props.Ixy**2)
    elif axis == "y":
        if restrained or props.Ixy == 0.0:
            sigma = x / props.Iy
        else:
            sigma = (props.Ix * x - props.Ixy * y) / (props.Ix * props.Iy - props.Ixy**2)
    else:
        raise ValueError(f"axis must be 'x' or 'y', not {axis!r}")
    if not positive:
        sigma = -sigma
    return sigma / float(np.abs(sigma).max())


# ───────────────────────────── critical loads ─────────────────────────────
@dataclass(frozen=True)
class CriticalBuckling:
    """Local and distortional buckling of one load (axial or a bending direction).

    Loads are in the units of the reference: ``Py = A·Fy`` for compression,
    ``My`` (first yield) for bending. ``None`` where the signature curve has no
    such minimum.
    """

    reference: float
    local: float | None
    local_length: float | None
    distortional: float | None
    distortional_length: float | None
    curve: SignatureCurve = field(repr=False)


@dataclass(frozen=True)
class SectionBuckling:
    """The elastic buckling loads DSM needs for one section and yield stress."""

    compression: CriticalBuckling
    """``reference = Py``; ``local = Pcrl``; ``distortional = Pcrd``."""
    bending_x: CriticalBuckling
    """About x, +y in compression; ``reference = My``; ``Mcrl``, ``Mcrd``."""


def _critical(curve: SignatureCurve, reference: float) -> CriticalBuckling:
    minima = curve.minima()
    local = minima[0] if minima else None
    distortional = minima[1] if len(minima) > 1 else None
    return CriticalBuckling(
        reference=reference,
        local=None if local is None else local[1] * reference,
        local_length=None if local is None else local[0],
        distortional=None if distortional is None else distortional[1] * reference,
        distortional_length=None if distortional is None else distortional[0],
        curve=curve,
    )


def section_buckling(
    shape: ColdFormedShape,
    elastic_modulus: float,
    fy: float,
    nu: float = 0.3,
    *,
    restrained: bool = True,
    lengths: Sequence[float] | np.ndarray | None = None,
) -> SectionBuckling:
    """``Pcrl``, ``Pcrd``, ``Mcrl`` and ``Mcrd`` of ``shape`` (strong-axis bending, +y compressed).

    Units follow the inputs: lengths of ``shape`` and stresses ``elastic_modulus``, ``fy``.
    """
    props = properties(shape)
    model = strip_model(shape, elastic_modulus, nu)
    # Reference stresses of Fy: λ is then Pcr / Py and Mcr / My.
    axial = signature_curve(model, fy * axial_stress(model), lengths)
    stress = fy * bending_stress(model, props, restrained=restrained)
    bending = signature_curve(model, stress, lengths)
    extreme = max(abs(y - props.yc) for _, y in outline(shape))  # outer fibre
    my = fy * props.Ix / extreme
    return SectionBuckling(
        compression=_critical(axial, props.A * fy), bending_x=_critical(bending, my)
    )


__all__ = [
    "CriticalBuckling",
    "SectionBuckling",
    "SignatureCurve",
    "StripModel",
    "assemble",
    "axial_stress",
    "bending_stress",
    "buckling_factor",
    "section_buckling",
    "signature_curve",
    "strip_model",
]
