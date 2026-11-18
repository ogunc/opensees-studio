"""AISC 360 Chapter J: welds, bolts and affected connection elements.

The functions return the same :class:`Strength` record as the member engine,
so a connection check can be reported with its nominal strength, available
strength, equation and calculation steps.

Implemented limit states:

* J2.4 fillet weld in shear, ``Rn = 0.60 Fexx (0.707 w) l``;
* J3.1 bolt shear/tension, ``Rn = Fn Ab``;
* J3.6 bolt bearing and tearout, ``2.4 d t Fu`` / ``1.2 lc t Fu`` (or the
  3.0 and 1.5 variants when deformation is not a design consideration);
* J3.4 slip-critical bolts, ``Rn = mu Du hf Tb ns``;
* J4.3 plate shear yielding, ``0.60 Fy Agv``;
* J4.4 plate shear rupture, ``0.60 Fu Anv``;
* J4.5 block shear, the lesser of ``0.60 Fu Anv + Ubs Fu Ant`` and
  ``0.60 Fy Agv + Ubs Fu Ant``;
* J5.1/J5.2 fillers, the weld leg increase and the bolt shear factor;
* J6 groove-welded splices;
* J7.1 bearing strength, ``1.8 Fy Apb``;
* J8 concrete bearing, ``0.85 f'c A1`` and the ``sqrt(A2/A1)`` increase;
* J10.1 flange local bending, ``6.25 Fyf tf^2``;
* J10.2/J10.3 web local yielding, ``Fyw tw (5k + lb)`` / ``(2.5k + lb)``;
* J10.4/J10.5 web local crippling;
* J10.6/J10.7 web sidesway buckling;
* J10.8 web compression buckling, ``24 tw^3 sqrt(E Fyw)/h Qf``.

The J10.6 web panel-zone shear strength lives with the AISC 341 SMF joint
table, because it is the seismic check that consumes it.

The caller supplies consistent units; no Qt, no OpenSees.
"""

from __future__ import annotations

import math
from typing import Literal

from opensees_studio.core.design.aisc360 import Method, Strength
from opensees_studio.core.design.calc import CalcStep

#: AISC 360 J2.4: fillet-weld throat and factors.
FILLET_THROAT = math.sqrt(0.5)
FILLET_PHI = 0.75
FILLET_OMEGA = 2.00
#: AISC 360 J3.1/J3.6: bolt factors.
BOLT_PHI = 0.75
BOLT_OMEGA = 2.00
#: AISC 360 J4.3/J4.4: plate shear factors.
SHEAR_YIELD_PHI = 1.00
SHEAR_YIELD_OMEGA = 1.50
SHEAR_RUPTURE_PHI = 0.75
SHEAR_RUPTURE_OMEGA = 2.00
#: AISC 360 J4.5: block-shear factor.
BLOCK_SHEAR_PHI = 0.75
BLOCK_SHEAR_OMEGA = 2.00
#: AISC 360 J3.4: slip-critical factors by hole type.
SLIP_FACTORS: dict[str, tuple[float, float]] = {
    "standard": (1.00, 1.50),
    "oversized": (0.85, 1.76),
    "long_slotted": (0.70, 2.14),
}
#: AISC 360 J3.4: the hole factor and the filler factor.
SLIP_DU = 1.13
SLIP_HF = 1.0

HoleType = Literal["standard", "oversized", "long_slotted"]


def _available(nominal: float, phi: float, omega: float, method: Method) -> float:
    return nominal * (phi if method == "LRFD" else 1.0 / omega)


def _strength(
    nominal: float,
    available: float,
    equation: str,
    steps: tuple[CalcStep, ...],
    notes: tuple[str, ...] = (),
) -> Strength:
    return Strength(nominal, available, equation, notes, steps)


def filler_bolt_factor(
    thickness: float,
    *,
    threshold: float = 0.25,
    slope: float = 0.4,
) -> float:
    """J5.2: bolt shear reduction for fillers thicker than ``threshold``.

    The default is the US customary form (1/4 in. and 0.4 per inch). The
    caller passes the SI equivalents when the project is in SI units, because
    the AISC 360 metric form is written with a 6 mm threshold and 0.0154 per
    millimetre.
    """
    if thickness <= 0.0:
        raise ValueError("The filler thickness must be positive.")
    if threshold <= 0.0 or slope <= 0.0:
        raise ValueError("The filler threshold and slope must be positive.")
    if thickness <= threshold:
        return 1.0
    return max(0.85, 1.0 - slope * (thickness - threshold))


def filler_weld_required_leg(
    required_leg: float,
    thickness: float,
    *,
    transfers_force: bool = False,
) -> float:
    """J5.1a: the weld leg required with a filler that does not transfer force."""
    if required_leg <= 0.0 or thickness <= 0.0:
        raise ValueError("The weld leg and filler thickness must be positive.")
    return required_leg if transfers_force else required_leg + thickness


def fillet_weld_strength(
    *,
    fexx: float,
    leg: float,
    length: float,
    both_sides: bool = True,
    filler_thickness: float | None = None,
    filler_transfers_force: bool = False,
    method: Method = "LRFD",
) -> Strength:
    """J2.4: fillet-weld shear strength, ``Rn = 0.60 Fexx (0.707 w) l``.

    A filler that does not transfer force is reported under J5.1a; the caller
    must increase the leg by the filler thickness (the provided leg is what is
    checked).
    """
    if min(fexx, leg, length) <= 0.0:
        raise ValueError("Fexx, the weld leg and the length must be positive.")
    sides = 2.0 if both_sides else 1.0
    throat = FILLET_THROAT * leg
    area = throat * length * sides
    nominal = 0.60 * fexx * area
    available = _available(nominal, FILLET_PHI, FILLET_OMEGA, method)
    notes: tuple[str, ...] = ()
    if filler_thickness is not None and not filler_transfers_force:
        required = filler_weld_required_leg(leg, filler_thickness, transfers_force=False)
        notes = (
            f"J5.1a: the filler does not transfer force; increase the weld leg "
            f"from {leg:g} to at least {required:g}.",
        )
    return _strength(
        nominal,
        available,
        "J2-4 fillet weld shear",
        (
            CalcStep("Effective throat", "0.707 w", f"0.707 x {leg:g}", throat),
            CalcStep(
                "Effective area",
                "Awe = throat x l x sides",
                f"{throat:.6g} x {length:g} x {sides:g}",
                area,
            ),
            CalcStep("Nominal strength", "0.60 Fexx Awe", f"{nominal:.6g}", nominal),
        ),
        notes,
    )


def bolt_shear_strength(
    *,
    fnv: float,
    diameter: float,
    count: int,
    filler_thickness: float | None = None,
    filler_threshold: float = 0.25,
    filler_slope: float = 0.4,
    method: Method = "LRFD",
) -> Strength:
    """J3.1: bolt shear, ``Rn = n Fnv Ab``, with the J5.2 filler factor."""
    if min(fnv, diameter) <= 0.0 or count < 1:
        raise ValueError("Fnv and the bolt diameter must be positive, and n >= 1.")
    area = math.pi * diameter**2 / 4.0
    nominal = count * fnv * area
    notes: tuple[str, ...] = ()
    if filler_thickness is not None:
        factor = filler_bolt_factor(
            filler_thickness, threshold=filler_threshold, slope=filler_slope
        )
        nominal *= factor
        notes = (f"J5.2: filler factor {factor:.3g} on the bolt shear strength.",)
    available = _available(nominal, BOLT_PHI, BOLT_OMEGA, method)
    return _strength(
        nominal,
        available,
        "J3-1 bolt shear",
        (
            CalcStep("Bolt area", "Ab = pi d^2 / 4", f"pi x {diameter:g}^2 / 4", area),
            CalcStep(
                "Nominal strength",
                "n Fnv Ab",
                f"{count} x {fnv:g} x {area:.6g}",
                nominal,
            ),
        ),
        notes,
    )


def bolt_tension_strength(
    *,
    fnt: float,
    diameter: float,
    count: int,
    method: Method = "LRFD",
) -> Strength:
    """J3.1: bolt tension, ``Rn = n Fnt Ab``."""
    if min(fnt, diameter) <= 0.0 or count < 1:
        raise ValueError("Fnt and the bolt diameter must be positive, and n >= 1.")
    area = math.pi * diameter**2 / 4.0
    nominal = count * fnt * area
    available = _available(nominal, BOLT_PHI, BOLT_OMEGA, method)
    return _strength(
        nominal,
        available,
        "J3-1 bolt tension",
        (
            CalcStep("Bolt area", "Ab = pi d^2 / 4", f"pi x {diameter:g}^2 / 4", area),
            CalcStep(
                "Nominal strength",
                "n Fnt Ab",
                f"{count} x {fnt:g} x {area:.6g}",
                nominal,
            ),
        ),
    )


def bolt_bearing_strength(
    *,
    fu: float,
    thickness: float,
    diameter: float,
    count: int,
    edge_distance: float,
    hole_diameter: float | None = None,
    deformation: bool = True,
    method: Method = "LRFD",
) -> Strength:
    """J3.6: bolt bearing and tearout at a standard hole.

    ``edge_distance`` is measured from the bolt center to the material edge;
    the clear distance ``lc`` subtracts half the hole. ``hole_diameter``
    defaults to ``diameter`` plus 1/16 in. in the same units (the caller can
    pass the exact value, e.g. 2 mm in SI).
    """
    if min(fu, thickness, diameter, edge_distance) <= 0.0 or count < 1:
        raise ValueError("Fu, t, d, the edge distance must be positive, and n >= 1.")
    hole = diameter + 0.0625 if hole_diameter is None else hole_diameter
    clear = max(0.0, edge_distance - hole / 2.0)
    bearing_factor = 2.4 if deformation else 3.0
    tearout_factor = 1.2 if deformation else 1.5
    bearing = bearing_factor * diameter * thickness * fu
    tearout = tearout_factor * clear * thickness * fu
    nominal = count * min(bearing, tearout)
    available = _available(nominal, BOLT_PHI, BOLT_OMEGA, method)
    return _strength(
        nominal,
        available,
        "J3-6a/c bearing and tearout",
        (
            CalcStep(
                "Bearing",
                f"{bearing_factor:g} d t Fu",
                f"{bearing_factor:g} x {diameter:g} x {thickness:g} x {fu:g}",
                bearing,
            ),
            CalcStep(
                "Tearout",
                f"{tearout_factor:g} lc t Fu",
                f"{tearout_factor:g} x {clear:.6g} x {thickness:g} x {fu:g}",
                tearout,
            ),
            CalcStep(
                "Nominal strength",
                "n min(bearing, tearout)",
                f"{count} x {min(bearing, tearout):.6g}",
                nominal,
            ),
        ),
    )


def slip_critical_strength(
    *,
    mu: float,
    tb: float,
    ns: int,
    count: int,
    hole_type: HoleType = "standard",
    method: Method = "LRFD",
) -> Strength:
    """J3.4: slip-critical bolt strength, ``Rn = mu Du hf Tb ns`` per bolt."""
    if min(mu, tb) <= 0.0 or ns < 1 or count < 1:
        raise ValueError("mu, Tb and ns must be positive, and n >= 1.")
    if hole_type not in SLIP_FACTORS:
        raise ValueError(f"Unknown hole type {hole_type!r}.")
    phi, omega = SLIP_FACTORS[hole_type]
    nominal = count * mu * SLIP_DU * SLIP_HF * tb * ns
    available = _available(nominal, phi, omega, method)
    return _strength(
        nominal,
        available,
        "J3-4 slip-critical",
        (
            CalcStep(
                "Nominal slip resistance",
                "n mu Du hf Tb ns",
                f"{count} x {mu:g} x {SLIP_DU:g} x {SLIP_HF:g} x {tb:g} x {ns}",
                nominal,
            ),
        ),
    )


def plate_shear_yielding(*, fy: float, agv: float, method: Method = "LRFD") -> Strength:
    """J4.3: plate shear yielding, ``Rn = 0.60 Fy Agv``."""
    if min(fy, agv) <= 0.0:
        raise ValueError("Fy and Agv must be positive.")
    nominal = 0.60 * fy * agv
    available = _available(nominal, SHEAR_YIELD_PHI, SHEAR_YIELD_OMEGA, method)
    return _strength(
        nominal,
        available,
        "J4-3 shear yielding",
        (
            CalcStep("Gross shear area", "Agv", f"{agv:g}", agv),
            CalcStep("Nominal strength", "0.60 Fy Agv", f"{nominal:.6g}", nominal),
        ),
    )


def plate_shear_rupture(*, fu: float, anv: float, method: Method = "LRFD") -> Strength:
    """J4.4: plate shear rupture, ``Rn = 0.60 Fu Anv``."""
    if min(fu, anv) <= 0.0:
        raise ValueError("Fu and Anv must be positive.")
    nominal = 0.60 * fu * anv
    available = _available(nominal, SHEAR_RUPTURE_PHI, SHEAR_RUPTURE_OMEGA, method)
    return _strength(
        nominal,
        available,
        "J4-4 shear rupture",
        (
            CalcStep("Net shear area", "Anv", f"{anv:g}", anv),
            CalcStep("Nominal strength", "0.60 Fu Anv", f"{nominal:.6g}", nominal),
        ),
    )


def block_shear_strength(
    *,
    fy: float,
    fu: float,
    agv: float,
    anv: float,
    ant: float,
    uniform_tension: bool = True,
    method: Method = "LRFD",
) -> Strength:
    """J4.5: block shear, the lesser of the two failure paths."""
    if min(fy, fu, agv, anv) <= 0.0 or ant < 0.0:
        raise ValueError("Fy, Fu, Agv and Anv must be positive; Ant cannot be negative.")
    ubs = 1.0 if uniform_tension else 0.5
    shear_rupture = 0.60 * fu * anv + ubs * fu * ant
    shear_yield = 0.60 * fy * agv + ubs * fu * ant
    nominal = min(shear_rupture, shear_yield)
    available = _available(nominal, BLOCK_SHEAR_PHI, BLOCK_SHEAR_OMEGA, method)
    return _strength(
        nominal,
        available,
        "J4-5 block shear",
        (
            CalcStep(
                "Shear rupture path",
                "0.60 Fu Anv + Ubs Fu Ant",
                f"0.60 x {fu:g} x {anv:g} + {ubs:g} x {fu:g} x {ant:g}",
                shear_rupture,
            ),
            CalcStep(
                "Shear yield path",
                "0.60 Fy Agv + Ubs Fu Ant",
                f"0.60 x {fy:g} x {agv:g} + {ubs:g} x {fu:g} x {ant:g}",
                shear_yield,
            ),
            CalcStep(
                "Nominal strength",
                "min(rupture, yield)",
                f"{nominal:.6g}",
                nominal,
            ),
        ),
    )


def bearing_strength(*, fy: float, apb: float, method: Method = "LRFD") -> Strength:
    """J7-1: bearing strength of a finished surface or a pin, ``1.8 Fy Apb``."""
    if min(fy, apb) <= 0.0:
        raise ValueError("Fy and Apb must be positive.")
    nominal = 1.8 * fy * apb
    available = _available(nominal, 0.75, 2.00, method)
    return _strength(
        nominal,
        available,
        "J7-1 bearing",
        (
            CalcStep("Projected bearing area", "Apb", f"{apb:g}", apb),
            CalcStep("Nominal strength", "1.8 Fy Apb", f"{nominal:.6g}", nominal),
        ),
    )


def concrete_bearing_strength(
    *,
    fc: float,
    a1: float,
    a2: float | None = None,
    method: Method = "LRFD",
) -> Strength:
    """J8: concrete bearing under a column base, full or partial area."""
    if min(fc, a1) <= 0.0:
        raise ValueError("f'c and A1 must be positive.")
    steps: tuple[CalcStep, ...]
    if a2 is None or a2 <= a1:
        nominal = 0.85 * fc * a1
        equation = "J8-1 concrete bearing (full area)"
        steps = (
            CalcStep("Loaded area", "A1", f"{a1:g}", a1),
            CalcStep("Nominal strength", "0.85 f'c A1", f"{nominal:.6g}", nominal),
        )
    else:
        ratio = math.sqrt(a2 / a1)
        nominal = min(0.85 * fc * a1 * ratio, 1.7 * fc * a1)
        equation = "J8-2 concrete bearing (partial area)"
        steps = (
            CalcStep("Loaded area", "A1", f"{a1:g}", a1),
            CalcStep("Support area", "A2", f"{a2:g}", a2),
            CalcStep("Area ratio", "sqrt(A2/A1)", f"{ratio:.6g}", ratio),
            CalcStep(
                "Nominal strength",
                "min(0.85 f'c A1 sqrt(A2/A1), 1.7 f'c A1)",
                f"{nominal:.6g}",
                nominal,
            ),
        )
    available = _available(nominal, 0.65, 2.31, method)
    return _strength(nominal, available, equation, steps)


def splice_strength(*, nominal: float, method: Method = "LRFD") -> Strength:
    """J6: a groove-welded beam splice develops the smaller section's nominal strength."""
    if nominal <= 0.0:
        raise ValueError("The splice nominal strength must be positive.")
    return _strength(
        nominal,
        nominal,
        "J6 groove-welded splice",
        (
            CalcStep(
                "Nominal strength of the smaller section",
                "Rn",
                f"{nominal:g}",
                nominal,
            ),
        ),
    )


def flange_local_bending(
    *,
    fyf: float,
    tf: float,
    bf: float,
    lb: float,
    distance_to_end: float,
    method: Method = "LRFD",
) -> Strength:
    """J10-1: flange local bending under a tensile concentrated force."""
    if min(fyf, tf, bf, lb, distance_to_end) <= 0.0:
        raise ValueError("Fyf, tf, bf, lb and the distance to the end must be positive.")
    if lb < 0.15 * bf:
        return _strength(
            0.0,
            0.0,
            "J10-1 not required",
            (),
            ("J10.1: the loaded length is less than 0.15 bf; the check is not required.",),
        )
    nominal = 6.25 * fyf * tf**2
    notes: tuple[str, ...] = ()
    if distance_to_end < 10.0 * tf:
        nominal *= 0.5
        notes = ("J10.1: the force is within 10 tf of the member end; Rn is reduced by 50%.",)
    available = _available(nominal, 0.90, 1.67, method)
    return _strength(
        nominal,
        available,
        "J10-1 flange local bending",
        (
            CalcStep("Loaded flange thickness", "tf", f"{tf:g}", tf),
            CalcStep("Nominal strength", "6.25 Fyf tf^2", f"{nominal:.6g}", nominal),
        ),
        notes,
    )


def web_local_yielding(
    *,
    fyw: float,
    tw: float,
    k: float,
    lb: float,
    d: float,
    distance_to_end: float,
    method: Method = "LRFD",
) -> Strength:
    """J10-2/J10-3: web local yielding under a concentrated force."""
    if min(fyw, tw, k, lb, d, distance_to_end) <= 0.0:
        raise ValueError("Fyw, tw, k, lb, d and the distance to the end must be positive.")
    if distance_to_end > d:
        nominal = fyw * tw * (5.0 * k + lb)
        equation = "J10-2 web local yielding (end distance > d)"
    else:
        nominal = fyw * tw * (2.5 * k + lb)
        equation = "J10-3 web local yielding (end distance <= d)"
    available = _available(nominal, 1.00, 1.50, method)
    return _strength(
        nominal,
        available,
        equation,
        (
            CalcStep("Bearing length", "lb", f"{lb:g}", lb),
            CalcStep(
                "Nominal strength",
                "Fyw tw (5k + lb) or Fyw tw (2.5k + lb)",
                f"{nominal:.6g}",
                nominal,
            ),
        ),
    )


def web_local_crippling(
    *,
    fyw: float,
    e: float,
    tw: float,
    tf: float,
    d: float,
    lb: float,
    distance_to_end: float,
    qf: float = 1.0,
    method: Method = "LRFD",
) -> Strength:
    """J10-4/J10-5: web local crippling under a compressive concentrated force."""
    if min(fyw, e, tw, tf, d, lb, distance_to_end, qf) <= 0.0:
        raise ValueError("Fyw, E, tw, tf, d, lb, distance and Qf must be positive.")
    ratio = lb / d
    thickness = tw / tf
    root = math.sqrt(e * fyw * tf / tw)
    if distance_to_end >= d / 2.0:
        nominal = 0.80 * tw**2 * (1.0 + 3.0 * ratio * thickness**1.5) * root * qf
        equation = "J10-4 web local crippling (end distance >= d/2)"
    elif ratio <= 0.2:
        nominal = 0.40 * tw**2 * (1.0 + 3.0 * ratio * thickness**1.5) * root * qf
        equation = "J10-5a web local crippling (end distance < d/2, lb/d <= 0.2)"
    else:
        nominal = 0.40 * tw**2 * (1.0 + (4.0 * ratio - 0.2) * thickness**1.5) * root * qf
        equation = "J10-5b web local crippling (end distance < d/2, lb/d > 0.2)"
    available = _available(nominal, 0.75, 2.00, method)
    return _strength(
        nominal,
        available,
        equation,
        (
            CalcStep("lb / d", "lb / d", f"{ratio:.6g}", ratio),
            CalcStep("tw / tf", "tw / tf", f"{thickness:.6g}", thickness),
            CalcStep(
                "Nominal strength",
                "0.80 or 0.40 tw^2 [..] sqrt(E Fyw tf/tw) Qf",
                f"{nominal:.6g}",
                nominal,
            ),
        ),
    )


def web_sidesway_buckling(
    *,
    fy: float,
    sx: float,
    mr: float,
    tw: float,
    tf: float,
    h: float,
    bf: float,
    lb: float,
    cr_low: float = 480_000.0,
    cr_high: float = 960_000.0,
    restrained: bool = True,
    method: Method = "LRFD",
) -> Strength:
    """J10-6/J10-7: web sidesway buckling under a compressive single force.

    ``cr_low`` and ``cr_high`` are the J10.4 constants in the caller's stress
    units: 480,000 ksi and 960,000 ksi in US customary units, 3.3e6 MPa and
    6.6e6 MPa in SI (mm, N), or the same values in Pa for SI (m, N). The
    ``(h/tw)/(Lb/bf)`` ratio and the 2.3/1.7 limits are dimensionless.
    """
    if min(fy, sx, mr, tw, tf, h, bf, lb, cr_low, cr_high) <= 0.0:
        raise ValueError("Fy, Sx, Mr, tw, tf, h, bf, Lb and Cr must be positive.")
    alpha = 1.0 if method == "LRFD" else 1.5
    my = fy * sx
    cr = cr_high if alpha * mr < my else cr_low
    ratio = (h / tw) / (lb / bf)
    limit = 2.3 if restrained else 1.7
    if ratio > limit:
        return _strength(
            0.0,
            0.0,
            "J10-6/7 not applicable",
            (),
            (
                f"J10.4: (h/tw)/(Lb/bf) = {ratio:.6g} exceeds {limit:g}; "
                "the sidesway buckling limit state does not apply.",
            ),
        )
    base = cr * tw**3 * tf / h**2
    nominal = base * (1.0 + 0.4 * ratio**3) if restrained else base * (0.4 * ratio**3)
    available = _available(nominal, 0.85, 1.76, method)
    return _strength(
        nominal,
        available,
        "J10-6 web sidesway buckling" if restrained else "J10-7 web sidesway buckling",
        (
            CalcStep("(h/tw)/(Lb/bf)", "(h/tw)/(Lb/bf)", f"{ratio:.6g}", ratio),
            CalcStep("Cr", "960,000 or 480,000 ksi", f"{cr:g}", cr),
            CalcStep(
                "Nominal strength",
                "Cr tw^3 tf/h^2 [1 + 0.4 ((h/tw)/(Lb/bf))^3]",
                f"{nominal:.6g}",
                nominal,
            ),
        ),
    )


def web_compression_buckling(
    *,
    e: float,
    fyw: float,
    tw: float,
    h: float,
    qf: float = 1.0,
    distance_to_end: float,
    d: float,
    method: Method = "LRFD",
) -> Strength:
    """J10-8: web compression buckling under a pair of compressive forces."""
    if min(e, fyw, tw, h, qf, distance_to_end, d) <= 0.0:
        raise ValueError("E, Fyw, tw, h, Qf, distance and d must be positive.")
    nominal = 24.0 * tw**3 * math.sqrt(e * fyw) / h * qf
    notes: tuple[str, ...] = ()
    if distance_to_end < d / 2.0:
        nominal *= 0.5
        notes = ("J10.5: the force is within d/2 of the member end; Rn is reduced by 50%.",)
    available = _available(nominal, 0.90, 1.67, method)
    return _strength(
        nominal,
        available,
        "J10-8 web compression buckling",
        (CalcStep("Nominal strength", "24 tw^3 sqrt(E Fyw)/h Qf", f"{nominal:.6g}", nominal),),
        notes,
    )
