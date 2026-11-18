"""AISC 358-22 Section 5.5: RBS beam web-to-column flange connection.

For SMF the beam web is joined to the column flange with a CJP groove weld
between the weld access holes; the single plate is backing and shall be at
least 3/8 in. (10 mm) thick. For IMF the same CJP is the default, but a bolted
single-plate shear connection is permitted. The bolted plate is checked for
gross shear yielding, net shear rupture, bolt shear and the fillet weld to the
column flange; the minimum fillet leg is 5/8 of the plate thickness.

The required shear is the beam required shear strength ``Vu`` of AISC 358
Section 2.5. The net area assumes all bolt holes in one vertical line, which
is conservative for a multi-column bolt group; bearing and block shear are
reported as not checked. No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from typing import Literal

from opensees_studio.core.design.aisc360 import Method
from opensees_studio.core.design.calc import CalcStep, LimitStateCheck

#: AISC 358-22 5.5: minimum backing/plate thickness, 3/8 in. (10 mm).
MIN_PLATE_THICKNESS_IN = 0.375
#: AISC 358-22 5.5: minimum fillet leg, 5/8 of the plate thickness.
MIN_WELD_LEG_FRACTION = 0.625
#: AISC 360 J2.4: fillet-weld throat and resistance factor.
FILLET_THROAT = math.sqrt(0.5)
FILLET_PHI = 0.75
FILLET_OMEGA = 2.00
#: AISC 360 G2: shear yielding and shear rupture factors.
SHEAR_YIELD_PHI = 1.00
SHEAR_YIELD_OMEGA = 1.50
SHEAR_RUPTURE_PHI = 0.75
SHEAR_RUPTURE_OMEGA = 2.00
#: AISC 360 J3.6: bolt shear factors.
BOLT_SHEAR_PHI = 0.75
BOLT_SHEAR_OMEGA = 2.00

WebConnectionType = Literal["cjp", "bolted"]


def _available(nominal: float, phi: float, omega: float, method: Method) -> float:
    return nominal * (phi if method == "LRFD" else 1.0 / omega)


def _check(
    name: str,
    equation: str,
    demand: float,
    capacity: float,
    steps: tuple[CalcStep, ...],
) -> LimitStateCheck:
    ratio = demand / capacity if capacity > 0.0 else math.inf
    return LimitStateCheck(name, equation, demand, capacity, ratio, steps)


def web_connection_checks(
    *,
    vu: float,
    plate_thickness: float,
    plate_height: float,
    bolt_count: int,
    bolt_diameter: float,
    bolt_fnv: float,
    hole_allowance: float,
    weld_leg: float | None,
    weld_fexx: float,
    fy: float,
    fu: float,
    min_thickness: float,
    method: Method = "LRFD",
    connection_type: WebConnectionType = "bolted",
) -> tuple[list[LimitStateCheck], list[str]]:
    """The 5.5 checks of one RBS beam web connection.

    ``min_thickness`` is 3/8 in. (10 mm) in project units; ``hole_allowance``
    is the hole diameter increment (1/16 in. or 2 mm) in project units.
    """
    if vu < 0.0:
        raise ValueError("Vu cannot be negative.")
    if min(plate_thickness, plate_height, fy, fu) <= 0.0:
        raise ValueError("The plate and material values must be positive.")
    if min_thickness <= 0.0:
        raise ValueError("The minimum thickness must be positive.")

    thickness = _check(
        "Web plate thickness (5.5)",
        "tp >= 3/8 in. (10 mm)",
        min_thickness,
        plate_thickness,
        (
            CalcStep(
                "Minimum plate thickness", "3/8 in. (10 mm)", f"{min_thickness:.6g}", min_thickness
            ),
            CalcStep("Provided plate thickness", "tp", f"{plate_thickness:.6g}", plate_thickness),
        ),
    )
    notes: list[str] = []
    if connection_type == "cjp":
        notes.append(
            "AISC 358 5.5(1): the SMF beam web uses a CJP groove weld between the "
            "weld access holes; the single plate is backing and shall be at least "
            "3/8 in. (10 mm) thick. The CJP weld is demand critical; its capacity "
            "is not computed."
        )
        return [thickness], notes

    checks = [thickness]
    if bolt_count < 1:
        raise ValueError("At least one bolt is required.")
    if min(bolt_diameter, bolt_fnv, weld_fexx) <= 0.0 or hole_allowance < 0.0:
        raise ValueError("The bolt, weld and hole values must be positive.")
    if weld_leg is not None and weld_leg <= 0.0:
        raise ValueError("The weld leg must be positive.")
    gross = plate_thickness * plate_height
    yield_nominal = 0.60 * fy * gross
    yield_capacity = _available(yield_nominal, SHEAR_YIELD_PHI, SHEAR_YIELD_OMEGA, method)
    checks.append(
        _check(
            "Web plate shear yielding (5.5)",
            "Vu <= phi 0.60 Fy tp hp",
            vu,
            yield_capacity,
            (
                CalcStep(
                    "Gross shear area",
                    "Ag = tp hp",
                    f"{plate_thickness:g} x {plate_height:g}",
                    gross,
                ),
                CalcStep("Nominal strength", "0.60 Fy Ag", f"{yield_nominal:.6g}", yield_nominal),
            ),
        )
    )
    net_height = max(0.0, plate_height - bolt_count * (bolt_diameter + hole_allowance))
    net = plate_thickness * net_height
    rupture_nominal = 0.60 * fu * net
    rupture_capacity = _available(rupture_nominal, SHEAR_RUPTURE_PHI, SHEAR_RUPTURE_OMEGA, method)
    checks.append(
        _check(
            "Web plate shear rupture (5.5)",
            "Vu <= phi 0.60 Fu Anv",
            vu,
            rupture_capacity,
            (
                CalcStep(
                    "Net shear area",
                    "Anv = tp (hp - n (db + 1/16))",
                    f"{plate_thickness:g} x {net_height:.6g}",
                    net,
                ),
                CalcStep(
                    "Nominal strength", "0.60 Fu Anv", f"{rupture_nominal:.6g}", rupture_nominal
                ),
            ),
        )
    )
    bolt_area = math.pi * bolt_diameter**2 / 4.0
    bolt_nominal = bolt_count * bolt_fnv * bolt_area
    bolt_capacity = _available(bolt_nominal, BOLT_SHEAR_PHI, BOLT_SHEAR_OMEGA, method)
    checks.append(
        _check(
            "Web bolts in shear (5.5)",
            "Vu <= n phi Fnv Ab",
            vu,
            bolt_capacity,
            (
                CalcStep(
                    "Bolt area",
                    "Ab = pi db^2 / 4",
                    f"pi x {bolt_diameter:g}^2 / 4",
                    bolt_area,
                ),
                CalcStep(
                    "Nominal strength",
                    "n Fnv Ab",
                    f"{bolt_count} x {bolt_fnv:g} x {bolt_area:.6g}",
                    bolt_nominal,
                ),
            ),
        )
    )
    if weld_leg is None:
        notes.append(
            "AISC 358 5.5(2): the fillet weld leg was not given; the plate-to-"
            "column weld is not checked."
        )
    else:
        min_leg = MIN_WELD_LEG_FRACTION * plate_thickness
        checks.append(
            _check(
                "Web plate weld minimum leg (5.5)",
                "leg >= 5/8 tp",
                min_leg,
                weld_leg,
                (
                    CalcStep("Minimum leg", "5/8 tp", f"0.625 x {plate_thickness:g}", min_leg),
                    CalcStep("Provided leg", "leg", f"{weld_leg:g}", weld_leg),
                ),
            )
        )
        weld_nominal = 2.0 * 0.60 * weld_fexx * FILLET_THROAT * weld_leg * plate_height
        weld_capacity = _available(weld_nominal, FILLET_PHI, FILLET_OMEGA, method)
        checks.append(
            _check(
                "Web plate fillet weld (5.5)",
                "Vu <= 2 phi 0.60 Fexx 0.707 leg hp",
                vu,
                weld_capacity,
                (
                    CalcStep(
                        "Weld throat",
                        "0.707 leg",
                        f"0.707 x {weld_leg:g}",
                        FILLET_THROAT * weld_leg,
                    ),
                    CalcStep(
                        "Nominal strength",
                        "2 x 0.60 Fexx x throat x hp",
                        f"2 x 0.60 x {weld_fexx:g} x {FILLET_THROAT * weld_leg:.6g} x {plate_height:g}",
                        weld_nominal,
                    ),
                ),
            )
        )
    notes.append(
        "AISC 358 5.5(2): the plate net area assumes all bolt holes in one "
        "vertical line; a different layout needs its own net section. Bolt "
        "bearing at the holes and block shear are not checked."
    )
    notes.append(
        "AISC 358 5.5(2): the IMF bolted single-plate connection is a "
        "slip-critical connection; the slip resistance and the J3-6a bearing "
        "limit are not checked."
    )
    return checks, notes
