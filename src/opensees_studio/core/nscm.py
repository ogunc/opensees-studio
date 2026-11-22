"""Seismic action of the Managua seismic code NSCM (MTI, ED-MTI 140622, 2021).

*Norma Sismorresistente para la Ciudad de Managua*. Transcribed from the
official text, section and equation cited per value:

- **Importance** I (Tabla 5.2.1): risk category I 0.75, II 1.0, III 1.3, IV 1.65.
- **Hazard** a0: PGA on rock for a 475-year return period (Tabla 14.2 per
  municipality, Managua 0.36667 g); the zone follows from it (Tabla 6.2.1):
  Z1 a0 < 0.17, Z2 0.17-0.23, Z3 0.23-0.315, Z4 >= 0.315.
- **Site amplification** Fas (Tabla 6.4.1) per zone and site class A-E, and the
  period adjustment FSTb, FSTc (Tabla 6.5.1) per site class A-D. Class E needs a
  site response study (Sec. 6.4 note, 13.5) and is refused here.
- **Elastic spectrum** A(T) (Ec. 6.7-1), in g, with A0 = a0 Fas I, β = 2.4,
  Tb = 0.05 s, Tc = 0.3 s, Td = 2 s, p = 0.8, q = 2::

      0 <= T <= FSTb Tb        A = A0 [1 + T / (FSTb Tb) (β - 1)]
      FSTb Tb <= T <= FSTc Tc  A = β A0
      FSTc Tc <= T <= Td       A = β A0 (FSTc Tc / T)^p
      Td <= T                  A = β A0 (FSTc Tc / T)^p (Td / T)^q

- **Reduced spectrum** (Sec. 6.9): A(T) / Ro, except the rising branch,
  A0 T / (FSTb Tb) (β / Ro - 1) + A0 (Ec. 6.9-1); Ro = R ΦP ΦE >= 1 (Ec. 6.6-1).
- **Seismic coefficient** Cs (Ec. 8.2-2): β A0 / Ro up to FSTc Tc, then times
  (FSTc Tc / T)^p, and times (Td / T)^q past Td; never below
  Cs,min = FSTc β A0 / (2 Ro) (Ec. 8.2-3). T is capped at Cu Ta (Sec. 8.2.1.5,
  Tabla 8.2.1).
- **Vertical component** Ev = 0.2 a0 Fas CM (Ec. 7.8-4).
- **Modal scaling** (Ec. 8.2-14): when the modal base shear Vt < Vb, forces and
  drifts are multiplied by Vb / Vt.
- **Drift** (Ec. 10.2-2): δ = Cd δe / I.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

NscmSiteClass = Literal["A", "B", "C", "D", "E"]
NscmRiskCategory = Literal["I", "II", "III", "IV"]

#: Tabla 5.2.1: importance factor per risk category.
NSCM_IMPORTANCE: dict[str, float] = {"I": 0.75, "II": 1.0, "III": 1.3, "IV": 1.65}

#: Tabla 6.2.1: upper a0 bound (g, exclusive) of zones Z1-Z3; Z4 is everything above.
NSCM_ZONE_LIMITS: tuple[tuple[str, float], ...] = (("Z1", 0.17), ("Z2", 0.23), ("Z3", 0.315))

#: Tabla 6.4.1: Fas per zone for site classes A-E (None: site response study).
NSCM_FAS: dict[str, tuple[float | None, ...]] = {
    "Z1": (0.8, 1.0, 1.4, 1.7, 2.2),
    "Z2": (0.8, 1.0, 1.4, 1.6, 2.0),
    "Z3": (0.8, 1.0, 1.4, 1.5, None),
    "Z4": (0.8, 1.0, 1.3, 1.4, None),
}
NSCM_SITE_CLASSES: tuple[str, ...] = ("A", "B", "C", "D", "E")

#: Tabla 6.5.1: (FSTb, FSTc) per site class.
NSCM_FS: dict[str, tuple[float, float]] = {
    "A": (1.0, 5.0 / 6.0),
    "B": (1.0, 1.0),
    "C": (1.0, 4.0 / 3.0),
    "D": (2.0, 5.0 / 3.0),
}

#: Sec. 6.7: spectrum shape constants.
NSCM_BETA = 2.4
NSCM_TB = 0.05
NSCM_TC = 0.3
NSCM_TD = 2.0
NSCM_P = 0.8
NSCM_Q = 2.0

#: Sec. 6.8: vertical spectrum as a fraction of the horizontal one.
NSCM_VERTICAL_RATIO = 0.7

#: Tabla 8.2.1: (Fas a0, Cu), interpolated between rows.
NSCM_CU: tuple[tuple[float, float], ...] = ((0.1, 1.7), (0.15, 1.6), (0.2, 1.5), (0.3, 1.4))

#: Tabla 8.2.2: (label, Ct for hn in metres, x); Ta = Ct hn^x (Ec. 8.2-4).
NSCM_PERIOD_SYSTEMS: dict[str, tuple[str, float, float]] = {
    "steel_mrf": ("Steel moment-resisting frame", 0.0724, 0.8),
    "concrete_mrf": ("Concrete moment-resisting frame", 0.0466, 0.9),
    "braced_ebf": ("Eccentrically braced / BRB steel frame", 0.0731, 0.75),
    "other": ("All other structural systems", 0.0488, 0.75),
}


class NscmError(ValueError):
    """Parameters outside what the NSCM defines."""


def zone_for_a0(a0: float) -> str:
    """Tabla 6.2.1 zone of a site with rock PGA ``a0`` (g)."""
    if a0 <= 0.0:
        raise NscmError("a0 must be positive.")
    for zone, upper in NSCM_ZONE_LIMITS:
        if a0 < upper:
            return zone
    return "Z4"


def site_amplification(a0: float, site_class: str) -> float:
    """Fas of Tabla 6.4.1."""
    if site_class not in NSCM_SITE_CLASSES:
        raise NscmError(f"Unknown NSCM site class {site_class!r}; use A to E.")
    zone = zone_for_a0(a0)
    fas = NSCM_FAS[zone][NSCM_SITE_CLASSES.index(site_class)]
    if fas is None or site_class == "E":
        raise NscmError(
            f"Site class E in zone {zone} needs a site response study (NSCM 6.4, 13.5); "
            "enter its spectrum as a user table."
        )
    return fas


def spectral_adjustment(site_class: str) -> tuple[float, float]:
    """(FSTb, FSTc) of Tabla 6.5.1."""
    if site_class not in NSCM_FS:
        raise NscmError(f"Tabla 6.5.1 defines FSTb and FSTc for site classes A-D, not {site_class!r}.")
    return NSCM_FS[site_class]


def importance_factor(risk_category: str) -> float:
    """I of Tabla 5.2.1."""
    if risk_category not in NSCM_IMPORTANCE:
        raise NscmError(f"Unknown risk category {risk_category!r}; use I to IV.")
    return NSCM_IMPORTANCE[risk_category]


def upper_limit_coefficient(a0: float, fas: float) -> float:
    """Cu of Tabla 8.2.1 at Fas a0, linear between the rows, clamped at the ends."""
    x = fas * a0
    xs = [row[0] for row in NSCM_CU]
    ys = [row[1] for row in NSCM_CU]
    return float(np.interp(x, xs, ys))


@dataclass(frozen=True)
class NscmSite:
    """What the NSCM spectrum needs: hazard, site, importance and Ro."""

    a0: float
    site_class: str
    risk_category: str = "II"
    r0: float = 1.0
    """Ro = R ΦP ΦE (Ec. 6.6-1); only the reduced spectrum and Cs use it."""

    def __post_init__(self) -> None:
        if self.r0 < 1.0:
            raise NscmError("Ro must be at least 1 (Ec. 6.6-1).")
        site_amplification(self.a0, self.site_class)
        spectral_adjustment(self.site_class)
        importance_factor(self.risk_category)

    @property
    def zone(self) -> str:
        return zone_for_a0(self.a0)

    @property
    def fas(self) -> float:
        return site_amplification(self.a0, self.site_class)

    @property
    def importance(self) -> float:
        return importance_factor(self.risk_category)

    @property
    def a0_design(self) -> float:
        """A0 = a0 Fas I (Sec. 6.7)."""
        return self.a0 * self.fas * self.importance

    def corner_periods(self) -> tuple[float, float, float]:
        """(FSTb Tb, FSTc Tc, Td), seconds."""
        fstb, fstc = spectral_adjustment(self.site_class)
        return fstb * NSCM_TB, fstc * NSCM_TC, NSCM_TD

    def elastic(self, periods: np.ndarray | list[float] | float) -> np.ndarray:
        """A(T) of Ec. 6.7-1, in g."""
        t = np.atleast_1d(np.asarray(periods, dtype=float))
        if np.any(t < 0.0):
            raise ValueError("periods must be >= 0.")
        a0 = self.a0_design
        tb, tc, td = self.corner_periods()
        safe = np.maximum(t, 1e-6)
        plateau = NSCM_BETA * a0
        return np.where(
            t <= tb,
            a0 * (1.0 + t / tb * (NSCM_BETA - 1.0)),
            np.where(
                t <= tc,
                plateau,
                np.where(
                    t <= td,
                    plateau * (tc / safe) ** NSCM_P,
                    plateau * (tc / safe) ** NSCM_P * (td / safe) ** NSCM_Q,
                ),
            ),
        )

    def vertical(self, periods: np.ndarray | list[float] | float) -> np.ndarray:
        """Vertical elastic spectrum, 70 % of A(T) (Sec. 6.8)."""
        return NSCM_VERTICAL_RATIO * self.elastic(periods)

    def reduced(self, periods: np.ndarray | list[float] | float) -> np.ndarray:
        """Design spectrum A(T) / Ro, with the rising branch of Ec. 6.9-1."""
        t = np.atleast_1d(np.asarray(periods, dtype=float))
        a0 = self.a0_design
        tb, _tc, _td = self.corner_periods()
        rising = a0 * t / tb * (NSCM_BETA / self.r0 - 1.0) + a0
        return np.where(t <= tb, rising, self.elastic(t) / self.r0)

    def seismic_coefficient(self, period: float) -> tuple[float, str]:
        """Cs of Ec. 8.2-2 with its minimum (Ec. 8.2-3), and which governs."""
        if period <= 0.0:
            raise NscmError("The period T must be positive.")
        _tb, tc, td = self.corner_periods()
        base = NSCM_BETA * self.a0_design / self.r0
        if period <= tc:
            cs, why = base, "Ec. 8.2-2 plateau βA0/Ro"
        elif period <= td:
            cs, why = base * (tc / period) ** NSCM_P, "Ec. 8.2-2 (FSTc·Tc/T)^p branch"
        else:
            cs = base * (tc / period) ** NSCM_P * (td / period) ** NSCM_Q
            why = "Ec. 8.2-2 (Td/T)^q branch"
        minimum = self.minimum_coefficient()
        if cs < minimum:
            cs, why = minimum, "Ec. 8.2-3 minimum FSTc·β·A0/(2Ro)"
        return cs, why

    def minimum_coefficient(self) -> float:
        """Cs,min = FSTc β A0 / (2 Ro) (Ec. 8.2-3)."""
        _fstb, fstc = spectral_adjustment(self.site_class)
        return fstc * NSCM_BETA * self.a0_design / (2.0 * self.r0)

    @property
    def cu(self) -> float:
        """Cu of Tabla 8.2.1."""
        return upper_limit_coefficient(self.a0, self.fas)

    def vertical_load_factor(self) -> float:
        """Ev / CM = 0.2 a0 Fas (Ec. 7.8-4)."""
        return 0.2 * self.a0 * self.fas

    def describe(self) -> str:
        tb, tc, td = self.corner_periods()
        return (
            f"NSCM Managua: a0={self.a0:g} g ({self.zone}), site {self.site_class} "
            f"(Fas={self.fas:g}), category {self.risk_category} (I={self.importance:g}), "
            f"A0={self.a0_design:.4g} g, corners {tb:.3g}/{tc:.3g}/{td:g} s"
        )


def approximate_period(system: str, height_m: float) -> float:
    """Ta = Ct hn^x (Ec. 8.2-4, Tabla 8.2.2), hn in metres."""
    if height_m <= 0.0:
        raise NscmError("The building has no height above its base.")
    _label, ct, x = NSCM_PERIOD_SYSTEMS[system]
    return float(ct * height_m**x)


def drift_amplification(cd: float, importance: float) -> float:
    """Cd / I of Ec. 10.2-2."""
    if cd <= 0.0 or importance <= 0.0:
        raise NscmError("Cd and I must be positive.")
    return cd / importance
