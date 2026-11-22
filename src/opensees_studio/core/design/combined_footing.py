"""Combined footings: one rectangular footing under two or more supports, ACI 318-19.

Same units, soil checks and slab checks as :mod:`.footing` (N, mm, MPa). The
footing is ``L`` along global X by ``B`` along global Y; its **long axis** is
the longer side, and the columns sit at ``(x, y)`` from its centre, each on its
own footprint (pedestal, column or base plate). A load is one reaction per
column, in the order of :attr:`CombinedFooting.columns`.

**Soil** (service loads): the resultant of every column plus the footing, the
pedestals and the fill, with the pressure plane of
:func:`~.footing.soil_pressure` (one- or two-way eccentricity, partial contact),
and the checks of :func:`~.footing.soil_checks`.

**Concrete** (strength loads, net pressure from the columns only):

* **Longitudinal beam.** The pressure is summed across the width into a line
  load; with each column's factored force at its centre and its moment about
  the transverse axis, the shear ``V(s)`` and the moment ``M(s)`` follow by
  statics along the long axis. Bottom bars along the long axis take the largest
  sagging moment outside the footprints (the cantilevers and under the
  columns), **top bars** the largest hogging moment between the columns; with
  no top bars a hogging moment is NG. One-way shear at ``d`` from every column
  face (22.5.5.1, ρw of the tension side).
* **Transverse beams** under each column (common practice, ACI 318-19 13.3.3
  leaves the method open): a band ``c + d`` wide along the long axis carries the
  column's force spread over the width ``B``, as a cantilever from the column's
  face; the bars across the long axis inside the band take it.
* **Punching** of each column at ``d/2`` (22.6.5.2) with the perimeter clipped
  by the footing's edges and ``γv M`` on an interior perimeter, the **bearing**
  of each footprint (22.8), minimum depth, minimum steel and spacing, and the
  development of the bars (the long bottom bars past the outer faces, with
  ``ld`` reduced by ``As,req / As,prov``, 25.4.10.1).

Not covered: a perimeter that overlaps another column's, strap footings, and a
footing in net uplift under strength loads (requires verification).

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core.design.footing import (
    PHI_BEARING,
    PHI_SHEAR,
    BaseActions,
    FootingCheck,
    FootingLoad,
    FootingResult,
    Pressure,
    _sqrt_fc,
    development_length,
    flexural_strength,
    required_steel,
    section_checks,
    size_effect,
    soil_checks,
    soil_pressure,
)

STATIONS = 1200
"""Strips along the long axis the beam statics are summed on."""


@dataclass(frozen=True)
class FootingColumn:
    """One support on a combined footing (mm, from the footing centre)."""

    x: float
    y: float
    cx: float
    cy: float
    flex_cx: float | None = None
    flex_cy: float | None = None
    pedestal_height: float = 0.0
    label: str = ""


@dataclass(frozen=True)
class CombinedLoad:
    """One alternative: the reaction of every column, in the footing's column order."""

    reactions: tuple[FootingLoad, ...]
    label: str = ""


@dataclass(frozen=True)
class CombinedFooting:
    length_x: float
    width_y: float
    thickness: float
    columns: tuple[FootingColumn, ...]
    soil_cover: float = 0.0
    fc: float = 21.0
    fy: float = 420.0
    lam: float = 1.0
    cover: float = 75.0
    bar_x_diameter: float = 16.0
    bar_x_spacing: float = 200.0
    bar_y_diameter: float = 16.0
    bar_y_spacing: float = 200.0
    top_bar_diameter: float = 0.0
    """Top bars along the long axis; 0 = none."""
    top_bar_spacing: float = 200.0
    concrete_weight: float = 23.6e-6
    soil_weight: float = 18.0e-6
    bearing_allowable: float = 0.15
    friction: float = 0.45
    fs_overturning: float = 1.5
    fs_sliding: float = 1.5

    @property
    def axis(self) -> str:
        """``x`` or ``y``: the long axis."""
        return "x" if self.length_x >= self.width_y else "y"

    @property
    def area(self) -> float:
        return self.length_x * self.width_y

    @property
    def d_x(self) -> float:
        return self.thickness - self.cover - self.bar_x_diameter / 2.0

    @property
    def d_y(self) -> float:
        return self.thickness - self.cover - self.bar_x_diameter - self.bar_y_diameter / 2.0

    @property
    def d_top(self) -> float:
        return self.thickness - self.cover - self.top_bar_diameter / 2.0

    def steel_area(self, direction: str) -> float:
        db, s, width = (
            (self.bar_x_diameter, self.bar_x_spacing, self.width_y)
            if direction == "x"
            else (self.bar_y_diameter, self.bar_y_spacing, self.length_x)
        )
        return math.pi * db**2 / 4.0 * width / s

    def top_steel_area(self) -> float:
        if self.top_bar_diameter <= 0.0:
            return 0.0
        width = self.width_y if self.axis == "x" else self.length_x
        return math.pi * self.top_bar_diameter**2 / 4.0 * width / self.top_bar_spacing

    def weight(self) -> float:
        footing = self.area * self.thickness * self.concrete_weight
        pedestals = sum(c.cx * c.cy * c.pedestal_height for c in self.columns)
        covered = sum(c.cx * c.cy for c in self.columns)
        fill = max(self.area - covered, 0.0) * self.soil_cover * self.soil_weight
        return footing + pedestals * self.concrete_weight + fill


# ───────────────────────────── statics ─────────────────────────────
def _column_action(
    f: CombinedFooting, column: FootingColumn, load: FootingLoad
) -> tuple[np.ndarray, np.ndarray]:
    """Force and moment a column puts on the footing, at the column's base on top of it."""
    force = -np.asarray(load.force, dtype=float)
    moment = -np.asarray(load.moment, dtype=float)
    moment = moment + np.cross(np.array([0.0, 0.0, column.pedestal_height]), force)
    return force, moment


def combined_actions(f: CombinedFooting, load: CombinedLoad, *, with_weight: bool) -> BaseActions:
    """The resultant at the underside of the footing, at its centre."""
    total_f = np.zeros(3)
    total_m = np.zeros(3)
    for column, reaction in zip(f.columns, load.reactions, strict=True):
        force, moment = _column_action(f, column, reaction)
        arm = np.array([column.x, column.y, f.thickness])
        total_f += force
        total_m += moment + np.cross(arm, force)
    n = -total_f[2] + (f.weight() if with_weight else 0.0)
    return BaseActions(
        n=float(n),
        mx=float(total_m[0]),
        my=float(total_m[1]),
        hx=float(total_f[0]),
        hy=float(total_f[1]),
    )


@dataclass
class BeamDiagram:
    """Shear and moment along the long axis (positive moment: bottom in tension)."""

    stations: np.ndarray
    shear: np.ndarray
    moment: np.ndarray


def beam_diagram(
    f: CombinedFooting, pressure: Pressure, load: CombinedLoad, stations: np.ndarray
) -> BeamDiagram:
    """``V(s)`` and ``M(s)`` of the part of the footing before each station."""
    half_l = (f.length_x if f.axis == "x" else f.width_y) / 2.0
    half_b = (f.width_y if f.axis == "x" else f.length_x) / 2.0
    n = STATIONS
    t = -half_l + (np.arange(n) + 0.5) * (2.0 * half_l / n)
    across = -half_b + (np.arange(80) + 0.5) * (2.0 * half_b / 80)
    if f.axis == "x":
        q = pressure.at(t[:, None], across[None, :])
    else:
        q = pressure.at(across[None, :], t[:, None])
    line = q.sum(axis=1) * (2.0 * half_b / 80) * (2.0 * half_l / n)  # force per strip
    shear = np.empty_like(stations)
    moment = np.empty_like(stations)
    for k, s in enumerate(stations):
        before = t < s
        v = float(line[before].sum())
        m = float((line[before] * (s - t[before])).sum())
        for column, reaction in zip(f.columns, load.reactions, strict=True):
            pos = column.x if f.axis == "x" else column.y
            if pos >= s:
                continue
            force, moment_vec = _column_action(f, column, reaction)
            p = -force[2]
            v -= p
            m -= p * (s - pos)
            m += moment_vec[1] if f.axis == "x" else -moment_vec[0]
        shear[k], moment[k] = v, m
    return BeamDiagram(stations, shear, moment)


# ───────────────────────────── the check ─────────────────────────────
def check_combined_footing(
    footing: CombinedFooting,
    service: Sequence[CombinedLoad],
    strength: Sequence[CombinedLoad],
) -> FootingResult:
    """Every soil check over ``service`` and every ACI check over ``strength``."""
    out = FootingResult()
    section_checks(footing, out)
    _development(footing, out)
    for load in service:
        soil_checks(footing, out, combined_actions(footing, load, with_weight=True), load.label)
    for load in strength:
        _strength(footing, out, load)
    if not service:
        out._note("No service load: the soil was not checked.")
    if not strength:
        out._note("No strength load: the concrete was not checked.")
    return out


def _long(f: CombinedFooting, column: FootingColumn) -> tuple[float, float, float]:
    """``(position, footprint, flexure width)`` of a column along the long axis."""
    if f.axis == "x":
        return column.x, column.cx, column.flex_cx or column.cx
    return column.y, column.cy, column.flex_cy or column.cy


def _cross(f: CombinedFooting, column: FootingColumn) -> tuple[float, float, float]:
    if f.axis == "x":
        return column.y, column.cy, column.flex_cy or column.cy
    return column.x, column.cx, column.flex_cx or column.cx


def _development(f: CombinedFooting, out: FootingResult) -> None:
    """The bars across the long axis, past the column faces (the long bars: per load)."""
    half_b = (f.width_y if f.axis == "x" else f.length_x) / 2.0
    cross_dir = "y" if f.axis == "x" else "x"
    db = f.bar_y_diameter if cross_dir == "y" else f.bar_x_diameter
    room = min(half_b - abs(p) - w / 2.0 for p, _c, w in (_cross(f, c) for c in f.columns))
    room -= f.cover
    ld = development_length(db, f.fc, f.fy, f.lam)
    out._keep(
        FootingCheck(
            f"Development ({cross_dir.upper()} bars)",
            ld / room if room > 0 else math.inf,
            "ACI 318-19 25.4.2.3",
            f"ld = {ld:.0f} mm, available {room:.0f} mm (hooks if short)",
        )
    )


def _strength(f: CombinedFooting, out: FootingResult, load: CombinedLoad) -> None:
    act = combined_actions(f, load, with_weight=False)
    if act.n <= 0.0:
        out.requires_verification = (
            "A strength load lifts the footing (net tension): not checked. Requires verification."
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
    _longitudinal(f, out, load, pressure)
    for column, reaction in zip(f.columns, load.reactions, strict=True):
        force, moment = _column_action(f, column, reaction)
        _transverse(f, out, column, float(-force[2]), load.label)
        _punching(f, out, column, float(-force[2]), moment, pressure, load.label)
        _bearing(f, out, column, float(-force[2]), load.label)


def _longitudinal(
    f: CombinedFooting, out: FootingResult, load: CombinedLoad, pressure: Pressure
) -> None:
    half_l = (f.length_x if f.axis == "x" else f.width_y) / 2.0
    width = f.width_y if f.axis == "x" else f.length_x
    long_dir = f.axis
    d_bot = f.d_x if long_dir == "x" else f.d_y
    as_bot = f.steel_area(long_dir)
    as_top = f.top_steel_area()
    spans = [_long(f, c) for c in f.columns]

    def inside(s: float) -> bool:
        return any(p - w / 2.0 + 1e-6 < s < p + w / 2.0 - 1e-6 for p, _c, w in spans)

    candidates = list(np.linspace(-half_l, half_l, 241)[1:-1])
    for p, c, w in spans:
        candidates += [p - w / 2.0, p + w / 2.0, p - c / 2.0 - d_bot, p + c / 2.0 + d_bot]
    flexure = np.array([s for s in candidates if -half_l < s < half_l and not inside(s)])
    shear_at = np.array(
        [
            s
            for p, c, _w in spans
            for s in (p - c / 2.0 - d_bot, p + c / 2.0 + d_bot)
            if -half_l < s < half_l and not inside(s)
        ]
    )
    diagram = beam_diagram(f, pressure, load, flexure)
    sag = float(max(diagram.moment.max(initial=0.0), 0.0))
    hog = float(max((-diagram.moment).max(initial=0.0), 0.0))
    label = long_dir.upper()
    # Bottom bars past the outer faces: ld cut by As,req / As,prov (25.4.10.1).
    db = f.bar_x_diameter if long_dir == "x" else f.bar_y_diameter
    outer = (min(p - w / 2.0 for p, _c, w in spans), max(p + w / 2.0 for p, _c, w in spans))
    faces = beam_diagram(f, pressure, load, np.array(outer))
    room = min(outer[0] + half_l, half_l - outer[1]) - f.cover
    need = max(required_steel(max(float(faces.moment.max()), 0.0), width, d_bot, f.fc, f.fy), 0.0)
    ld = development_length(db, f.fc, f.fy, f.lam)
    ld_eff = max(ld * min(need / as_bot, 1.0), 300.0) if as_bot > 0 else math.inf
    out._keep(
        FootingCheck(
            f"Development ({label} bars)", ld_eff / room if room > 0 else math.inf,
            "ACI 318-19 25.4.2.3, 25.4.10.1",
            f"ld = {ld:.0f} mm × As,req/As = {ld_eff:.0f} mm, available {room:.0f} mm",
            load.label,
        )
    )  # fmt: skip
    phi_mn, phi = flexural_strength(as_bot, width, d_bot, f.fc, f.fy)
    out._keep(
        FootingCheck(
            f"Flexure, bottom ({label} bars)", sag / phi_mn, "ACI 318-19 13.2.7.1, 22.2",
            f"Mu+ = {sag / 1e6:.4g} kN·m, φMn = {phi_mn / 1e6:.4g} kN·m (φ = {phi:.2f})",
            load.label,
        )
    )  # fmt: skip
    if hog > 0.0:
        if as_top > 0.0:
            phi_top, phi_t = flexural_strength(as_top, width, f.d_top, f.fc, f.fy)
            ratio = hog / phi_top
            value = f"Mu- = {hog / 1e6:.4g} kN·m, φMn = {phi_top / 1e6:.4g} kN·m (φ = {phi_t:.2f})"
        else:
            ratio = math.inf
            value = f"Mu- = {hog / 1e6:.4g} kN·m with no top bars: add them"
        out._keep(
            FootingCheck(
                f"Flexure, top ({label} bars)", ratio, "ACI 318-19 22.2", value, load.label
            )
        )
    if shear_at.size:
        sd = beam_diagram(f, pressure, load, shear_at)
        sqrt_fc = _sqrt_fc(f.fc)
        worst = 0.0
        capacity = math.inf
        for v, m in zip(sd.shear, sd.moment, strict=True):
            tension = as_bot if m >= 0.0 or as_top <= 0.0 else as_top
            d = d_bot if m >= 0.0 or as_top <= 0.0 else f.d_top
            rho = tension / (width * d)
            vc = min(0.66 * size_effect(d) * f.lam * rho ** (1 / 3), 0.42 * f.lam)
            vc *= sqrt_fc * width * d
            if abs(v) / (PHI_SHEAR * vc) > (worst / capacity if capacity < math.inf else -1):
                worst, capacity = abs(v), PHI_SHEAR * vc
        out._keep(
            FootingCheck(
                f"One-way shear ({label} direction)", worst / capacity, "ACI 318-19 22.5.5.1",
                f"Vu = {worst / 1e3:.4g} kN, φVc = {capacity / 1e3:.4g} kN", load.label,
            )
        )  # fmt: skip


def _transverse(
    f: CombinedFooting, out: FootingResult, column: FootingColumn, pu: float, label: str
) -> None:
    if pu <= 0.0:
        return
    cross_dir = "y" if f.axis == "x" else "x"
    half_b = (f.width_y if f.axis == "x" else f.length_x) / 2.0
    length = f.length_x if f.axis == "x" else f.width_y
    d = f.d_y if cross_dir == "y" else f.d_x
    db, spacing = (
        (f.bar_y_diameter, f.bar_y_spacing)
        if cross_dir == "y"
        else (f.bar_x_diameter, f.bar_x_spacing)
    )
    _pos, c_long, _w = _long(f, column)
    offset, _c, flex = _cross(f, column)
    band = min(c_long + d, length)
    arm = half_b + abs(offset) - flex / 2.0
    mu = pu / (2.0 * half_b) * arm**2 / 2.0
    as_band = math.pi * db**2 / 4.0 * band / spacing
    phi_mn, phi = flexural_strength(as_band, band, d, f.fc, f.fy)
    out._keep(
        FootingCheck(
            f"Transverse flexure under the columns ({cross_dir.upper()} bars)", mu / phi_mn,
            "ACI 318-19 13.3.3 (transverse beam)",
            f"{column.label}: band {band:.0f} mm, Mu = {mu / 1e6:.4g} kN·m, "
            f"φMn = {phi_mn / 1e6:.4g} kN·m (φ = {phi:.2f})",
            label,
        )
    )  # fmt: skip


def _punching(
    f: CombinedFooting,
    out: FootingResult,
    column: FootingColumn,
    pu: float,
    moment: np.ndarray,
    pressure: Pressure,
    label: str,
) -> None:
    if pu <= 0.0:
        return
    hx, hy = f.length_x / 2.0, f.width_y / 2.0
    ox, oy = column.x, column.y
    d = (f.d_x + f.d_y) / 2.0
    b1, b2 = column.cx + d, column.cy + d
    x0, x1 = max(ox - b1 / 2.0, -hx), min(ox + b1 / 2.0, hx)
    y0, y1 = max(oy - b2 / 2.0, -hy), min(oy + b2 / 2.0, hy)
    sides = [ox - b1 / 2.0 > -hx, ox + b1 / 2.0 < hx, oy - b2 / 2.0 > -hy, oy + b2 / 2.0 < hy]
    b0 = (sides[0] + sides[1]) * (y1 - y0) + (sides[2] + sides[3]) * (x1 - x0)
    if sum(sides) < 2 or b0 <= 0.0:
        out._note(f"{column.label}: the punching perimeter does not fit; one-way shear governs.")
        return
    alpha_s = {4: 40.0, 3: 30.0, 2: 20.0}[sum(sides)]
    beta = max(column.cx, column.cy) / min(column.cx, column.cy)
    vc = min(0.33, 0.17 * (1.0 + 2.0 / beta), 0.083 * (2.0 + alpha_s * d / b0))
    vc *= size_effect(d) * f.lam * _sqrt_fc(f.fc)
    vu = (pu - pressure.force(x0, x1, y0, y1)) / (b0 * d)
    if sum(sides) == 4:
        for m, span, across in ((moment[1], b1, b2), (moment[0], b2, b1)):
            gamma_v = 1.0 - 1.0 / (1.0 + 2.0 / 3.0 * math.sqrt(span / across))
            jc = d * span**3 / 6.0 + span * d**3 / 6.0 + d * across * span**2 / 2.0
            vu += gamma_v * abs(m) * (span / 2.0) / jc
    out._keep(
        FootingCheck(
            "Two-way shear (punching)", vu / (PHI_SHEAR * vc), "ACI 318-19 22.6.5.2, 8.4.4.2",
            f"{column.label}: vu = {vu:.3g} MPa, φvc = {PHI_SHEAR * vc:.3g} MPa "
            f"(b0 = {b0:.0f} mm, αs = {alpha_s:g})",
            label,
        )
    )  # fmt: skip


def _bearing(
    f: CombinedFooting, out: FootingResult, column: FootingColumn, pu: float, label: str
) -> None:
    if pu <= 0.0:
        return
    hx, hy = f.length_x / 2.0, f.width_y / 2.0
    a1 = column.cx * column.cy
    r_plan = min(2.0 * (hx - abs(column.x)) / column.cx, 2.0 * (hy - abs(column.y)) / column.cy)
    r_depth = min(
        (column.cx + 4.0 * f.thickness) / column.cx, (column.cy + 4.0 * f.thickness) / column.cy
    )
    root = min(max(min(r_plan, r_depth), 1.0), 2.0)
    bearing = PHI_BEARING * 0.85 * f.fc * a1 * root
    out._keep(
        FootingCheck(
            "Bearing on the footing", pu / bearing, "ACI 318-19 22.8",
            f"{column.label}: Pu = {pu / 1e3:.4g} kN, φBn = {bearing / 1e3:.4g} kN", label,
        )
    )  # fmt: skip


# ───────────────────────────── sizing ─────────────────────────────
_SOIL = ("Soil bearing", "Soil contact", "Overturning about X", "Overturning about Y")
_DEPTH = ("Two-way shear (punching)", "Minimum depth")


def size_combined_footing(
    footing: CombinedFooting,
    service: Sequence[CombinedLoad],
    strength: Sequence[CombinedLoad],
    *,
    limit: float = 1.0,
    step: float = 50.0,
    max_width: float = 8000.0,
) -> CombinedFooting | None:
    """Width (keeping the length), then thickness, then bars that pass everything.

    The width across the long axis grows in ``step``; the thickness from 300 mm;
    then the bars (bottom both ways, and top bars along the long axis when a
    hogging moment needs them), 12 to 32 mm at the largest 25 mm spacing.
    """
    from opensees_studio.core.design.footing import BAR_DIAMETERS

    def ratios(trial: CombinedFooting, s: Sequence[CombinedLoad], u: Sequence[CombinedLoad]):  # type: ignore[no-untyped-def]
        return check_combined_footing(trial, s, u)

    def across(trial: CombinedFooting, width: float) -> CombinedFooting:
        if footing.axis == "x":
            return replace(trial, width_y=width)
        return replace(trial, length_x=width)

    width = footing.width_y if footing.axis == "x" else footing.length_x
    thickness = 300.0
    trial = footing
    while width <= max_width and thickness <= 3000.0:
        trial = replace(across(footing, width), thickness=thickness)
        soil = ratios(trial, service, [])
        if any(soil.ratio(n) > limit for n in _SOIL):
            width += step
            continue
        if any(ratios(trial, [], strength).ratio(n) > limit for n in _DEPTH) or any(
            c.ratio > limit
            for c in ratios(trial, [], strength).checks
            if c.name.startswith("One-way shear")
        ):
            thickness += step
            continue
        found = None
        for db in BAR_DIAMETERS:
            top = int(min(3.0 * thickness, 450.0) // 25) * 25
            for spacing in range(top, 74, -25):
                bars = replace(
                    trial,
                    bar_x_diameter=db, bar_x_spacing=float(spacing),
                    bar_y_diameter=db, bar_y_spacing=float(spacing),
                    top_bar_diameter=db, top_bar_spacing=float(spacing),
                )  # fmt: skip
                result = ratios(bars, service, strength)
                if result.governing is not None and result.governing.ratio <= limit:
                    found = bars
                    break
            if found is not None:
                break
        if found is not None:
            needs_top = any(c.name.startswith("Flexure, top") for c in result.checks)
            return found if needs_top else replace(found, top_bar_diameter=0.0)
        failing = {c.name for c in result.checks if c.ratio > limit}
        if any(n.startswith(("Development", "Bearing", "Sliding")) for n in failing):
            width += step
        else:
            thickness += step
    return None


# ───────────────────────────── project data ─────────────────────────────
class CombinedColumn(BaseModel):
    """One support on a combined footing, as a project saves it (project units).

    ``column_x`` by ``column_y``, ``steel_x`` / ``steel_y`` and the pedestal height
    mean what they mean in :class:`~.footing.FootingDesign`. The column's position
    comes from its node.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    node_id: PositiveInt
    column_x: PositiveFloat
    column_y: PositiveFloat
    steel_x: PositiveFloat | None = None
    steel_y: PositiveFloat | None = None
    pedestal_height: float = Field(default=0.0, ge=0.0)


class CombinedFootingDesign(BaseModel):
    """A rectangular footing under two or more supports (project units).

    ``center_x`` and ``center_y`` place the footing's centre in global X and Y;
    its underside is ``thickness`` below the top, and the top sits under the
    lowest pedestal (or at the supports with no pedestal).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = Field(min_length=1)
    columns: list[CombinedColumn] = Field(min_length=2)
    center_x: float
    center_y: float
    length_x: PositiveFloat
    width_y: PositiveFloat
    thickness: PositiveFloat
    soil_cover: float = Field(default=0.0, ge=0.0)
    fc: PositiveFloat
    fy: PositiveFloat
    lam: float = Field(default=1.0, gt=0.0, le=1.0)
    cover: PositiveFloat
    bar_x_diameter: PositiveFloat
    bar_x_spacing: PositiveFloat
    bar_y_diameter: PositiveFloat
    bar_y_spacing: PositiveFloat
    top_bar_diameter: float = Field(default=0.0, ge=0.0)
    top_bar_spacing: PositiveFloat
    concrete_weight: PositiveFloat
    soil_weight: PositiveFloat
    bearing_allowable: PositiveFloat
    friction: PositiveFloat = 0.45
    fs_overturning: PositiveFloat = 1.5
    fs_sliding: PositiveFloat = 1.5

    @property
    def node_ids(self) -> list[int]:
        return [c.node_id for c in self.columns]
