"""Seismic action of the Nicaraguan building code RNC-07 (MTI, 2007), Título II.

Everything here is transcribed from the official text (articles cited per value):

- **Zone acceleration** a0 (Art. 24, Fig. 2): zone A 0.1, B 0.2, C 0.3 g, for
  structures of Group B and C. The isoacceleration map of Anexo C gives a value
  per site; the engineer may type that a0 instead of the zone value.
- **Soil amplification** S (Art. 25, Tabla 2) per zone and soil type I-III;
  type IV (Vs < 180 m/s) needs a site-specific spectrum and is refused.
- **Elastic design spectrum** a(T) (Art. 27, Ec. 6), in g, with d = 2.7 a0,
  Ta = 0.1 s, Tb = 0.6 s, Tc = 2 s::

      T < Ta          a = S [a0 + (d - a0) T / Ta]
      Ta <= T <= Tb   a = S d
      Tb < T <= Tc    a = S d (Tb / T)
      T > Tc          a = S d (Tb / Tc) (Tc / T)^2

  Group A multiplies the design accelerations by 1.5; Group C takes Group B's.
- **Ductility reduction** Q' (Art. 21, Ec. 2): Q' = Q when T >= Ta or T is
  unknown, else 1 + (T / Ta)(Q - 1); multiplied by 0.9 (one regularity
  condition of Art. 23 a) not met), 0.8 (two or more) or 0.7 (strongly
  irregular, Art. 23 c), never below 1 (Art. 23 d).
- **Overstrength** Ω = 2 (Art. 22).
- **Static coefficient** (Art. 24, Ec. 3): c = S (2.7 a0) / (Q' Ω), never below
  S a0, with Q' = Q (the period ignored); Group A forces times 1.5 (Art. 32 a).
  With the period (Art. 32 b, Ec. 13) the coefficient is a(T) / (Ω Q'(T)) with
  a(T) not below S a0.
- **Modal base shear check** (Art. 33 a, Ec. 26): V0 >= 0.8 a W0 / (Ω Q').
- **Drift factors** (Art. 34): service displacements are the reduced ones times
  Q'Ω/2.5 (limit 0.002, or 0.004 without fragile partitions), collapse ones
  times QΩ (limits per system, Tabla 4).

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

Rnc07Zone = Literal["A", "B", "C"]
Rnc07Soil = Literal["I", "II", "III"]
Rnc07Group = Literal["A", "B", "C"]
Rnc07Regularity = Literal["regular", "irregular_one", "irregular_two", "strongly_irregular"]

#: Art. 24 / Fig. 2: a0 (g) per seismic zone, Group B and C.
RNC07_ZONE_A0: dict[str, float] = {"A": 0.1, "B": 0.2, "C": 0.3}

#: Art. 25, Tabla 2: S per zone, for soil types I, II and III.
RNC07_SOIL_FACTOR: dict[str, tuple[float, float, float]] = {
    "A": (1.0, 1.8, 2.4),
    "B": (1.0, 1.7, 2.2),
    "C": (1.0, 1.5, 2.0),
}
RNC07_SOILS: tuple[str, ...] = ("I", "II", "III")

#: Art. 27: spectrum corner periods (s) and plateau factor d = 2.7 a0.
RNC07_TA = 0.1
RNC07_TB = 0.6
RNC07_TC = 2.0
RNC07_PLATEAU = 2.7

#: Art. 22: overstrength reduction.
RNC07_OMEGA = 2.0

#: Art. 20 / 27: design accelerations of Group A are 1.5 times Group B's.
RNC07_GROUP_FACTOR: dict[str, float] = {"A": 1.5, "B": 1.0, "C": 1.0}

#: Art. 23 d: Q' correction for irregularity.
RNC07_REGULARITY_FACTOR: dict[str, float] = {
    "regular": 1.0,
    "irregular_one": 0.9,
    "irregular_two": 0.8,
    "strongly_irregular": 0.7,
}
RNC07_REGULARITY_LABELS: dict[str, str] = {
    "regular": "Regular (Art. 23 a)",
    "irregular_one": "One condition of Art. 23 a not met (Q' × 0.9)",
    "irregular_two": "Two or more conditions not met (Q' × 0.8)",
    "strongly_irregular": "Strongly irregular, Art. 23 c (Q' × 0.7)",
}

#: Art. 21: ductility factors Q the code defines.
RNC07_Q_VALUES: tuple[float, ...] = (1.0, 1.5, 2.0, 3.0, 4.0)

#: Art. 34 c: allowable service drift ratios.
RNC07_SERVICE_DRIFT = 0.002
RNC07_SERVICE_DRIFT_NO_FRAGILE = 0.004

#: Art. 34, Tabla 4: maximum collapse storey drift ratio per structural system.
RNC07_COLLAPSE_DRIFT: dict[str, float] = {
    "Ductile RC frames (Q = 3 or 4)": 0.030,
    "Ductile steel frames (Q = 3 or 4)": 0.030,
    "Steel or RC frames with limited ductility (Q = 1 or 2)": 0.015,
    "Flat slabs without walls or bracing": 0.015,
    "Steel eccentrically braced frames": 0.020,
    "Steel or RC concentrically braced frames": 0.015,
    "Walls with ductile RC frames (Q = 3)": 0.015,
    "Walls with limited-ductility RC frames (Q = 1 or 2)": 0.010,
    "Diaphragm walls": 0.006,
    "Confined solid masonry with horizontal reinforcement or mesh": 0.005,
    "Confined solid masonry; confined hollow masonry with horizontal "
    "reinforcement or mesh": 0.004,
    "Hollow masonry with interior reinforcement": 0.002,
    "Masonry neither confined nor internally reinforced": 0.0015,
}


class Rnc07Error(ValueError):
    """Parameters outside what RNC-07 defines."""


def zone_for_a0(a0: float) -> str:
    """The Fig. 2 zone whose a0 is closest to ``a0`` (for the soil factor table).

    A map value between two zone values takes the higher zone, the
    conservative reading of Tabla 2.
    """
    if a0 <= 0.0:
        raise Rnc07Error("a0 must be positive.")
    if a0 <= RNC07_ZONE_A0["A"] + 1e-12:
        return "A"
    if a0 <= RNC07_ZONE_A0["B"] + 1e-12:
        return "B"
    return "C"


def soil_factor(zone: str, soil: str) -> float:
    """S of Tabla 2 (Art. 25)."""
    if soil == "IV":
        raise Rnc07Error(
            "Soil type IV (Vs < 180 m/s) needs a site-specific spectrum (Art. 25); "
            "enter it as a user table."
        )
    if zone not in RNC07_SOIL_FACTOR:
        raise Rnc07Error(f"Unknown RNC-07 zone {zone!r}; use A, B or C.")
    if soil not in RNC07_SOILS:
        raise Rnc07Error(f"Unknown RNC-07 soil type {soil!r}; use I, II or III.")
    return RNC07_SOIL_FACTOR[zone][RNC07_SOILS.index(soil)]


def ductility_reduction(
    q: float, period: float | None = None, regularity: str = "regular"
) -> float:
    """Q' of Art. 21 (Ec. 2) with the Art. 23 d irregularity correction, >= 1."""
    if q < 1.0:
        raise Rnc07Error("Q must be at least 1.")
    if regularity not in RNC07_REGULARITY_FACTOR:
        raise Rnc07Error(f"Unknown regularity {regularity!r}.")
    if period is None or period >= RNC07_TA:
        base = q
    else:
        base = 1.0 + (max(period, 0.0) / RNC07_TA) * (q - 1.0)
    return max(1.0, base * RNC07_REGULARITY_FACTOR[regularity])


def elastic_spectrum(
    periods: np.ndarray | list[float] | float,
    a0: float,
    s: float,
    group: str = "B",
) -> np.ndarray:
    """a(T) of Art. 27 (Ec. 6), in g, Group A times 1.5."""
    if a0 <= 0.0 or s <= 0.0:
        raise Rnc07Error("a0 and S must be positive.")
    if group not in RNC07_GROUP_FACTOR:
        raise Rnc07Error(f"Unknown RNC-07 group {group!r}; use A, B or C.")
    t = np.atleast_1d(np.asarray(periods, dtype=float))
    if np.any(t < 0.0):
        raise ValueError("periods must be >= 0.")
    d = RNC07_PLATEAU * a0
    ta, tb, tc = RNC07_TA, RNC07_TB, RNC07_TC
    safe = np.maximum(t, 1e-6)
    a = np.where(
        t < ta,
        s * (a0 + (d - a0) * t / ta),
        np.where(
            t <= tb,
            s * d,
            np.where(t <= tc, s * d * tb / safe, s * d * (tb / tc) * (tc / safe) ** 2),
        ),
    )
    return a * RNC07_GROUP_FACTOR[group]


def reduced_spectrum(
    periods: np.ndarray | list[float] | float,
    a0: float,
    s: float,
    q: float,
    *,
    group: str = "B",
    regularity: str = "regular",
) -> np.ndarray:
    """Modal design accelerations Am = a / (Ω Q'(T)) of Art. 33 (Ec. 19), in g."""
    t = np.atleast_1d(np.asarray(periods, dtype=float))
    a = elastic_spectrum(t, a0, s, group)
    qp = np.array([ductility_reduction(q, float(value), regularity) for value in t])
    return a / (RNC07_OMEGA * qp)


@dataclass(frozen=True)
class Rnc07Coefficient:
    """The static seismic coefficient and how it was reached."""

    c: float
    q_prime: float
    why: str


def static_coefficient(
    a0: float,
    s: float,
    q: float,
    *,
    group: str = "B",
    regularity: str = "regular",
    period: float | None = None,
) -> Rnc07Coefficient:
    """Seismic coefficient of the equivalent static method, Group factor included.

    ``period=None`` is Art. 32 a (Ec. 3): c = S (2.7 a0) / (Q' Ω) >= S a0 with
    Q' = Q. A period is Art. 32 b (Ec. 13): a(T) / (Ω Q'(T)) with a >= S a0.
    """
    if a0 <= 0.0 or s <= 0.0:
        raise Rnc07Error("a0 and S must be positive.")
    factor = RNC07_GROUP_FACTOR[group]
    floor = s * a0
    if period is None:
        qp = ductility_reduction(q, None, regularity)
        c = s * RNC07_PLATEAU * a0 / (qp * RNC07_OMEGA)
        why = f"Ec. 3: S·2.7a0/(Q'Ω) with Q' = {qp:.4g}"
        if c < floor:
            c, why = floor, "Ec. 3 minimum S·a0"
    else:
        qp = ductility_reduction(q, period, regularity)
        a = float(elastic_spectrum(period, a0, s, "B")[0])
        why = f"Ec. 13: a(T)/(ΩQ') with a = {a:.4g}, Q'(T) = {qp:.4g}"
        if a < floor:
            a, why = floor, f"Ec. 13 with a raised to S·a0 = {floor:.4g}, Q'(T) = {qp:.4g}"
        c = a / (RNC07_OMEGA * qp)
    if factor != 1.0:
        why += f"; Group {group} × {factor:g}"
    return Rnc07Coefficient(c=c * factor, q_prime=qp, why=why)


def modal_base_shear_minimum(
    a0: float,
    s: float,
    q: float,
    period: float,
    weight: float,
    *,
    group: str = "B",
    regularity: str = "regular",
) -> float:
    """0.8 a W0 / (Ω Q') of Art. 33 a (Ec. 26), with a and Q' at the fundamental period."""
    a = float(elastic_spectrum(period, a0, s, group)[0])
    qp = ductility_reduction(q, period, regularity)
    return 0.8 * a * weight / (RNC07_OMEGA * qp)


def service_drift_factor(q: float, period: float | None, regularity: str = "regular") -> float:
    """Q'Ω/2.5 (Art. 34 a b), or QΩ/2.5 when the period was ignored (Art. 34 a a)."""
    if period is None:
        return q * RNC07_OMEGA / 2.5
    return ductility_reduction(q, period, regularity) * RNC07_OMEGA / 2.5


def collapse_drift_factor(q: float) -> float:
    """QΩ (Art. 34 b)."""
    return q * RNC07_OMEGA
