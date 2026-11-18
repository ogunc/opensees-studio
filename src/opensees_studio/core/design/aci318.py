"""Reinforced concrete members after ACI 318-19 (SI expressions, consistent units).

The section is a cloud of fibres — concrete (``fc``) and reinforcing bars
(``fy``, ``Es``) — so any shape the Concrete Section Wizard or the Section
Designer draws is checked the same way.

* **Axial force and bending** (22.2, 22.4, 21.2): strain compatibility with
  ``εcu = 0.003`` and the equivalent rectangular stress block ``0.85 f'c`` over
  ``a = β1 c`` (β1 of 22.2.2.4.3), bars elastic-perfectly plastic. The nominal
  axial force and moment for a sweep of neutral-axis depths about one axis give
  the interaction curve; φ goes from 0.65 (tied) or 0.75 (spiral) to 0.90 as the
  net tensile strain of the extreme bar goes from ``εty`` to ``εty + 0.003``
  (Table 21.2.2), and ``φPn,max = 0.80 φP0`` tied, ``0.85 φP0`` spiral
  (22.4.2.1). Biaxial bending: Bresler's reciprocal load method above
  ``0.1 f'c Ag``, the linear load contour below.
* **Shear** (22.5): ``Vc = (0.17 λ √f'c + Nu / (6 Ag)) bw d`` (22.5.5.1, with
  Av ≥ Av,min), ``Vs = Av fyt d / s``, ``Vs ≤ 0.66 √f'c bw d`` (22.5.1.2),
  ``φ = 0.75``.
* **Torsion threshold** (22.7.4.1): ``φ 0.083 λ √f'c Acp² / pcp``; above it the
  member needs torsion design, which is reported, not done.
* **Beams** (Pu < 0.1 f'c Ag): ``As,min = max(0.25 √f'c / fy, 1.4 / fy) bw d``
  (9.6.1.2) and ``εt ≥ 0.004`` (9.3.3.1).

``mpa`` is the size of one MPa in the stresses' unit: the √f'c expressions are
written in MPa. No Qt, no OpenSees.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

EPS_CU = 0.003


@dataclass(frozen=True)
class RcSection:
    """Fibres of one section: concrete ``(y, z, area)`` and bars ``(y, z, area)``."""

    concrete: np.ndarray
    bars: np.ndarray
    fc: float
    fy: float
    es: float
    mpa: float = 1e6
    transverse: Literal["tied", "spiral"] = "tied"

    @property
    def gross_area(self) -> float:
        """``Ag``: the concrete fibres, which (as in OpenSees) also cover the bars."""
        return float(self.concrete[:, 2].sum())

    @property
    def steel_area(self) -> float:
        return float(self.bars[:, 2].sum())

    @property
    def beta1(self) -> float:
        """β1 of ACI 318-19 22.2.2.4.3."""
        fc = self.fc / self.mpa
        return float(min(0.85, max(0.65, 0.85 - 0.05 * (fc - 28.0) / 7.0)))

    @property
    def p0(self) -> float:
        """Nominal axial strength without bending, ``0.85 f'c (Ag - Ast) + fy Ast``."""
        return 0.85 * self.fc * (self.gross_area - self.steel_area) + self.fy * self.steel_area

    @property
    def phi_compression(self) -> float:
        return 0.75 if self.transverse == "spiral" else 0.65

    @property
    def pn_max(self) -> float:
        """``φPn,max`` (22.4.2.1)."""
        factor = 0.85 if self.transverse == "spiral" else 0.80
        return factor * self.phi_compression * self.p0

    def phi(self, eps_t: float) -> float:
        """Strength reduction of Table 21.2.2 for the net tensile strain ``eps_t``."""
        eps_ty = self.fy / self.es
        low = self.phi_compression
        if eps_t <= eps_ty:
            return low
        if eps_t >= eps_ty + 0.003:
            return 0.90
        return low + (0.90 - low) * (eps_t - eps_ty) / 0.003


@dataclass(frozen=True)
class CurvePoint:
    """One neutral-axis depth: nominal forces and the strength reduction."""

    pn: float
    """Axial force, compression positive."""
    mn: float
    """Moment about the section centroid, positive for compression on the +side."""
    phi: float
    eps_t: float


def interaction_curve(
    section: RcSection, axis: Literal["y", "z"], points: int = 120
) -> list[CurvePoint]:
    """Nominal (Pn, Mn) about local ``axis`` (bending that puts ``axis`` coordinates in play).

    ``axis="y"`` bends about local z (the fibres' y is the lever arm, moment M3
    in a frame), ``axis="z"`` about local y. Both signs of curvature are swept,
    from pure tension to pure compression.
    """
    column = 0 if axis == "y" else 1
    conc = section.concrete
    bars = section.bars
    area = section.gross_area
    centroid = float((conc[:, column] * conc[:, 2]).sum()) / area
    out: list[CurvePoint] = []
    for sign in (1.0, -1.0):
        # Distance of each fibre from the compressed face, along the bending direction.
        top = conc[:, column].max() if sign > 0 else -conc[:, column].min()
        depth_c = top - sign * conc[:, column]
        depth_s = top - sign * bars[:, column]
        height = float(depth_c.max())
        for c in np.geomspace(1e-4 * height, 50.0 * height, points):
            a = section.beta1 * c
            concrete_force = 0.85 * section.fc * conc[:, 2] * (depth_c <= a)
            strain = EPS_CU * (c - depth_s) / c
            stress = np.clip(strain * section.es, -section.fy, section.fy)
            # Displaced concrete: a bar in the compression block replaces concrete.
            displaced = 0.85 * section.fc * bars[:, 2] * (depth_s <= a)
            steel_force = stress * bars[:, 2] - displaced
            pn = float(concrete_force.sum() + steel_force.sum())
            arm_c = sign * (conc[:, column] - centroid)
            arm_s = sign * (bars[:, column] - centroid)
            mn = sign * float((concrete_force * arm_c).sum() + (steel_force * arm_s).sum())
            eps_t = float(-strain.min()) if strain.size else 0.0
            out.append(CurvePoint(pn=pn, mn=mn, phi=section.phi(eps_t), eps_t=eps_t))
    # Pure tension.
    out.append(CurvePoint(pn=-section.fy * section.steel_area, mn=0.0, phi=0.9, eps_t=1.0))
    return out


def design_moment_capacity(
    curve: list[CurvePoint], pu: float, section: RcSection, sign: float
) -> tuple[float, float]:
    """``(φMn, φ)`` at the factored axial force ``pu`` (compression positive), for
    moments of ``sign``. ``(0, φ)`` when ``pu`` is outside the curve."""
    best: tuple[float, float] = (0.0, section.phi_compression)
    points = sorted((p for p in curve if p.mn * sign >= 0.0), key=lambda p: p.phi * p.pn)
    design = [(p.phi * min(p.pn, section.pn_max / p.phi), p.phi * abs(p.mn), p.phi) for p in points]
    for (p1, m1, f1), (p2, m2, _f2) in itertools.pairwise(design):
        if (p1 - pu) * (p2 - pu) <= 0.0 and p1 != p2:
            t = (pu - p1) / (p2 - p1)
            moment = m1 + t * (m2 - m1)
            if moment > best[0]:
                best = (moment, f1)
    return best


def axial_capacity_at(curve: list[CurvePoint], eccentricity: float, section: RcSection) -> float:
    """``φPn`` where the design curve meets the eccentricity ``e = M / P`` (compression side)."""
    best = 0.0
    design = [
        (p.phi * min(p.pn, section.pn_max / p.phi), p.phi * abs(p.mn)) for p in curve if p.pn > 0.0
    ]
    design.sort(key=lambda pm: pm[1] / pm[0] if pm[0] > 0 else math.inf)
    for (p1, m1), (p2, m2) in itertools.pairwise(design):
        e1, e2 = m1 / p1, m2 / p2
        if (e1 - eccentricity) * (e2 - eccentricity) <= 0.0 and e1 != e2:
            t = (eccentricity - e1) / (e2 - e1)
            best = max(best, p1 + t * (p2 - p1))
    return best


@dataclass
class Check:
    name: str
    ratio: float
    clause: str
    detail: str = ""


@dataclass
class RcMemberCheck:
    """Every limit state at one station."""

    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def governing(self) -> Check | None:
        return max(self.checks, key=lambda c: c.ratio, default=None)


@dataclass(frozen=True)
class ShearReinforcement:
    av: float
    """Area of the legs of one stirrup set crossing the shear plane."""
    spacing: float
    fyt: float


def section_depths(section: RcSection, axis: Literal["y", "z"], sign: float) -> tuple[float, float]:
    """``(h, d)`` in the bending direction: overall depth and depth of the extreme bar."""
    column = 0 if axis == "y" else 1
    conc = section.concrete
    top = conc[:, column].max() if sign > 0 else -conc[:, column].min()
    depth_c = top - sign * conc[:, column]
    depth_s = top - sign * section.bars[:, column]
    return float(depth_c.max()), float(depth_s.max()) if depth_s.size else float(depth_c.max())


def check_station(
    section: RcSection,
    curves: dict[str, list[CurvePoint]],
    *,
    pu: float,
    m3: float,
    m2: float,
    v2: float,
    v3: float,
    t: float,
    shear: ShearReinforcement | None,
    lam: float = 1.0,
) -> RcMemberCheck:
    """ACI 318-19 checks of one station; forces factored, compression ``pu`` positive.

    ``m3`` bends about local z (curve ``"y"``), ``m2`` about local y (curve ``"z"``).
    """
    out = RcMemberCheck()
    ag = section.gross_area
    sqrt_fc = math.sqrt(section.fc / section.mpa) * section.mpa
    if pu > 0.0:
        out.checks.append(
            Check("Axial compression", pu / section.pn_max, "22.4.2.1", "Pu / φPn,max")
        )
    elif pu < 0.0:
        tension = 0.9 * section.fy * section.steel_area
        out.checks.append(Check("Axial tension", -pu / tension, "22.4.3", "Tu / φ fy Ast"))
    capacities: dict[str, float] = {}
    for name, moment, key in (("M3", m3, "y"), ("M2", m2, "z")):
        if abs(moment) <= 0.0:
            continue
        capacity, _phi = design_moment_capacity(
            curves[key], pu, section, math.copysign(1.0, moment)
        )
        capacities[name] = capacity
        ratio = abs(moment) / capacity if capacity > 0.0 else math.inf
        out.checks.append(
            Check(f"Flexure {name} with axial force", ratio, "22.4, 21.2", "Mu / φMn at Pu")
        )
    if len(capacities) == 2:
        if pu >= 0.1 * section.fc * ag:
            # Bresler's reciprocal load: 1/φPni = 1/φPnx + 1/φPny - 1/φP0.
            p_x = axial_capacity_at(curves["y"], abs(m3) / pu, section)
            p_y = axial_capacity_at(curves["z"], abs(m2) / pu, section)
            p_0 = section.phi_compression * section.p0
            inverse = 1.0 / p_x + 1.0 / p_y - 1.0 / p_0 if p_x > 0 and p_y > 0 else math.inf
            ratio = pu * inverse if math.isfinite(inverse) else math.inf
            out.checks.append(
                Check("Biaxial bending", ratio, "R22.4 (Bresler)", "Pu / φPni, reciprocal load")
            )
        else:
            ratio = abs(m3) / capacities["M3"] + abs(m2) / capacities["M2"]
            out.checks.append(
                Check("Biaxial bending", ratio, "R22.4", "Mux/φMnx + Muy/φMny (load contour)")
            )
    for name, v, axis in (("V2", v2, "y"), ("V3", v3, "z")):
        if abs(v) <= 0.0:
            continue
        h, d = section_depths(section, axis, 1.0)  # type: ignore[arg-type]
        bw = ag / h
        nu_term = pu / (6.0 * ag)
        vc = max(0.0, (0.17 * lam * sqrt_fc + nu_term) * bw * d)
        vc = min(vc, 0.42 * lam * sqrt_fc * bw * d)
        vs = 0.0
        if shear is not None and shear.spacing > 0.0:
            vs = min(shear.av * shear.fyt * d / shear.spacing, 0.66 * sqrt_fc * bw * d)
        phi_vn = 0.75 * (vc + vs)
        out.checks.append(
            Check(f"Shear {name}", abs(v) / phi_vn if phi_vn > 0 else math.inf, "22.5", "Vu / φVn")
        )
    if abs(t) > 0.0:
        h_y, _ = section_depths(section, "y", 1.0)
        h_z, _ = section_depths(section, "z", 1.0)
        acp, pcp = ag, 2.0 * (h_y + h_z)
        threshold = 0.75 * 0.083 * lam * sqrt_fc * acp**2 / pcp
        ratio = abs(t) / threshold
        out.checks.append(Check("Torsion threshold", ratio, "22.7.4.1", "Tu / φTth"))
        if ratio > 1.0:
            out.notes.append(
                "Torsion above the threshold: design the closed stirrups and longitudinal "
                "torsion steel (22.7), which this check does not do."
            )
    return out


def beam_checks(
    section: RcSection, axis: Literal["y", "z"], curve: list[CurvePoint]
) -> list[Check]:
    """Minimum flexural steel (9.6.1.2) and the tension-controlled limit (9.3.3.1)."""
    out: list[Check] = []
    sqrt_fc_mpa = math.sqrt(section.fc / section.mpa)
    fy_mpa = section.fy / section.mpa
    for sign in (1.0, -1.0):
        h, d = section_depths(section, axis, sign)
        bw = section.gross_area / h
        column = 0 if axis == "y" else 1
        top = section.concrete[:, column].max() if sign > 0 else -section.concrete[:, column].min()
        depth_s = top - sign * section.bars[:, column]
        tension_steel = float(section.bars[depth_s > h / 2.0, 2].sum())
        minimum = max(0.25 * sqrt_fc_mpa / fy_mpa, 1.4 / fy_mpa) * bw * d
        if tension_steel > 0.0:
            out.append(
                Check(
                    "Minimum flexural steel" + (" (+)" if sign > 0 else " (-)"),
                    minimum / tension_steel,
                    "9.6.1.2",
                    "As,min / As",
                )
            )
    pure = [p for p in curve if abs(p.pn) < 0.01 * section.p0 and p.mn != 0.0]
    if pure:
        worst = min(pure, key=lambda p: p.eps_t)
        out.append(
            Check(
                "Net tensile strain εt ≥ 0.004",
                0.004 / max(worst.eps_t, 1e-9),
                "9.3.3.1",
                "0.004 / εt",
            )
        )
    return out
