"""AISC 341-22 gusset plates: Whitmore width, yielding and plate buckling.

The brace force reaches the gusset over a spread width. The Whitmore length
``Lw`` gives the effective width

    bw = 2 Lw tan(30 deg) + t_brace

and the plate is checked as a compression member of that width and the gusset
thickness: yielding ``Pn = Fy b t`` and buckling with ``r = t/sqrt(12)``,
``K = 0.65`` and the free length ``Lc``. The demand is the expected brace
strength ``Ry Fy Ag`` (AISC 341-22 F2.6c). No Qt, no OpenSees.
"""

from __future__ import annotations

import math

from opensees_studio.core.design.aisc360 import Method, Strength, _available, _critical_stress
from opensees_studio.core.design.calc import CalcStep, LimitStateCheck

#: F2.6c: the spread angle of the Whitmore width, 30 degrees each side.
WHITMORE_ANGLE = math.radians(30.0)
#: A gusset plate buckles as a column with K = 0.65 (AISC 360 Commentary).
GUSSET_K = 0.65


def whitmore_width(lw: float, brace_thickness: float = 0.0) -> float:
    """``bw = 2 Lw tan(30) + t_brace`` for a Whitmore length ``Lw``."""
    if lw <= 0.0:
        raise ValueError("The Whitmore length must be positive.")
    return 2.0 * lw * math.tan(WHITMORE_ANGLE) + max(0.0, brace_thickness)


def gusset_yielding(
    fy: float, width: float, thickness: float, *, method: Method = "LRFD"
) -> Strength:
    """F2.6c: gusset gross yielding, ``Pn = Fy b t``."""
    if min(fy, width, thickness) <= 0.0:
        raise ValueError("Fy, b and t must be positive.")
    nominal = fy * width * thickness
    return Strength(
        nominal,
        _available(nominal, "compression", method),
        "gusset yielding",
        (),
        (
            CalcStep("Gusset area", "Ag = b t", f"{width:g} x {thickness:g}", width * thickness),
            CalcStep("Nominal strength", "Pn = Fy Ag", f"{nominal:.6g}", nominal),
        ),
    )


def gusset_buckling(
    fy: float,
    e: float,
    width: float,
    thickness: float,
    length: float,
    *,
    method: Method = "LRFD",
    k: float = GUSSET_K,
) -> Strength:
    """F2.6c: plate buckling with ``r = t/sqrt(12)`` and ``K Lc/r``."""
    if min(fy, e, width, thickness, length) <= 0.0 or k <= 0.0:
        raise ValueError("Fy, E, b, t, Lc and K must be positive.")
    radius = thickness / math.sqrt(12.0)
    slenderness = k * length / radius
    fe = math.pi**2 * e / slenderness**2
    fcr = _critical_stress(fy, fe)
    nominal = fcr * width * thickness
    return Strength(
        nominal,
        _available(nominal, "compression", method),
        "gusset buckling",
        (),
        (
            CalcStep("Radius of gyration", "r = t/sqrt(12)", f"{radius:.6g}", radius),
            CalcStep("Slenderness", "KLc/r", f"{slenderness:.6g}", slenderness),
            CalcStep("Elastic buckling", "Fe = pi^2 E/(KLc/r)^2", f"{fe:.6g}", fe),
            CalcStep(
                "Critical stress",
                "Fcr = 0.658^(Fy/Fe) Fy" if fy / fe <= 2.25 else "Fcr = 0.877 Fe",
                f"{fcr:.6g}",
                fcr,
            ),
            CalcStep("Nominal strength", "Pn = Fcr b t", f"{nominal:.6g}", nominal),
        ),
    )


def gusset_checks(
    *,
    fy: float,
    e: float,
    width: float,
    thickness: float,
    whitmore_length: float,
    free_length: float,
    demand: float,
    brace_thickness: float = 0.0,
    method: Method = "LRFD",
) -> list[LimitStateCheck]:
    """The three gusset checks for an expected brace force ``demand``."""
    required = whitmore_width(whitmore_length, brace_thickness)
    yield_strength = gusset_yielding(fy, width, thickness, method=method)
    buckling = gusset_buckling(fy, e, width, thickness, free_length, method=method)
    whitmore_ratio = required / width if width > 0.0 else math.inf

    def record(name: str, strength: Strength) -> LimitStateCheck:
        return LimitStateCheck(
            name,
            strength.equation,
            abs(demand),
            strength.available,
            abs(demand) / strength.available if strength.available > 0 else math.inf,
            strength.steps,
        )

    return [
        LimitStateCheck(
            "Gusset Whitmore width",
            "bw = 2 Lw tan(30) + t_brace",
            required,
            width,
            whitmore_ratio,
            (
                CalcStep(
                    "Whitmore width", "bw = 2 Lw tan(30) + t_brace", f"{required:.6g}", required
                ),
                CalcStep("Gusset width", "b", f"{width:.6g}", width),
            ),
        ),
        record("Gusset yielding", yield_strength),
        record("Gusset buckling", buckling),
    ]
