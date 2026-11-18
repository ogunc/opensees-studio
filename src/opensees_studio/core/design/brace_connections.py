"""AISC 341-22 F2.6c: SCBF brace connections and gusset-to-flange welds.

The brace connection is designed for three independent required strengths:

* tension: ``Ry Fy Ag / alpha_s`` (the lesser of that and the maximum load
  effect the system can transfer; the first is the upper bound and is used
  here);
* compression: the expected brace compression of F2.3 divided by ``alpha_s``;
* flexure: ``1.1 Ry Mp / alpha_s`` about the critical buckling axis, to
  accommodate brace buckling.

The gusset plate welded directly to a beam or column flange needs an available
shear strength of ``0.6 Ry Fy tp / alpha_s`` times the joint length when the
brace buckles out of plane. Comparing per unit length is equivalent. The weld
is a fillet weld with throat ``0.707 leg`` and the AISC 360 J2.4 shear
strength (``phi = 0.75``, ``Omega = 2.00``).

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from opensees_studio.core.design.aisc341 import alpha_s
from opensees_studio.core.design.aisc360 import Method
from opensees_studio.core.design.calc import CalcStep, LimitStateCheck

#: AISC 360 J2.4: resistance factor and safety factor of a fillet weld in shear.
FILLET_PHI = 0.75
FILLET_OMEGA = 2.00
#: Effective throat of a 45-degree fillet weld, ``cos 45 = 0.707``.
FILLET_THROAT = math.sqrt(0.5)
#: F2.6c.4: the gusset shear demand per unit length.
GUSSET_WELD_FRACTION = 0.60
#: F2.6c.3: the brace buckling moment is 1.1 times the expected plastic moment.
BUCKLING_MOMENT_FACTOR = 1.1


@dataclass(frozen=True)
class ConnectionDemand:
    """The three independent required strengths of one brace connection."""

    tension: float
    compression: float
    flexure: float
    """``1.1 Ry Mp / alpha_s``; 0 when the shape has no plastic modulus."""
    steps: tuple[CalcStep, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def critical_plastic_modulus(shape: Any) -> float | None:
    """The plastic modulus about the critical buckling axis, when tabulated.

    The critical axis is the one with the smaller radius of gyration. The
    shape families expose ``Zx``/``Zy`` (and ``Z`` for a round HSS); an equal
    leg angle has no plastic modulus in the table, so the flexural demand is
    reported as not evaluated instead of being approximated.
    """
    candidates: list[tuple[float, float]] = []
    for z_name, r_name in (("Zx", "rx"), ("Zy", "ry"), ("Z", "r")):
        z = getattr(shape, z_name, None)
        r = getattr(shape, r_name, None)
        if z is not None and r is not None and float(z) > 0.0 and float(r) > 0.0:
            candidates.append((float(r), float(z)))
    if not candidates:
        return None
    return min(candidates)[1]


def brace_connection_demands(
    *,
    ry: float,
    fy: float,
    ag: float,
    expected_compression: float,
    plastic_modulus: float | None,
    method: Method = "LRFD",
) -> ConnectionDemand:
    """F2.6c.1 to F2.6c.3: the required strengths of a brace connection."""
    if min(ry, fy, ag) <= 0.0 or expected_compression < 0.0:
        raise ValueError("Ry, Fy, Ag and the expected compression must be positive.")
    factor = alpha_s(method)
    tension = ry * fy * ag / factor
    compression = expected_compression / factor
    steps = [
        CalcStep(
            "Required tension",
            "Ry Fy Ag / alpha_s",
            f"{ry:g} x {fy:g} x {ag:g} / {factor:g}",
            tension,
        ),
        CalcStep(
            "Required compression",
            "P_expected / alpha_s",
            f"{expected_compression:g} / {factor:g}",
            compression,
        ),
    ]
    notes: list[str] = []
    if plastic_modulus is None or plastic_modulus <= 0.0:
        flexure = 0.0
        notes.append(
            "F2.6c.3: the shape has no plastic modulus about its critical "
            "buckling axis; the flexural demand is not evaluated."
        )
    else:
        flexure = BUCKLING_MOMENT_FACTOR * ry * fy * plastic_modulus / factor
        steps.append(
            CalcStep(
                "Required flexure",
                "1.1 Ry Fy Z / alpha_s",
                f"1.1 x {ry:g} x {fy:g} x {plastic_modulus:g} / {factor:g}",
                flexure,
            )
        )
    return ConnectionDemand(tension, compression, flexure, tuple(steps), tuple(notes))


def fillet_weld_capacity(
    *,
    fexx: float,
    leg: float,
    both_sides: bool = True,
    method: Method = "LRFD",
) -> float:
    """AISC 360 J2.4: fillet-weld shear strength per unit length."""
    if min(fexx, leg) <= 0.0:
        raise ValueError("Fexx and the weld leg must be positive.")
    sides = 2.0 if both_sides else 1.0
    nominal = sides * 0.60 * fexx * FILLET_THROAT * leg
    factor = FILLET_PHI if method == "LRFD" else 1.0 / FILLET_OMEGA
    return nominal * factor


def gusset_weld_check(
    *,
    ry: float,
    fy: float,
    thickness: float,
    fexx: float,
    leg: float,
    both_sides: bool = True,
    method: Method = "LRFD",
) -> LimitStateCheck:
    """F2.6c.4: gusset-to-flange weld, compared per unit length."""
    if min(ry, fy, thickness) <= 0.0:
        raise ValueError("Ry, Fy and the gusset thickness must be positive.")
    factor = alpha_s(method)
    demand = GUSSET_WELD_FRACTION * ry * fy * thickness / factor
    capacity = fillet_weld_capacity(fexx=fexx, leg=leg, both_sides=both_sides, method=method)
    ratio = demand / capacity if capacity > 0.0 else math.inf
    sides = "2" if both_sides else "1"
    return LimitStateCheck(
        "Gusset-to-flange weld (F2.6c.4)",
        "0.6 Ry Fy tp / alpha_s <= phi 0.60 Fexx 0.707 leg",
        demand,
        capacity,
        ratio,
        (
            CalcStep(
                "Required shear per length",
                "0.6 Ry Fy tp / alpha_s",
                f"0.6 x {ry:g} x {fy:g} x {thickness:g} / {factor:g}",
                demand,
            ),
            CalcStep(
                "Weld throat",
                "0.707 leg",
                f"0.707 x {leg:g}",
                FILLET_THROAT * leg,
            ),
            CalcStep(
                "Available shear per length",
                f"{sides} x phi 0.60 Fexx 0.707 leg",
                f"{sides} x {capacity / (2.0 if both_sides else 1.0):.6g}",
                capacity,
            ),
        ),
    )


def gusset_weld_required_leg(
    *,
    ry: float,
    fy: float,
    thickness: float,
    fexx: float,
    both_sides: bool = True,
    method: Method = "LRFD",
) -> float:
    """The fillet-weld leg that just meets F2.6c.4, for a given electrode."""
    if min(ry, fy, thickness, fexx) <= 0.0:
        raise ValueError("Ry, Fy, tp and Fexx must be positive.")
    factor = alpha_s(method)
    demand = GUSSET_WELD_FRACTION * ry * fy * thickness / factor
    sides = 2.0 if both_sides else 1.0
    weld_factor = FILLET_PHI if method == "LRFD" else 1.0 / FILLET_OMEGA
    per_leg = sides * weld_factor * 0.60 * fexx * FILLET_THROAT
    return demand / per_leg
