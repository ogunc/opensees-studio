"""Column base plates: AISC Design Guide 1 (3rd ed.) with ACI 318-19 Chapter 17 anchors.

LRFD, consistent units. The column (depth ``d``, flange width ``bf``) sits on a
plate ``N`` (along d) by ``B`` of thickness ``tp`` and yield ``fy``, on concrete
``f'c`` whose supporting area is ``A2``. Anchor rods sit at ``f`` from the
plate centre, ``n`` of them on the tension side.

* **Bearing** (J8, DG1 3.1): ``fp,max = φ 0.85 f'c √(A2/A1) ≤ φ 1.7 f'c``,
  ``φ = 0.65``; ``q,max = fp,max B``.
* **Moment** (DG1 3.3): ``e = Mu / Pu`` against ``e,crit = N/2 - Pu / (2 q,max)``.
  Small eccentricity: the bearing length ``Y = N - 2e`` carries ``q = Pu / Y``.
  Large: ``Y = (f + N/2) - √((f + N/2)² - 2 Pu (e + f) / q,max)`` at ``q,max``,
  and the rods carry ``T = q,max Y - Pu``.
* **Plate** (DG1 3.1.2, 3.3): cantilevers ``m = (N - 0.95 d) / 2``,
  ``n = (B - 0.8 bf) / 2`` for an I-shape (``0.95 b`` for a rectangular HSS,
  ``0.8 D`` both ways for a round one) and, concentric, ``λ n' = λ √(d bf) / 4``
  (kept for every kind, which is conservative); the required thickness is
  ``1.49 l √(fp / Fy)`` (``Y ≥ l``) or ``2.11 √(fp Y (l - Y/2) / Fy)``, and on
  the tension side ``2.11 √(T x / (B Fy))`` with ``x = f - 0.95 d / 2``.
* **Anchor rods** (ACI 318-19 17.6.1, 17.6.2, 17.7.1): steel ``φ 0.75 Ase futa``
  in tension and ``φ 0.65 · 0.6 Ase futa`` in shear (``Ase = 0.75 Ab``); concrete
  breakout of the tension group ``φ 0.70 (ANc / ANco) ψed Nb`` with
  ``Nb = 10 λ √f'c hef^1.5`` (N, MPa, mm; cast-in, cracked concrete),
  ``ANco = 9 hef²``.
* **Shear**: friction ``φ μ Pu`` (``φ = 0.75``, ``μ = 0.55``) or the rods,
  whichever is larger.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

PHI_BEARING = 0.65
PHI_PLATE = 0.90


ColumnKind = Literal["W", "HSS", "round"]
"""Column on the plate: an I-shape, a rectangular HSS, or a round HSS / pipe."""

CANTILEVER_FACTORS: dict[str, tuple[float, float]] = {
    "W": (0.95, 0.80),
    "HSS": (0.95, 0.95),
    "round": (0.80, 0.80),
}
"""DG1 3.1.2: ``m = (N - kd d) / 2``, ``n = (B - kb bf) / 2`` for each column kind
(a round column has ``d = bf = D``)."""

ROD_GRADES: dict[str, tuple[str, float]] = {
    "F1554-36": ("ASTM F1554 Gr. 36", 58.0),
    "F1554-55": ("ASTM F1554 Gr. 55", 75.0),
    "F1554-105": ("ASTM F1554 Gr. 105", 125.0),
}
"""Anchor rod grades: label and futa in ksi."""


@dataclass(frozen=True)
class BasePlate:
    d: float
    bf: float
    n_length: float
    """Plate length N, along the column depth."""
    b_width: float
    """Plate width B."""
    tp: float
    fy: float
    fc: float
    a2: float | None = None
    """Concrete area supporting the plate (concentric, similar); None = A1."""
    rods_tension: int = 2
    rod_diameter: float = 0.0
    rod_futa: float = 0.0
    rod_offset: float = 0.0
    """f: distance from the plate centre to the line of the tension rods."""
    rod_spacing: float = 0.0
    """Spacing of the tension rods along B."""
    edge_distance: float = 0.0
    """Smallest distance from a rod to the edge of the concrete."""
    embedment: float = 0.0
    """hef of the rods."""
    rods_total: int = 4
    lam: float = 1.0
    mpa: float = 1e6
    """One MPa in the stresses' unit."""
    mm: float = 1e-3
    """One millimetre in the lengths' unit."""
    newton: float = 1.0
    """One newton in the forces' unit."""
    kind: ColumnKind = "W"

    def cantilevers(self) -> tuple[float, float]:
        """``(m, n)`` of DG1 3.1.2 for the column kind."""
        kd, kb = CANTILEVER_FACTORS[self.kind]
        return (self.n_length - kd * self.d) / 2.0, (self.b_width - kb * self.bf) / 2.0


class BasePlateDesign(BaseModel):
    """The base plate and anchor rods of one column base, as a project saves them.

    Lengths and stresses are in the project's units; ``a2_ratio`` is A2 / A1 of
    J8 (1.0 when the plate covers the pier, at most 4).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    node_id: PositiveInt
    n_length: PositiveFloat
    b_width: PositiveFloat
    tp: PositiveFloat
    plate_grade: str = "A36"
    fc: PositiveFloat
    a2_ratio: float = Field(default=1.0, ge=1.0, le=4.0)
    rod_diameter: PositiveFloat
    rod_grade: str = "F1554-36"
    rods_total: PositiveInt = 4
    rods_tension: PositiveInt = 2
    rod_offset: PositiveFloat
    """f: from the plate centre to the line of the tension rods."""
    rod_spacing: PositiveFloat
    edge_distance: PositiveFloat
    embedment: PositiveFloat


@dataclass
class PlateCheck:
    name: str
    ratio: float
    reference: str
    value: str = ""


@dataclass
class BasePlateResult:
    checks: list[PlateCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    eccentricity: float = 0.0
    bearing_length: float = 0.0
    anchor_tension: float = 0.0

    @property
    def governing(self) -> PlateCheck | None:
        return max(self.checks, key=lambda c: c.ratio, default=None)


def bearing_limit(plate: BasePlate) -> float:
    """``fp,max``: the design bearing stress (J8, DG1 3.1.1)."""
    a1 = plate.n_length * plate.b_width
    ratio = math.sqrt(plate.a2 / a1) if plate.a2 and plate.a2 > a1 else 1.0
    return PHI_BEARING * min(0.85 * plate.fc * ratio, 1.7 * plate.fc)


def _thickness_bearing(fp: float, length: float, y: float, fy: float) -> float:
    if y >= length:
        return 1.49 * length * math.sqrt(fp / fy)
    return 2.11 * math.sqrt(fp * y * (length - y / 2.0) / fy)


def check_base_plate(
    plate: BasePlate, *, pu: float, mu: float = 0.0, vu: float = 0.0
) -> BasePlateResult:
    """Every DG1 / ACI 318 check of the plate under ``pu`` (compression positive), ``mu``, ``vu``."""
    out = BasePlateResult()
    fp_max = bearing_limit(plate)
    q_max = fp_max * plate.b_width
    m, n = plate.cantilevers()
    if pu <= 0.0:
        out.notes.append("The column is not in compression: only the anchor rods are checked.")
    tension = 0.0
    if pu > 0.0 and abs(mu) <= 1e-12 * max(pu, 1.0):
        fp = pu / (plate.n_length * plate.b_width)
        out.checks.append(PlateCheck("Concrete bearing", fp / fp_max, "AISC J8, DG1 3.1.1"))
        x = 4.0 * plate.d * plate.bf / (plate.d + plate.bf) ** 2 * min(fp / fp_max, 1.0)
        lam = min(1.0, 2.0 * math.sqrt(x) / (1.0 + math.sqrt(max(1.0 - x, 0.0)))) if x > 0 else 0.0
        length = max(m, n, lam * math.sqrt(plate.d * plate.bf) / 4.0)
        required = length * math.sqrt(
            2.0 * pu / (PHI_PLATE * plate.fy * plate.b_width * plate.n_length)
        )
        out.checks.append(
            PlateCheck(
                "Plate thickness (bearing)",
                required / plate.tp,
                "DG1 3.1.2",
                f"tp,req = {required:.4g}",
            )
        )
        out.bearing_length = plate.n_length
    elif pu > 0.0:
        e = abs(mu) / pu
        out.eccentricity = e
        e_crit = plate.n_length / 2.0 - pu / (2.0 * q_max)
        length = max(m, n)
        if e <= e_crit:
            y = plate.n_length - 2.0 * e
            q = pu / y
            out.bearing_length = y
            out.checks.append(PlateCheck("Concrete bearing", q / q_max, "DG1 3.3.1 (small e)"))
            required = _thickness_bearing(q / plate.b_width, length, y, plate.fy)
        else:
            f = plate.rod_offset
            if f <= 0.0:
                out.checks.append(
                    PlateCheck("Anchor rods for large eccentricity", math.inf, "DG1 3.3.2")
                )
                out.notes.append("Large eccentricity needs anchor rods: give their offset f.")
                return out
            term = (f + plate.n_length / 2.0) ** 2 - 2.0 * pu * (e + f) / q_max
            if term < 0.0:
                out.checks.append(
                    PlateCheck("Bearing length for large eccentricity", math.inf, "DG1 3.3.2")
                )
                out.notes.append("No real bearing length: the plate is too small for Pu and Mu.")
                return out
            y = (f + plate.n_length / 2.0) - math.sqrt(term)
            tension = q_max * y - pu
            out.bearing_length = y
            out.anchor_tension = tension
            out.checks.append(PlateCheck("Concrete bearing", 1.0, "DG1 3.3.2 (large e, at q,max)"))
            required = _thickness_bearing(fp_max, length, y, plate.fy)
            x = f - CANTILEVER_FACTORS[plate.kind][0] * plate.d / 2.0
            if x > 0.0 and tension > 0.0:
                t_tension = 2.11 * math.sqrt(tension * x / (plate.b_width * plate.fy))
                required = max(required, t_tension)
        out.checks.append(
            PlateCheck(
                "Plate thickness", required / plate.tp, "DG1 3.3", f"tp,req = {required:.4g}"
            )
        )
    if pu < 0.0:
        # Uplift: every rod takes its share (the tension-side count reads it below).
        tension = -pu * max(plate.rods_tension, 1) / max(plate.rods_total, 1)
        out.anchor_tension = tension
    _anchor_checks(plate, out, tension, vu, max(pu, 0.0))
    return out


def _anchor_checks(
    plate: BasePlate, out: BasePlateResult, tension: float, vu: float, pu: float
) -> None:
    if plate.rod_diameter <= 0.0 or plate.rod_futa <= 0.0:
        if tension > 0.0:
            out.notes.append("Anchor rods carry tension: give their diameter and futa.")
        return
    ase = 0.75 * math.pi * plate.rod_diameter**2 / 4.0
    if tension > 0.0:
        rods = max(plate.rods_tension, 1)
        per_rod = tension / rods
        steel = 0.75 * ase * plate.rod_futa
        out.checks.append(
            PlateCheck("Anchor rod steel in tension", per_rod / steel, "ACI 318-19 17.6.1")
        )
        if plate.embedment > 0.0:
            hef = plate.embedment
            hef_mm = hef / plate.mm
            nb = 10.0 * plate.lam * math.sqrt(plate.fc / plate.mpa) * hef_mm**1.5 * plate.newton
            anco = 9.0 * hef**2
            ca = plate.edge_distance if plate.edge_distance > 0.0 else 1.5 * hef
            side = min(ca, 1.5 * hef)
            width = 2.0 * side + (rods - 1) * plate.rod_spacing
            anc = min(width * 2.0 * side, rods * anco)
            psi_ed = 1.0 if ca >= 1.5 * hef else 0.7 + 0.3 * ca / (1.5 * hef)
            breakout = 0.70 * anc / anco * psi_ed * nb
            out.checks.append(
                PlateCheck(
                    "Concrete breakout of the rods in tension",
                    tension / breakout,
                    "ACI 318-19 17.6.2",
                )
            )
    if abs(vu) > 0.0:
        friction = 0.75 * 0.55 * pu
        rods_shear = max(plate.rods_total, 1) * 0.65 * 0.6 * ase * plate.rod_futa
        capacity = max(friction, rods_shear)
        out.checks.append(
            PlateCheck(
                "Shear (friction or the rods)",
                abs(vu) / capacity if capacity > 0.0 else math.inf,
                "DG1 3.5, ACI 318-19 17.7.1",
            )
        )
