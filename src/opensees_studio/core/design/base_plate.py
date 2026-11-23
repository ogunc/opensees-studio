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

**Uplift, with or without a moment** (``Pu ≤ 0``, uplift ``U = -Pu``). A rigid
plate on rods in two rows at ``±f`` (``nt`` rods at ``+f``, ``min(nt, n - nt)``
at ``-f``, the rest on the centre line), the concrete in compression only:

* **Rods only** while every rod stays in tension: the plate translates and
  rotates, each rod taking ``k (δ + θ x)``; with symmetric rows the row forces
  are ``T = U nt / n ± |Mu| / (2 f)``. The rows' breakout cones are also
  checked as one group under ``U``.
* **Rods and bearing** once the far row would go into compression
  (``|Mu| > 2 f U nt / n`` with symmetric rows): the far and centre rods are
  dropped (conservative), the concrete bears over ``Y`` at ``q,max`` on the
  compression side, and equilibrium of forces and moments about the plate
  centre gives ``Y = (f + N/2) - √((f + N/2)² - 2 (|Mu| - U f) / q,max)`` and
  ``T = q,max Y + U``: DG1 3.3.2 with a negative ``Pu``, continuous with it at
  ``Pu = 0``.
* The plate bends over the tension rods, ``tp ≥ 2.11 √(T x / (B Fy))`` with
  ``x = f - 0.95 d / 2`` (the tension-side expression of DG1 3.3.2), and over
  the bearing block as in 3.3.

The sign of ``Mu`` names the row: ``Mu > 0`` pulls the row at ``+f``, ``Mu < 0``
the one at ``-f`` (:attr:`BasePlateResult.row_tension`). One axis only: a
moment about the plate's other axis is not combined (the per-support check
reports it). When the rods carry both tension and shear (friction short of the shear),
the interaction ``Nua/φNn + Vua/φVn ≤ 1.2`` of ACI 318-19 17.8.3 is checked.
Not covered for any demand: pullout, side-face blowout, ψec of an
eccentric group, anchor reinforcement, grout and the weld. A demand the method
cannot take (rods carrying tension with no diameter or futa) sets
:attr:`BasePlateResult.requires_verification` and never reads as a pass.

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
    """Tension of the most loaded rod row."""
    row_tension: tuple[float, float] = (0.0, 0.0)
    """Uplift: the tension of the rod rows at ``+f`` and ``-f``."""
    bearing_force: float = 0.0
    """Uplift with a large moment: the concrete's compression ``q,max Y``."""
    requires_verification: str = ""
    """Why this demand is outside the implemented method (empty when it is not).
    The checks then hold only what could be computed, so their ratio is no pass."""

    @property
    def governing(self) -> PlateCheck | None:
        return max(self.checks, key=lambda c: c.ratio, default=None)


REQUIRES_VERIFICATION = "Requires verification"
"""Status label of a demand outside the implemented method."""

RODS_UNDEFINED = (
    "The anchor rods carry tension but have no diameter or futa, so nothing checks "
    "them. Requires verification."
)


def moment_is_significant(plate: BasePlate, mu: float) -> bool:
    """``mu`` is more than rounding next to the plate's bearing moment ``q,max N²``."""
    scale = bearing_limit(plate) * plate.b_width * plate.n_length**2
    return abs(mu) > 1e-9 * scale


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
        tension = _uplift(plate, out, -pu, mu, q_max, max(m, n))
        if tension is None:
            return out
        _anchor_checks(plate, out, tension, vu, 0.0)
        return out
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
    _anchor_checks(plate, out, tension, vu, max(pu, 0.0))
    return out


def _rows(plate: BasePlate) -> tuple[int, int, int]:
    """Rods at ``+f``, at ``-f`` and on the centre line."""
    total = max(plate.rods_total, 1)
    near = min(max(plate.rods_tension, 1), total)
    far = min(near, total - near)
    return near, far, total - near - far


def _uplift(
    plate: BasePlate, out: BasePlateResult, uplift: float, mu: float, q_max: float, length: float
) -> float | None:
    """Rod row tensions under ``uplift`` (≥ 0) and ``mu``; the near row's, None to stop."""
    near, far, centre = _rows(plate)
    total = near + far + centre
    sign = 1.0 if mu >= 0.0 else -1.0
    moment = abs(mu) if moment_is_significant(plate, mu) else 0.0
    f = plate.rod_offset
    if moment == 0.0:
        out.notes.append("The column is in tension: the anchor rods share the uplift.")
        t_near, t_far = uplift * near / total, uplift * far / total
    elif f <= 0.0:
        out.checks.append(PlateCheck("Anchor rods for uplift with moment", math.inf, "DG1 3.3.2"))
        out.notes.append("Uplift with a moment needs anchor rods: give their offset f.")
        return None
    else:
        # Rigid plate on equal rods: F_i = k (δ + θ x_i), x = +f, -f, 0.
        a = [[total, f * (near - far)], [f * (near - far), f * f * (near + far)]]
        det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
        delta = (uplift * a[1][1] - moment * a[0][1]) / det if det else 0.0
        theta = (a[0][0] * moment - a[1][0] * uplift) / det if det else math.inf
        rod_far = delta - theta * f
        rod_centre = delta
        if det and rod_far >= 0.0 and (centre == 0 or rod_centre >= 0.0):
            out.notes.append(
                "Uplift with a small moment: every rod in tension, no bearing on the concrete."
            )
            t_near, t_far = near * (delta + theta * f), far * rod_far
            if far:
                _group_breakout(plate, out, uplift)
        else:
            term = (f + plate.n_length / 2.0) ** 2 - 2.0 * (moment - uplift * f) / q_max
            if term < 0.0:
                out.checks.append(
                    PlateCheck("Bearing length for uplift with moment", math.inf, "DG1 3.3.2")
                )
                out.notes.append("No real bearing length: the plate is too small for the moment.")
                return None
            y = (f + plate.n_length / 2.0) - math.sqrt(term)
            out.bearing_length = y
            out.bearing_force = q_max * y
            out.eccentricity = math.inf if uplift == 0.0 else moment / uplift
            t_near, t_far = q_max * y + uplift, 0.0
            out.notes.append(
                "Uplift with a large moment: the far rods go slack and the concrete bears "
                "at q,max on the compression side."
            )
            out.checks.append(
                PlateCheck("Concrete bearing", 1.0, "DG1 3.3.2 with Pu < 0 (at q,max)")
            )
            required = _thickness_bearing(bearing_limit(plate), length, y, plate.fy)
            out.checks.append(
                PlateCheck(
                    "Plate thickness (bearing side)",
                    required / plate.tp,
                    "DG1 3.3",
                    f"tp,req = {required:.4g}",
                )
            )
    out.row_tension = (t_near, t_far) if sign > 0 else (t_far, t_near)
    out.anchor_tension = t_near
    x = f - CANTILEVER_FACTORS[plate.kind][0] * plate.d / 2.0
    if x > 0.0 and t_near > 0.0:
        required = 2.11 * math.sqrt(t_near * x / (plate.b_width * plate.fy))
        out.checks.append(
            PlateCheck(
                "Plate thickness (tension side)",
                required / plate.tp,
                "DG1 3.3.2 (tension side)",
                f"tp,req = {required:.4g}",
            )
        )
    return t_near


def _nb(plate: BasePlate) -> float:
    hef_mm = plate.embedment / plate.mm
    return float(10.0 * plate.lam * math.sqrt(plate.fc / plate.mpa) * hef_mm**1.5 * plate.newton)


def _group_breakout(plate: BasePlate, out: BasePlateResult, uplift: float) -> None:
    """ACI 318-19 17.6.2 of both rows as one group under the whole uplift."""
    if plate.embedment <= 0.0 or plate.rod_diameter <= 0.0:
        return
    hef = plate.embedment
    ca = plate.edge_distance if plate.edge_distance > 0.0 else 1.5 * hef
    side = min(ca, 1.5 * hef)
    near, far, centre = _rows(plate)
    width = 2.0 * side + (near - 1) * plate.rod_spacing
    depth = 2.0 * side + 2.0 * plate.rod_offset
    anco = 9.0 * hef**2
    anc = min(width * depth, (near + far + centre) * anco)
    psi_ed = 1.0 if ca >= 1.5 * hef else 0.7 + 0.3 * ca / (1.5 * hef)
    breakout = 0.70 * anc / anco * psi_ed * _nb(plate)
    out.checks.append(
        PlateCheck(
            "Concrete breakout of the rod group (both rows)",
            uplift / breakout,
            "ACI 318-19 17.6.2",
        )
    )


def _anchor_checks(
    plate: BasePlate, out: BasePlateResult, tension: float, vu: float, pu: float
) -> None:
    if plate.rod_diameter <= 0.0 or plate.rod_futa <= 0.0:
        if tension > 0.0:
            out.requires_verification = RODS_UNDEFINED
            out.notes.append(RODS_UNDEFINED)
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
            nb = _nb(plate)
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
        rods_take_shear = rods_shear > 0.0 and friction < abs(vu)
        tension_ratio = max(
            (
                c.ratio
                for c in out.checks
                if c.name.startswith(("Anchor rod steel", "Concrete breakout"))
            ),
            default=0.0,
        )
        shear_ratio = abs(vu) / rods_shear if rods_shear > 0.0 else math.inf
        if rods_take_shear and tension > 0.0 and tension_ratio > 0.2 and shear_ratio > 0.2:
            out.checks.append(
                PlateCheck(
                    "Rod tension-shear interaction",
                    (tension_ratio + shear_ratio) / 1.2,
                    "ACI 318-19 17.8.3",
                )
            )
