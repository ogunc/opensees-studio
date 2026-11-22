"""Isolated spread footings under a support: the soil and ACI 318-19.

AISC does not design footings: it stops at the base plate (AISC 360 J8, Design
Guide 1, :mod:`.base_plate`). The footing under it is reinforced concrete, so
this module checks it after **ACI 318-19** Chapter 13 (foundations) with the
one-way and two-way shear of Chapter 22, and the soil with the service loads.

Everything here works in **N, mm, MPa** (:class:`Footing`); the service converts
the project's units in and out. One footing is a rectangle ``L`` (along global
X) by ``B`` (along global Y) of thickness ``h``. The support sits at
``(offset_x, offset_y)`` from the footing centre on a footprint ``cx`` by
``cy`` (a pedestal of height ``hp``, or the column or the base plate itself).
The loads are the support **reactions** in global axes (the force and moment the
support puts on the structure); the footing takes them with the opposite sign.

**Soil, service loads** (the ASD combinations):

* ``N`` = the column's compression + the footing, the pedestal and the fill
  above the footing. The moment at the underside adds the column moment and the
  horizontal force times ``hp + h``.
* Pressure: a plane on the rectangle, compression only. Inside the kern
  ``q = N/A (1 ± 6 ex/L ± 6 ey/B)``; outside it one-way eccentricity has the
  closed form ``q,max = 2N / (3 B (L/2 - e))`` and two-way eccentricity is solved
  for the contact plane numerically (Newton on a 160 × 160 grid).
* Checks: ``q,max ≤ qa`` (gross allowable bearing of the soil report), contact
  area ``≥ 50 %`` of the footing, overturning ``FS = N (L/2) / M`` per
  direction, sliding ``FS = μ N / H``, and no net uplift.

**Concrete, strength loads** (the LRFD combinations): the net pressure from the
column's factored reaction only (the weight of the footing and the fill balances
its own pressure).

* Depth ``d ≥ 150 mm`` (13.3.1.2).
* One-way shear at ``d`` from the face (22.5.5.1 (c), no stirrups):
  ``φ Vc = 0.75 · 0.66 λs λ ρw^(1/3) √f'c b d ≤ 0.75 · 0.42 λ √f'c b d``,
  ``λs = √(2 / (1 + 0.004 d)) ≤ 1``.
* Two-way shear at ``d/2`` (22.6.5.2): ``vc`` the least of ``0.33``,
  ``0.17 (1 + 2/β)`` and ``0.083 (2 + αs d / b0)`` times ``λs λ √f'c``;
  ``αs`` 40, 30 or 20 with the sides that fit in the footing. The column's
  moment adds ``γv M c / Jc`` (8.4.4.2) on an interior perimeter.
* Flexure at the face of the column or pedestal, or halfway between the steel
  column's face and the edge of its base plate (13.2.7.1), each direction and
  each side: ``φ Mn`` with ``φ`` from the net tensile strain (21.2.2).
* Minimum steel ``0.0018 Ag`` (Grade 420, 24.4.3.2 via 13.3.3), spacing at most
  ``min(3h, 450 mm)``, and in a rectangular footing the band of the short
  direction ``2 / (β + 1)`` of the steel needed under the support (13.3.3.3).
* Bearing of the footprint on the footing ``φ 0.85 f'c A1 √(A2/A1)``,
  ``√(A2/A1) ≤ 2`` (22.8).
* Development of straight bars past the critical section (25.4.2.3, simplified
  with ``ψt = ψe = 1``).

Not covered: combined and strip footings, mats, piles, footings in net uplift
under strength loads (top steel), and the moment transfer of an edge or corner
punching perimeter (the shear part is checked, a note says the rest is not).
Anything outside the method is reported, never a pass.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

PHI_SHEAR = 0.75
PHI_BEARING = 0.65
ES = 200_000.0
"""Modulus of the reinforcement, MPa."""
MIN_DEPTH = 150.0
"""ACI 318-19 13.3.1.2: d of a footing on soil, mm."""
MIN_CONTACT = 0.5
"""Smallest share of the footing in contact with the soil under service loads."""
GRID = 160
"""Points per side of the grid the pressure integrals run on."""

REQUIRES_VERIFICATION = "Requires verification"


# ───────────────────────────── inputs ─────────────────────────────
@dataclass(frozen=True)
class FootingLoad:
    """A support reaction in global axes: force (N) and moment (N·mm) on the structure."""

    force: tuple[float, float, float]
    moment: tuple[float, float, float] = (0.0, 0.0, 0.0)
    label: str = ""


@dataclass(frozen=True)
class Footing:
    """One isolated footing, in N, mm and MPa."""

    length_x: float
    width_y: float
    thickness: float
    cx: float
    """Footprint of the support on the footing along X (pedestal, column or plate)."""
    cy: float
    offset_x: float = 0.0
    """Support centre minus footing centre, along X."""
    offset_y: float = 0.0
    flex_cx: float | None = None
    """Width of the section the moment is taken at (13.2.7.1); None = ``cx``."""
    flex_cy: float | None = None
    pedestal_height: float = 0.0
    """0 = no pedestal: the support sits on the footing."""
    soil_cover: float = 0.0
    """Fill above the top of the footing."""
    fc: float = 21.0
    fy: float = 420.0
    lam: float = 1.0
    cover: float = 75.0
    """Clear cover to the bottom bars."""
    bar_x_diameter: float = 16.0
    """Bars running along X (bottom layer)."""
    bar_x_spacing: float = 200.0
    bar_y_diameter: float = 16.0
    """Bars running along Y (on top of the X bars)."""
    bar_y_spacing: float = 200.0
    concrete_weight: float = 23.6e-6
    """N/mm³ (23.6 kN/m³)."""
    soil_weight: float = 18.0e-6
    bearing_allowable: float = 0.15
    """Gross allowable bearing pressure qa, MPa."""
    friction: float = 0.45
    fs_overturning: float = 1.5
    fs_sliding: float = 1.5

    @property
    def area(self) -> float:
        return self.length_x * self.width_y

    @property
    def d_x(self) -> float:
        """Effective depth of the X bars (bottom layer)."""
        return self.thickness - self.cover - self.bar_x_diameter / 2.0

    @property
    def d_y(self) -> float:
        """Effective depth of the Y bars (on the X bars)."""
        return self.thickness - self.cover - self.bar_x_diameter - self.bar_y_diameter / 2.0

    def steel_area(self, direction: str) -> float:
        """Bars running along ``direction`` over the whole footing width, mm²."""
        db, s, width = (
            (self.bar_x_diameter, self.bar_x_spacing, self.width_y)
            if direction == "x"
            else (self.bar_y_diameter, self.bar_y_spacing, self.length_x)
        )
        return math.pi * db**2 / 4.0 * width / s

    def weight(self) -> float:
        """Footing, pedestal and fill, N."""
        footing = self.area * self.thickness * self.concrete_weight
        pedestal = self.cx * self.cy * self.pedestal_height * self.concrete_weight
        fill = max(self.area - self.cx * self.cy, 0.0) * self.soil_cover * self.soil_weight
        return footing + pedestal + fill


# ───────────────────────────── results ─────────────────────────────
@dataclass
class FootingCheck:
    name: str
    ratio: float
    reference: str
    value: str = ""
    load: str = ""


@dataclass
class FootingResult:
    checks: list[FootingCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    requires_verification: str = ""
    q_max: float = 0.0
    """Largest service pressure, MPa."""
    contact: float = 1.0
    """Smallest share of the footing in contact under service loads."""
    pressure: Pressure | None = None
    """The service pressure with the largest q,max (for the pressure plan)."""
    pressure_load: str = ""

    @property
    def governing(self) -> FootingCheck | None:
        return max(self.checks, key=lambda c: c.ratio, default=None)

    def ratio(self, name: str) -> float:
        return max((c.ratio for c in self.checks if c.name == name), default=0.0)

    def _keep(self, check: FootingCheck) -> None:
        for i, old in enumerate(self.checks):
            if old.name == check.name:
                if check.ratio > old.ratio:
                    self.checks[i] = check
                return
        self.checks.append(check)

    def _note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


# ───────────────────────────── statics ─────────────────────────────
@dataclass(frozen=True)
class BaseActions:
    """The resultant at the underside of the footing, at its centre."""

    n: float
    """Downward force (compression positive)."""
    mx: float
    my: float
    hx: float
    hy: float

    @property
    def ex(self) -> float:
        return self.my / self.n

    @property
    def ey(self) -> float:
        return -self.mx / self.n


def base_actions(footing: Footing, load: FootingLoad, *, with_weight: bool) -> BaseActions:
    """The footing's actions at its underside: the reaction reversed, moved down, plus weight."""
    force = -np.asarray(load.force, dtype=float)
    moment = -np.asarray(load.moment, dtype=float)
    arm = np.array(
        [footing.offset_x, footing.offset_y, footing.pedestal_height + footing.thickness]
    )
    moment = moment + np.cross(arm, force)
    n = -force[2] + (footing.weight() if with_weight else 0.0)
    return BaseActions(
        n=float(n), mx=float(moment[0]), my=float(moment[1]), hx=float(force[0]), hy=float(force[1])
    )


def top_moments(footing: Footing, load: FootingLoad) -> tuple[float, float]:
    """``(Mx, My)`` the support passes into the top of the footing (for punching)."""
    force = -np.asarray(load.force, dtype=float)
    moment = -np.asarray(load.moment, dtype=float) + np.cross(
        np.array([0.0, 0.0, footing.pedestal_height]), force
    )
    return float(moment[0]), float(moment[1])


# ───────────────────────────── soil pressure ─────────────────────────────
@dataclass(frozen=True)
class Pressure:
    """``q(x, y) = max(a + b x + c y, 0)`` on the footing, x and y from its centre."""

    a: float
    b: float
    c: float
    length_x: float
    width_y: float

    def at(self, x: np.ndarray | float, y: np.ndarray | float) -> np.ndarray:
        return np.maximum(self.a + self.b * np.asarray(x) + self.c * np.asarray(y), 0.0)

    @property
    def q_max(self) -> float:
        hx, hy = self.length_x / 2.0, self.width_y / 2.0
        return float(self.a + abs(self.b) * hx + abs(self.c) * hy)

    def region(
        self, x0: float, x1: float, y0: float, y1: float, n: int = GRID
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        """Midpoints ``(x, y, q)`` of an ``n`` × ``n`` grid on a sub-rectangle, and the cell area."""
        if x1 <= x0 or y1 <= y0:
            empty = np.zeros(0)
            return empty, empty, empty, 0.0
        xs = x0 + (np.arange(n) + 0.5) * (x1 - x0) / n
        ys = y0 + (np.arange(n) + 0.5) * (y1 - y0) / n
        x, y = np.meshgrid(xs, ys, indexing="ij")
        return x, y, self.at(x, y), (x1 - x0) * (y1 - y0) / n**2

    def force(self, x0: float, x1: float, y0: float, y1: float) -> float:
        """Soil force on a sub-rectangle."""
        _x, _y, q, da = self.region(x0, x1, y0, y1)
        return float(q.sum() * da)

    def contact(self) -> float:
        """Share of the footing with pressure on it."""
        hx, hy = self.length_x / 2.0, self.width_y / 2.0
        _x, _y, q, _da = self.region(-hx, hx, -hy, hy)
        return float((q > 0.0).mean())


def soil_pressure(length: float, width: float, n: float, ex: float, ey: float) -> Pressure | None:
    """The compression-only pressure plane under ``n`` at ``(ex, ey)``; None when it overturns."""
    if n <= 0.0:
        return None
    hx, hy = length / 2.0, width / 2.0
    if abs(ex) >= hx * (1.0 - 1e-9) or abs(ey) >= hy * (1.0 - 1e-9):
        return None
    area = length * width
    if abs(ex) / length + abs(ey) / width <= 1.0 / 6.0 + 1e-12:
        return Pressure(
            n / area, 12.0 * n * ex / (width * length**3), 12.0 * n * ey / (length * width**3),
            length, width,
        )  # fmt: skip
    small = 1e-9
    if abs(ey) <= small * width:
        lc = 3.0 * (hx - abs(ex))
        q_max = 2.0 * n / (width * lc)
        b = math.copysign(q_max / lc, ex)
        return Pressure(-q_max * (hx - lc) / lc, b, 0.0, length, width)
    if abs(ex) <= small * length:
        lc = 3.0 * (hy - abs(ey))
        q_max = 2.0 * n / (length * lc)
        c = math.copysign(q_max / lc, ey)
        return Pressure(-q_max * (hy - lc) / lc, 0.0, c, length, width)
    return _biaxial(length, width, n, ex, ey)


def _biaxial(length: float, width: float, n: float, ex: float, ey: float) -> Pressure | None:
    """Newton on the contact plane, in coordinates scaled to the half sides."""
    hx, hy = length / 2.0, width / 2.0
    k = GRID
    u = -1.0 + (np.arange(k) + 0.5) * 2.0 / k
    uu, vv = np.meshgrid(u, u, indexing="ij")
    basis = np.stack([np.ones_like(uu), uu, vv]).reshape(3, -1)
    da = 4.0 / k**2
    target = np.array([1.0, ex / hx, ey / hy])
    # Pressure in units of n / area: ∫ q dA over the unit square [-1, 1]² is 4 · mean.
    p = np.array([0.25, 0.75 * target[1], 0.75 * target[2]])

    def residual(params: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        q = np.maximum(params @ basis, 0.0)
        r = basis @ q * da - target
        return r, q

    r, q = residual(p)
    for _ in range(200):
        if np.linalg.norm(r) < 1e-10:
            break
        active = q > 0.0
        if not active.any():
            return None
        jac = (basis[:, active] * da) @ basis[:, active].T
        try:
            step = np.linalg.solve(jac, -r)
        except np.linalg.LinAlgError:
            return None
        t = 1.0
        while t > 1e-6:
            trial = p + t * step
            r_new, q_new = residual(trial)
            if np.linalg.norm(r_new) < np.linalg.norm(r):
                p, r, q = trial, r_new, q_new
                break
            t /= 2.0
        else:
            return None
    if np.linalg.norm(r) > 1e-6:
        return None
    scale = n / (hx * hy)
    return Pressure(scale * p[0], scale * p[1] / hx, scale * p[2] / hy, length, width)


# ───────────────────────────── concrete helpers ─────────────────────────────
def size_effect(d: float) -> float:
    """``λs`` of ACI 318-19 22.5.5.1.3 (d in mm)."""
    return min(1.0, math.sqrt(2.0 / (1.0 + 0.004 * d)))


def _sqrt_fc(fc: float) -> float:
    return math.sqrt(min(fc, 69.0))  # √f'c ≤ 8.3 MPa (22.5.3.1)


def beta1(fc: float) -> float:
    return max(0.65, min(0.85, 0.85 - 0.05 * (fc - 28.0) / 7.0))


def flexural_strength(
    steel: float, b: float, d: float, fc: float, fy: float
) -> tuple[float, float]:
    """``(φ Mn, φ)`` of a singly reinforced rectangle."""
    a = steel * fy / (0.85 * fc * b)
    mn = steel * fy * (d - a / 2.0)
    c = a / beta1(fc)
    eps_t = 0.003 * (d - c) / c if c > 0.0 else math.inf
    eps_y = fy / ES
    if eps_t >= eps_y + 0.003:
        phi = 0.90
    elif eps_t <= eps_y:
        phi = 0.65
    else:
        phi = 0.65 + 0.25 * (eps_t - eps_y) / 0.003
    return phi * mn, phi


def required_steel(mu: float, b: float, d: float, fc: float, fy: float) -> float:
    """As that gives ``0.9 Mn = mu`` (inf when the section cannot)."""
    if mu <= 0.0:
        return 0.0
    k = 2.0 * mu / (0.9 * 0.85 * fc * b * d**2)
    if k >= 1.0:
        return math.inf
    return 0.85 * fc * b * d / fy * (1.0 - math.sqrt(1.0 - k))


def min_steel_ratio(fy: float) -> float:
    """ACI 318-19 Table 24.4.3.2 (slabs and footings), on the gross area."""
    return 0.0020 if fy < 420.0 else max(0.0018 * 420.0 / fy, 0.0014)


def development_length(db: float, fc: float, fy: float, lam: float = 1.0) -> float:
    """Straight bar in tension, ACI 318-19 Table 25.4.2.3 (ψt = ψe = 1), mm."""
    psi_g = 1.0 if fy <= 420.0 else (1.15 if fy <= 550.0 else 1.3)
    k = 2.1 if db <= 20.0 else 1.7
    return max(fy * psi_g / (k * lam * _sqrt_fc(fc)) * db, 300.0)


# ───────────────────────────── the check ─────────────────────────────
def check_footing(
    footing: Footing,
    service: Sequence[FootingLoad],
    strength: Sequence[FootingLoad],
) -> FootingResult:
    """Every soil check over ``service`` and every ACI check over ``strength``."""
    out = FootingResult()
    _static_checks(footing, out)
    for load in service:
        _service_checks(footing, out, load)
    for load in strength:
        _strength_checks(footing, out, load)
    if not service:
        out._note("No service load: the soil was not checked.")
    if not strength:
        out._note("No strength load: the concrete was not checked.")
    return out


def _static_checks(f: Footing, out: FootingResult) -> None:
    section_checks(f, out)
    _development_checks(f, out)


def section_checks(f: Any, out: FootingResult) -> None:
    """Depth, minimum steel and spacing of a footing slab (isolated or combined)."""
    d = min(f.d_x, f.d_y)
    out._keep(
        FootingCheck(
            "Minimum depth", MIN_DEPTH / d if d > 0 else math.inf, "ACI 318-19 13.3.1.2",
            f"d = {d:.0f} mm ≥ {MIN_DEPTH:.0f} mm",
        )
    )  # fmt: skip
    rho = min_steel_ratio(f.fy)
    for direction, width in (("x", f.width_y), ("y", f.length_x)):
        as_min = rho * width * f.thickness
        provided = f.steel_area(direction)
        out._keep(
            FootingCheck(
                f"Minimum steel ({direction.upper()} bars)", as_min / provided,
                "ACI 318-19 13.3.3, 24.4.3.2",
                f"As = {provided:.0f} mm², As,min = {as_min:.0f} mm²",
            )
        )  # fmt: skip
    s_max = min(3.0 * f.thickness, 450.0)
    spacing = max(f.bar_x_spacing, f.bar_y_spacing)
    out._keep(
        FootingCheck(
            "Bar spacing", spacing / s_max, "ACI 318-19 7.7.2.3",
            f"s = {spacing:.0f} mm, s,max = {s_max:.0f} mm",
        )
    )  # fmt: skip


def _development_checks(f: Footing, out: FootingResult) -> None:
    for direction in ("x", "y"):
        db = f.bar_x_diameter if direction == "x" else f.bar_y_diameter
        side, off, flex = (
            (f.length_x, f.offset_x, f.flex_cx or f.cx)
            if direction == "x"
            else (f.width_y, f.offset_y, f.flex_cy or f.cy)
        )
        available = side / 2.0 - abs(off) - flex / 2.0 - f.cover
        ld = development_length(db, f.fc, f.fy, f.lam)
        out._keep(
            FootingCheck(
                f"Development ({direction.upper()} bars)",
                ld / available if available > 0 else math.inf,
                "ACI 318-19 25.4.2.3",
                f"ld = {ld:.0f} mm, available {available:.0f} mm (hooks if short)",
            )
        )


def _service_checks(f: Footing, out: FootingResult, load: FootingLoad) -> None:
    soil_checks(f, out, base_actions(f, load, with_weight=True), load.label)


def soil_checks(f: Any, out: FootingResult, act: BaseActions, label: str) -> None:
    """Uplift, overturning, sliding, bearing and contact under one service resultant.

    ``f`` carries the plan (``length_x``, ``width_y``), ``bearing_allowable``,
    ``friction``, ``fs_overturning`` and ``fs_sliding``.
    """
    load = FootingLoad((0.0, 0.0, 0.0), label=label)
    if act.n <= 0.0:
        out._keep(
            FootingCheck(
                "Uplift of the footing", math.inf, "Equilibrium",
                f"net upward {-act.n / 1e3:.4g} kN", load.label,
            )
        )  # fmt: skip
        return
    out._keep(FootingCheck("Uplift of the footing", 0.0, "Equilibrium", "", load.label))
    for axis, moment, half in (("X", act.my, f.length_x / 2.0), ("Y", act.mx, f.width_y / 2.0)):
        fs = act.n * half / abs(moment) if abs(moment) > 0.0 else math.inf
        out._keep(
            FootingCheck(
                f"Overturning about {'Y' if axis == 'X' else 'X'}",
                f.fs_overturning / fs if fs > 0 else math.inf,
                "N (B/2) / M ≥ FS",
                f"FS = {fs:.3g} (required {f.fs_overturning:g})",
                load.label,
            )
        )
    h = math.hypot(act.hx, act.hy)
    fs_slide = f.friction * act.n / h if h > 0.0 else math.inf
    out._keep(
        FootingCheck(
            "Sliding", f.fs_sliding / fs_slide if fs_slide > 0 else math.inf, "μ N / H ≥ FS",
            f"FS = {fs_slide:.3g} (required {f.fs_sliding:g})", load.label,
        )
    )  # fmt: skip
    pressure = soil_pressure(f.length_x, f.width_y, act.n, act.ex, act.ey)
    if pressure is None:
        out._keep(
            FootingCheck(
                "Soil bearing", math.inf, "Soil report",
                "resultant outside the footing (overturns)", load.label,
            )
        )  # fmt: skip
        return
    q_max = pressure.q_max
    if out.pressure is None or q_max > out.q_max:
        out.pressure, out.pressure_load = pressure, load.label
    out.q_max = max(out.q_max, q_max)
    out._keep(
        FootingCheck(
            "Soil bearing", q_max / f.bearing_allowable, "Soil report (qa)",
            f"q,max = {q_max * 1e3:.4g} kPa, qa = {f.bearing_allowable * 1e3:.4g} kPa",
            load.label,
        )
    )  # fmt: skip
    contact = pressure.contact()
    out.contact = min(out.contact, contact)
    out._keep(
        FootingCheck(
            "Soil contact", MIN_CONTACT / contact if contact > 0 else math.inf,
            f"≥ {MIN_CONTACT:.0%} of the footing in contact",
            f"{contact:.0%} in contact", load.label,
        )
    )  # fmt: skip


def _strength_checks(f: Footing, out: FootingResult, load: FootingLoad) -> None:
    act = base_actions(f, load, with_weight=False)
    if act.n <= 0.0:
        out.requires_verification = (
            "A strength load lifts the footing (net tension): the top reinforcement and "
            "the footing's own weight against uplift are not checked. Requires verification."
        )
        out._note(out.requires_verification)
        return
    pressure = soil_pressure(f.length_x, f.width_y, act.n, act.ex, act.ey)
    if pressure is None:
        out._keep(
            FootingCheck(
                "Factored soil pressure", math.inf, "Equilibrium",
                "resultant outside the footing", load.label,
            )
        )  # fmt: skip
        return
    hx, hy = f.length_x / 2.0, f.width_y / 2.0
    ox, oy = f.offset_x, f.offset_y
    sqrt_fc = _sqrt_fc(f.fc)

    # One-way shear and flexure, each direction and side.
    for direction in ("x", "y"):
        if direction == "x":
            d, width, c, flex, o, half = f.d_x, f.width_y, f.cx, f.flex_cx or f.cx, ox, hx
        else:
            d, width, c, flex, o, half = f.d_y, f.length_x, f.cy, f.flex_cy or f.cy, oy, hy
        As = f.steel_area(direction)
        lam_s = size_effect(d)
        rho = As / (width * d)
        vc = min(0.66 * lam_s * f.lam * rho ** (1.0 / 3.0), 0.42 * f.lam) * sqrt_fc * width * d
        worst_v, worst_m = 0.0, 0.0
        for sign in (1.0, -1.0):
            section_v = o + sign * (c / 2.0 + d)
            section_m = o + sign * flex / 2.0
            for section, kind in ((section_v, "v"), (section_m, "m")):
                lo, hi = (section, half) if sign > 0 else (-half, section)
                if hi <= lo:
                    continue
                if direction == "x":
                    x, _y, q, da = pressure.region(lo, hi, -hy, hy)
                    arm = np.abs(x - section)
                else:
                    _x, y, q, da = pressure.region(-hx, hx, lo, hi)
                    arm = np.abs(y - section)
                if kind == "v":
                    worst_v = max(worst_v, float(q.sum() * da))
                else:
                    worst_m = max(worst_m, float((q * arm).sum() * da))
        label = direction.upper()
        out._keep(
            FootingCheck(
                f"One-way shear ({label} direction)", worst_v / (PHI_SHEAR * vc),
                "ACI 318-19 22.5.5.1",
                f"Vu = {worst_v / 1e3:.4g} kN, φVc = {PHI_SHEAR * vc / 1e3:.4g} kN", load.label,
            )
        )  # fmt: skip
        phi_mn, phi = flexural_strength(As, width, d, f.fc, f.fy)
        out._keep(
            FootingCheck(
                f"Flexure ({label} bars)", worst_m / phi_mn, "ACI 318-19 13.2.7.1, 22.2",
                f"Mu = {worst_m / 1e6:.4g} kN·m, φMn = {phi_mn / 1e6:.4g} kN·m (φ = {phi:.2f})",
                load.label,
            )
        )  # fmt: skip
        long_side, short_side = max(f.length_x, f.width_y), min(f.length_x, f.width_y)
        short_bars = "y" if f.width_y < f.length_x else "x"
        if direction == short_bars and long_side > short_side * (1.0 + 1e-9):
            beta = long_side / short_side
            need = max(required_steel(worst_m, width, d, f.fc, f.fy),
                       min_steel_ratio(f.fy) * width * f.thickness)  # fmt: skip
            band = need * 2.0 / (beta + 1.0)
            in_band = As * short_side / long_side
            out._keep(
                FootingCheck(
                    f"Short-direction band ({label} bars)", band / in_band,
                    "ACI 318-19 13.3.3.3",
                    f"band {short_side:.0f} mm needs {band:.0f} mm², has {in_band:.0f} mm²",
                    load.label,
                )
            )  # fmt: skip

    # Two-way shear around the footprint.
    d = (f.d_x + f.d_y) / 2.0
    b1, b2 = f.cx + d, f.cy + d
    x0, x1 = max(ox - b1 / 2.0, -hx), min(ox + b1 / 2.0, hx)
    y0, y1 = max(oy - b2 / 2.0, -hy), min(oy + b2 / 2.0, hy)
    sides = [ox - b1 / 2.0 > -hx, ox + b1 / 2.0 < hx, oy - b2 / 2.0 > -hy, oy + b2 / 2.0 < hy]
    b0 = (sides[0] + sides[1]) * (y1 - y0) + (sides[2] + sides[3]) * (x1 - x0)
    if sum(sides) >= 2 and b0 > 0.0:
        alpha_s = {4: 40.0, 3: 30.0, 2: 20.0}[sum(sides)]
        beta = max(f.cx, f.cy) / min(f.cx, f.cy)
        lam_s = size_effect(d)
        vc = min(0.33, 0.17 * (1.0 + 2.0 / beta), 0.083 * (2.0 + alpha_s * d / b0))
        vc *= lam_s * f.lam * sqrt_fc
        vu_force = act.n - pressure.force(x0, x1, y0, y1)
        vu = vu_force / (b0 * d)
        mx, my = top_moments(f, load)
        if sum(sides) == 4:
            for moment, span, across in ((my, b1, b2), (mx, b2, b1)):
                gamma_v = 1.0 - 1.0 / (1.0 + 2.0 / 3.0 * math.sqrt(span / across))
                jc = d * span**3 / 6.0 + span * d**3 / 6.0 + d * across * span**2 / 2.0
                vu += gamma_v * abs(moment) * (span / 2.0) / jc
        elif abs(mx) + abs(my) > 1e-9 * max(act.n, 1.0) * max(f.cx, f.cy):
            out._note(
                "The punching perimeter reaches the footing's edge: its shear is checked, the "
                "transfer of the column moment by eccentric shear (8.4.4.2) is not."
            )
        out._keep(
            FootingCheck(
                "Two-way shear (punching)", vu / (PHI_SHEAR * vc), "ACI 318-19 22.6.5.2, 8.4.4.2",
                f"vu = {vu:.3g} MPa, φvc = {PHI_SHEAR * vc:.3g} MPa (b0 = {b0:.0f} mm, αs = {alpha_s:g})",
                load.label,
            )
        )  # fmt: skip
    else:
        out._note("The punching perimeter does not fit in the footing: one-way shear governs.")

    # Bearing of the footprint on the footing.
    a1 = f.cx * f.cy
    r_plan = min(2.0 * (hx - abs(ox)) / f.cx, 2.0 * (hy - abs(oy)) / f.cy)
    r_depth = min((f.cx + 4.0 * f.thickness) / f.cx, (f.cy + 4.0 * f.thickness) / f.cy)
    root = min(max(min(r_plan, r_depth), 1.0), 2.0)
    bearing = PHI_BEARING * 0.85 * f.fc * a1 * root
    out._keep(
        FootingCheck(
            "Bearing on the footing", act.n / bearing, "ACI 318-19 22.8",
            f"Pu = {act.n / 1e3:.4g} kN, φBn = {bearing / 1e3:.4g} kN", load.label,
        )
    )  # fmt: skip


# ───────────────────────────── sizing ─────────────────────────────
SOIL_CHECKS = ("Soil bearing", "Soil contact", "Overturning about X", "Overturning about Y")
SHEAR_CHECKS = (
    "One-way shear (X direction)",
    "One-way shear (Y direction)",
    "Two-way shear (punching)",
    "Minimum depth",
)
BAR_DIAMETERS = (12.0, 16.0, 20.0, 25.0, 32.0)


def _ok(result: FootingResult, names: Sequence[str], limit: float) -> bool:
    return all(result.ratio(name) <= limit for name in names)


def _steel_ok(result: FootingResult, limit: float) -> bool:
    return all(
        c.ratio <= limit
        for c in result.checks
        if c.name.startswith(("Flexure", "Minimum steel", "Short-direction", "Bar spacing"))
    )


def size_footing(
    footing: Footing,
    service: Sequence[FootingLoad],
    strength: Sequence[FootingLoad],
    *,
    limit: float = 1.0,
    step: float = 50.0,
    max_side: float = 8000.0,
) -> Footing | None:
    """The smallest footing (plan, then thickness, then bars) passing every check.

    The plan grows in ``step`` keeping the aspect ratio, the thickness from 300 mm
    in ``step``, then the bars: the largest spacing (multiple of 25 mm) of the
    smallest diameter that passes. None when no footing up to ``max_side`` does.
    """
    aspect = footing.width_y / footing.length_x
    min_side = max(footing.cx, footing.cy) + 2.0 * step

    def plan(base: Footing, length: float) -> Footing:
        width = max(round(length * aspect / step) * step, step)
        return replace(base, length_x=length, width_y=width)

    def bars_for(base: Footing) -> Footing | None:
        for db in BAR_DIAMETERS:
            top = int(min(3.0 * base.thickness, 450.0) // 25) * 25
            for spacing in range(top, 74, -25):
                trial = replace(
                    base,
                    bar_x_diameter=db, bar_x_spacing=float(spacing),
                    bar_y_diameter=db, bar_y_spacing=float(spacing),
                )  # fmt: skip
                if _steel_ok(check_footing(trial, [], strength), limit):
                    return trial
        return None

    length = max(round(min_side / step) * step, step)
    thickness = 300.0
    while length <= max_side and thickness <= 3000.0:
        trial = replace(plan(footing, length), thickness=thickness)
        if not _ok(check_footing(trial, service, []), SOIL_CHECKS, limit):
            length += step
            continue
        if not _ok(check_footing(trial, [], strength), SHEAR_CHECKS, limit):
            thickness += step
            continue
        bars = bars_for(trial)
        if bars is None:
            thickness += step
            continue
        final = check_footing(bars, service, strength)
        if final.governing is None or final.governing.ratio <= limit:
            return bars
        failing = {c.name for c in final.checks if c.ratio > limit}
        if any(
            name.startswith(("Development", "Bearing", "Sliding", "Overturning"))
            for name in failing
        ):
            length += step
        else:
            thickness += step
    return None


# ───────────────────────────── project data ─────────────────────────────
class FootingDesign(BaseModel):
    """The isolated footing under one support, as a project saves it (project units).

    ``column_x`` by ``column_y`` is what sits on the footing: the pedestal when
    ``pedestal_height > 0``, else the column, or the steel column's base plate.
    ``steel_x`` and ``steel_y`` are the steel column's own size on that plate:
    with them the moment is taken halfway between the column and the plate edge
    (ACI 318-19 13.2.7.1). Unit weights are force per length³.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    node_id: PositiveInt
    length_x: PositiveFloat
    width_y: PositiveFloat
    thickness: PositiveFloat
    offset_x: float = 0.0
    offset_y: float = 0.0
    column_x: PositiveFloat
    column_y: PositiveFloat
    steel_x: PositiveFloat | None = None
    steel_y: PositiveFloat | None = None
    pedestal_height: float = Field(default=0.0, ge=0.0)
    soil_cover: float = Field(default=0.0, ge=0.0)
    fc: PositiveFloat
    fy: PositiveFloat
    lam: float = Field(default=1.0, gt=0.0, le=1.0)
    cover: PositiveFloat
    bar_x_diameter: PositiveFloat
    bar_x_spacing: PositiveFloat
    bar_y_diameter: PositiveFloat
    bar_y_spacing: PositiveFloat
    concrete_weight: PositiveFloat
    soil_weight: PositiveFloat
    bearing_allowable: PositiveFloat
    friction: PositiveFloat = 0.45
    fs_overturning: PositiveFloat = 1.5
    fs_sliding: PositiveFloat = 1.5

    def plate_support_area(self) -> float:
        """A2 this footing gives a base plate on it: the pedestal top, else the footing plan.

        The concrete under the plate is at most this; AISC J8 caps the benefit at
        ``√(A2/A1) ≤ 2``.
        """
        if self.pedestal_height > 0.0:
            return self.column_x * self.column_y
        return self.length_x * self.width_y
