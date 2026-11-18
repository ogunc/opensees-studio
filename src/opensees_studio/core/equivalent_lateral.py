"""Equivalent lateral force (ELF) seismic loads: base shear and its storey distribution.

Two codes, the ones whose spectra the application already builds:

- **ASCE/SEI 7-16 §12.8**: ``Cs = SDS / (R / Ie)``, capped by ``SD1 / (T (R/Ie))``
  (``T <= TL``) or ``SD1 TL / (T² (R/Ie))`` (``T > TL``), and at least
  ``max(0.044 SDS Ie, 0.01)`` and, when ``S1 >= 0.6 g``, ``0.5 S1 / (R/Ie)``.
  ``V = Cs W``. Storey forces ``Fx = Cvx V`` with ``Cvx = wx hx^k / Σ wi hi^k``,
  ``k = 1`` for ``T <= 0.5 s``, ``2`` for ``T >= 2.5 s``, linear between (§12.8.3).
- **TBDY 2018 §4.7**: ``Vt = m_t SaR(T) g >= 0.04 m_t I SDS g``, with
  ``SaR = Sae(T) / Ra(T)``, ``Ra = R/I`` for ``T > TB`` and
  ``D + (R/I - D) T / TB`` below. An extra ``ΔFN = 0.0075 N Vt`` acts at the
  top storey; the rest is shared as ``Fi = (Vt - ΔFN) mi Hi / Σ mj Hj``.

The storey weights are the masses the solver gets (``effective_nodal_masses``:
typed masses, the mass source and diaphragm lumping) times g, gathered at the
storey levels (the project's storeys, or every elevation above the base that
carries mass). Heights are measured from the base (the lowest node).

Each storey force goes to the floor: to a horizontal diaphragm's retained node
when that is where the mass is, else shared between the floor's joints in
proportion to their mass. **Accidental eccentricity** (3D) moves it by
``±e = ±ratio × L`` across the load, ``L`` the floor's extent in that
direction: a torque ``F e`` at the retained node, or the mass-proportional
shares tilted so their resultant acts ``e`` off the centre of mass.

The code coefficients (R, Ie / I, D, Ct, the period) are the engineer's: the
generator applies the formulas, it does not pick the structural system.

This module is part of ``core``: no Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np

from opensees_studio.core.mass_source import effective_nodal_masses
from opensees_studio.core.plane import VERTICAL_AXIS
from opensees_studio.core.response_spectrum import four_branch_spectrum
from opensees_studio.core.storeys import (
    base_elevation,
    elevation_tolerance,
    nodes_at_elevation,
    storey_levels,
)
from opensees_studio.core.target_spectrum import TBDY_TL, tbdy2018_corner_periods
from opensees_studio.core.units import UnitSystem, gravity, length_scale

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

Code = Literal["asce7_16", "tbdy2018"]
CODE_LABELS: dict[str, str] = {
    "asce7_16": "ASCE/SEI 7-16 §12.8",
    "tbdy2018": "TBDY 2018 §4.7",
}

#: ASCE 7-16 Table 12.8-2: (label, Ct for h in metres, x).
ASCE_PERIOD_SYSTEMS: dict[str, tuple[str, float, float]] = {
    "steel_mrf": ("Steel moment-resisting frame", 0.0724, 0.8),
    "concrete_mrf": ("Concrete moment-resisting frame", 0.0466, 0.9),
    "braced_ebf": ("Eccentrically braced / BRB frame", 0.0731, 0.75),
    "other": ("All other structural systems", 0.0488, 0.75),
}
#: TBDY 2018 §4.7.3.4: (label, Ct for H in metres); T = Ct H^(3/4).
TBDY_PERIOD_SYSTEMS: dict[str, tuple[str, float]] = {
    "concrete_frame": ("Reinforced concrete frame", 0.1),
    "steel_frame": ("Steel frame", 0.08),
    "braced_ebf": ("Eccentrically braced steel frame", 0.07),
    "other": ("All other systems", 0.05),
}


@dataclass(frozen=True)
class ElfParameters:
    """What the engineer gives the generator."""

    code: Code
    period: float
    """Fundamental period T in the direction, seconds."""
    sds: float
    sd1: float
    r: float
    """Response modification (ASCE R) or load reduction (TBDY R) coefficient."""
    importance: float = 1.0
    """ASCE Ie or TBDY I."""
    tl: float = TBDY_TL
    s1: float = 0.0
    """ASCE mapped S1 (g), for the §12.8-6 minimum; 0 leaves it out."""
    overstrength_d: float = 2.0
    """TBDY D (overstrength), for Ra(T) below TB."""
    eccentricity_ratio: float = 0.05
    """Accidental eccentricity as a fraction of the floor extent (3D)."""


@dataclass(frozen=True)
class ElfLevel:
    """One storey of the distribution."""

    name: str
    elevation: float
    height: float
    """Above the base."""
    weight: float
    force: float
    nodes: tuple[int, ...]


@dataclass
class ElfResult:
    """Base shear, its distribution, and what the code formulas gave."""

    code: Code
    direction: int
    """Global axis of the loads: 0 = X, 1 = Y."""
    period: float
    total_weight: float
    coefficient: float
    """ASCE Cs, or TBDY Vt / W."""
    base_shear: float
    levels: list[ElfLevel]
    notes: list[str] = field(default_factory=list)
    """The governing limit and anything left out, for the dialog."""

    def table(self) -> list[tuple[str, float, float, float]]:
        """``(storey, height, weight, force)`` rows, top first."""
        return [(lv.name, lv.height, lv.weight, lv.force) for lv in reversed(self.levels)]


class ElfError(ValueError):
    """The model or the parameters cannot give an ELF distribution."""


# ─────────────────────────── periods ───────────────────────────
def approximate_period(code: Code, system: str, height: float, length_to_m: float) -> float:
    """The code's empirical period for a building ``height`` tall (model length units)."""
    h_m = height * length_to_m
    if h_m <= 0.0:
        raise ElfError("The building has no height above its base.")
    if code == "asce7_16":
        _label, ct, x = ASCE_PERIOD_SYSTEMS[system]
        return float(ct * h_m**x)
    _label, ct_tbdy = TBDY_PERIOD_SYSTEMS[system]
    return float(ct_tbdy * h_m**0.75)


# ─────────────────────────── base shear ───────────────────────────
def asce7_cs(p: ElfParameters) -> tuple[float, str]:
    """ASCE 7-16 seismic response coefficient Cs and the clause that governs it."""
    ri = p.r / p.importance
    if p.r <= 0.0 or p.importance <= 0.0:
        raise ElfError("R and Ie must be positive.")
    cs = p.sds / ri
    why = "Eq. 12.8-2 (SDS / (R/Ie))"
    if p.period > 0.0:
        cap = p.sd1 / (p.period * ri) if p.period <= p.tl else p.sd1 * p.tl / (p.period**2 * ri)
        if cap < cs:
            cs, why = cap, ("Eq. 12.8-3 (T <= TL)" if p.period <= p.tl else "Eq. 12.8-4 (T > TL)")
    floor = max(0.044 * p.sds * p.importance, 0.01)
    if cs < floor:
        cs, why = floor, "Eq. 12.8-5 minimum (0.044 SDS Ie, at least 0.01)"
    if p.s1 >= 0.6:
        floor6 = 0.5 * p.s1 / ri
        if cs < floor6:
            cs, why = floor6, "Eq. 12.8-6 minimum (0.5 S1 / (R/Ie), S1 >= 0.6 g)"
    return cs, why


def asce7_k(period: float) -> float:
    """ASCE 7-16 §12.8.3 distribution exponent."""
    if period <= 0.5:
        return 1.0
    if period >= 2.5:
        return 2.0
    return 1.0 + (period - 0.5) / 2.0


def tbdy_sar(p: ElfParameters) -> tuple[float, float]:
    """TBDY 2018 reduced spectral acceleration SaR(T) (g) and Ra(T)."""
    if p.r <= 0.0 or p.importance <= 0.0 or p.overstrength_d <= 0.0:
        raise ElfError("R, I and D must be positive.")
    _ta, tb = tbdy2018_corner_periods(p.sds, p.sd1)
    sae = float(np.ravel(four_branch_spectrum(p.period, p.sds, p.sd1, p.tl))[0])
    ri = p.r / p.importance
    ra = ri if p.period > tb else p.overstrength_d + (ri - p.overstrength_d) * p.period / tb
    return sae / ra, ra


# ─────────────────────────── the levels ───────────────────────────
@dataclass(frozen=True)
class _Level:
    name: str
    elevation: float
    nodes: tuple[int, ...]


def _levels(project: Project, masses: dict[int, np.ndarray], direction: int) -> list[_Level]:
    """The project's storeys, else every elevation above the base that carries mass."""
    levels = storey_levels(project)
    if levels:
        return [
            _Level(lv.storey.name or f"Storey {k}", lv.storey.elevation, lv.nodes)
            for k, lv in enumerate(levels, start=1)
        ]
    base = base_elevation(project)
    tol = elevation_tolerance(project)
    coords = {n.id: n.coords for n in project.nodes}
    elevations: list[float] = []
    for nid, mass in masses.items():
        z = float(coords[nid][VERTICAL_AXIS])
        if mass[direction] > 0.0 and z > base + tol and all(abs(z - e) > tol for e in elevations):
            elevations.append(z)
    return [
        _Level(f"Level {k}", z, tuple(nodes_at_elevation(project, z)))
        for k, z in enumerate(sorted(elevations), start=1)
    ]


# ─────────────────────────── the generator ───────────────────────────
def equivalent_lateral_forces(project: Project, direction: int, p: ElfParameters) -> ElfResult:
    """Base shear and storey forces of ``project`` for loads along global axis ``direction``."""
    if project.ndm == 2 and direction != 0:
        raise ElfError("A 2D model takes lateral loads along X only (it lives in the X-Z plane).")
    if p.period <= 0.0:
        raise ElfError("The period T must be positive.")
    if p.sds <= 0.0 or p.sd1 <= 0.0:
        raise ElfError("SDS and SD1 must be positive.")
    units = project.meta.units
    g = gravity(units)
    masses = effective_nodal_masses(project)
    levels = _levels(project, masses, direction)
    if not levels:
        raise ElfError(
            "No storey carries mass: define storeys (Define → Storeys) and masses "
            "(Assign → Joint → Masses, or Define → Mass Source)."
        )
    base = base_elevation(project)
    weights = [
        g * sum(float(masses[n][direction]) for n in lv.nodes if n in masses) for lv in levels
    ]
    total = float(sum(weights))
    if total <= 0.0:
        raise ElfError("The storeys carry no mass in that direction.")
    heights = [lv.elevation - base for lv in levels]
    notes: list[str] = []
    on_levels = {n for lv in levels for n in lv.nodes}
    off = g * sum(
        float(m[direction])
        for nid, m in masses.items()
        if nid not in on_levels
        and float(project.node(nid).coords[VERTICAL_AXIS]) > base + elevation_tolerance(project)
    )
    if off > 1e-9 * total:
        notes.append(
            f"{off / (off + total):.1%} of the weight above the base lies off the storey "
            "levels and is not in W."
        )

    if p.code == "asce7_16":
        cs, why = asce7_cs(p)
        shear = cs * total
        k = asce7_k(p.period)
        share = np.array([w * h**k for w, h in zip(weights, heights, strict=True)])
        forces = shear * share / share.sum()
        notes.insert(0, f"Cs = {cs:.4g} by {why}; k = {k:.3g}.")
        coefficient = cs
    else:
        sar, ra = tbdy_sar(p)
        shear = sar * total
        minimum = 0.04 * p.importance * p.sds * total
        why = f"SaR(T) = {sar:.4g} g with Ra(T) = {ra:.4g}"
        if shear < minimum:
            shear, why = minimum, "the minimum 0.04 I SDS (Eq. 4.19)"
        top = 0.0075 * len(levels) * shear
        share = np.array([w * h for w, h in zip(weights, heights, strict=True)])
        forces = (shear - top) * share / share.sum()
        forces[-1] += top
        notes.insert(0, f"Vt by {why}; ΔFN = {top:.4g} at the top storey (Eq. 4.20).")
        coefficient = shear / total
    result_levels = [
        ElfLevel(lv.name, lv.elevation, h, w, float(f), lv.nodes)
        for lv, h, w, f in zip(levels, heights, weights, forces, strict=True)
    ]
    return ElfResult(
        code=p.code,
        direction=direction,
        period=p.period,
        total_weight=total,
        coefficient=coefficient,
        base_shear=float(shear),
        levels=result_levels,
        notes=notes,
    )


def building_height(project: Project) -> float:
    """Highest node above the lowest one, in model length units."""
    if not project.nodes:
        return 0.0
    zs = [float(n.coords[VERTICAL_AXIS]) for n in project.nodes]
    return max(zs) - min(zs)


def length_in_metres(project: Project) -> float:
    """Metres per model length unit."""
    return length_scale(project.meta.units, UnitSystem.SI_M_N)


# ─────────────────────────── nodal loads ───────────────────────────
def _retained_with_mass(
    project: Project, level_nodes: Sequence[int], masses: dict[int, np.ndarray], direction: int
) -> int | None:
    """A horizontal diaphragm's retained node on this floor that holds its mass, if any."""
    floor = set(level_nodes)
    for diaphragm in project.diaphragms:
        if diaphragm.perp_dirn != 3:
            continue
        node = diaphragm.retained_node
        on_floor = node in floor or _on_same_level(project, node, level_nodes)
        if node in masses and on_floor and float(masses[node][direction]) > 0.0:
            return node
    return None


def _on_same_level(project: Project, node: int, level_nodes: Sequence[int]) -> bool:
    if not level_nodes:
        return False
    tol = elevation_tolerance(project)
    z = float(project.node(node).coords[VERTICAL_AXIS])
    return abs(z - float(project.node(level_nodes[0]).coords[VERTICAL_AXIS])) <= tol


def nodal_forces(
    project: Project, result: ElfResult, eccentricity_sign: int = 0, ratio: float = 0.05
) -> dict[int, tuple[float, float, float, float, float, float]]:
    """The storey forces as global nodal loads, with ``±ratio`` accidental eccentricity.

    ``eccentricity_sign`` is -1, 0 or +1; it is ignored in 2D.
    """
    masses = effective_nodal_masses(project)
    d = result.direction
    across = 1 - d  # the horizontal axis perpendicular to the load (3D)
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    out: dict[int, np.ndarray] = {}

    def add(nid: int, slot: int, value: float) -> None:
        out.setdefault(nid, np.zeros(6))[slot] += value

    for level in result.levels:
        force = level.force
        floor = [n for n in level.nodes if n in coords]
        if not floor or force == 0.0:
            continue
        extent = 0.0
        if project.ndm == 3 and eccentricity_sign:
            values = [coords[n][across] for n in floor]
            extent = max(values) - min(values)
        e = eccentricity_sign * ratio * extent if project.ndm == 3 else 0.0
        retained = _retained_with_mass(project, floor, masses, d)
        if retained is not None:
            add(retained, d, force)
            if e:
                # The torque of F acting e across the load: r x F about +Z is
                # -F e for a load along X (e along Y), +F e along Y (e along X).
                add(retained, 5, force * e * (1.0 if d == 1 else -1.0))
            continue
        m = np.array([float(masses.get(n, np.zeros(6))[d]) for n in floor])
        if m.sum() <= 0.0:
            m = np.ones(len(floor))
        total = m.sum()
        shares = force * m / total
        if e and project.ndm == 3:
            r = np.array([coords[n][across] for n in floor])
            centre = float(m @ r) / total
            r = r - centre
            inertia = float(m @ r**2)
            if inertia > 0.0:
                shares = force * m / total * (1.0 + e * total * r / inertia)
        for nid, value in zip(floor, shares, strict=True):
            add(nid, d, float(value))
    return {nid: tuple(float(v) for v in vec) for nid, vec in out.items()}  # type: ignore[misc]
