"""AISC 360-16 available strengths of steel members.

The equations of *Specification for Structural Steel Buildings* (ANSI/AISC
360-16) a frame check needs. This module holds the doubly symmetric I-shapes
(W, M, S and HP families), the common pieces (factors, buckling stress,
effective width, interaction) and :func:`check_member`, which works on any
shape following :class:`SteelShape`; channels, tees, angles and HSS are in
:mod:`core.design.aisc360_shapes`. For the I-shapes:

* **D2** tension, yielding of the gross section and, when the caller supplies
  a net area and shear-lag factor, rupture of the effective net section;
* **E3 / E4 / E7** compression: flexural buckling about both axes, torsional
  buckling (E4, doubly symmetric), with the effective area of slender
  elements (E7);
* **F2 / F3** major-axis flexure of a compact web: yielding,
  lateral-torsional buckling with ``Cb``, and flange local buckling;
* **F4 / F5** major-axis flexure of a noncompact or slender web: the four
  limit states of F4 or F5, including the web plastification and bending
  strength reduction factors;
* **F6** minor-axis flexure;
* **G2.1 / G6** shear along the web and the flanges;
* **H1-1** interaction of axial force and biaxial flexure.

Every function works in one consistent unit system (the project's): the
shape's properties are scaled once by the caller. ``h``, the clear web height,
is taken as ``d - 2 tf`` (the table carries no ``k``), slightly conservative.

LRFD uses the resistance factors φ, ASD the safety factors Ω (``φ Rn`` and
``Rn / Ω``). No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Protocol

from opensees_studio.core.design.calc import CalcStep, LimitStateCheck
from opensees_studio.core.design.stability import b1, pe1, tau_b

Method = Literal["LRFD", "ASD"]

#: Families checked with the doubly symmetric I-shape provisions.
I_SHAPE_FAMILIES = frozenset({"W", "M", "S", "HP"})

#: Resistance factor φ and safety factor Ω per limit state (AISC 360-16).
FACTORS: dict[str, tuple[float, float]] = {
    "tension": (0.90, 1.67),
    "tension_rupture": (0.75, 2.00),
    "compression": (0.90, 1.67),
    "flexure": (0.90, 1.67),
    "shear": (0.90, 1.67),
    "shear_rolled": (1.00, 1.50),  # G2.1(a): rolled I-shapes with a stocky web
}


@dataclass(frozen=True)
class IShape:
    """Section properties of a doubly symmetric I-shape, in consistent units."""

    name: str
    A: float
    d: float
    bf: float
    tw: float
    tf: float
    Ix: float
    Iy: float
    Zx: float
    Zy: float
    Sx: float
    Sy: float
    rx: float
    ry: float
    J: float
    Cw: float

    @property
    def h(self) -> float:
        """Clear web height, taken as ``d - 2 tf``."""
        return self.d - 2.0 * self.tf

    @property
    def ho(self) -> float:
        """Distance between the flange centroids."""
        return self.d - self.tf

    @property
    def rts(self) -> float:
        """Effective radius of gyration for lateral-torsional buckling (F2-7)."""
        return math.sqrt(math.sqrt(self.Iy * self.Cw) / self.Sx)

    @property
    def flange_ratio(self) -> float:
        return self.bf / (2.0 * self.tf)

    @property
    def web_ratio(self) -> float:
        return self.h / self.tw

    @property
    def c(self) -> float:
        """The ``c`` of F2-8a: 1 for a doubly symmetric I-shape."""
        return 1.0

    # The SteelShape protocol: the limit states of this family.
    def tension(self, steel: Steel, method: Method) -> Strength:
        return tension(self, steel, method)

    def compression(
        self,
        steel: Steel,
        method: Method,
        *,
        length_x: float,
        length_y: float,
        k_x: float = 1.0,
        k_y: float = 1.0,
    ) -> Strength:
        return compression(
            self, steel, method, length_x=length_x, length_y=length_y, k_x=k_x, k_y=k_y
        )

    def flexure_major(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return flexure_major(self, steel, method, unbraced=unbraced, cb=cb)

    def flexure_minor(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return flexure_minor(self, steel, method)

    def shear_major(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return shear_major(self, steel, method)

    def shear_minor(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return shear_minor(self, steel, method)


@dataclass(frozen=True)
class BuiltUpIShape(IShape):
    """A doubly symmetric I-shape welded from plates (a built-up column or plate girder).

    It is checked like a rolled I-shape with what AISC 360 sets apart for built-up
    sections: the flange slenderness limits take ``kc = 4 / sqrt(h/tw)`` (Table
    B4.1a case 2, B4.1b case 11), and web shear has no rolled-shape exception
    and takes transverse stiffeners at ``stiffener_spacing`` (G2.1).
    """

    stiffener_spacing: float | None = None
    """Clear distance a between transverse web stiffeners; None = unstiffened."""

    @property
    def kc(self) -> float:
        """Table B4.1 note: ``kc = 4 / sqrt(h/tw)``, between 0.35 and 0.76."""
        return min(max(4.0 / math.sqrt(self.h / self.tw), 0.35), 0.76)


@dataclass(frozen=True)
class Steel:
    """Material of the check: yield stress, ultimate stress, Young's and shear moduli."""

    Fy: float
    E: float
    G: float
    Fu: float | None = None


@dataclass(frozen=True)
class Strength:
    """One available strength: the nominal value, the factor and the governing equation."""

    nominal: float
    available: float
    equation: str
    notes: tuple[str, ...] = ()
    steps: tuple[CalcStep, ...] = ()


def _step(label: str, formula: str, substitution: str, value: float) -> CalcStep:
    return CalcStep(label, formula, substitution, value)


def _available(nominal: float, kind: str, method: Method) -> float:
    phi, omega = FACTORS[kind]
    return phi * nominal if method == "LRFD" else nominal / omega


# ──────────────────────────── classification ────────────────────────────
@dataclass(frozen=True)
class Slenderness:
    """Width-to-thickness ratios against the limits of Table B4.1."""

    flange: float
    web: float
    flange_compression_limit: float
    web_compression_limit: float
    flange_compact: float
    flange_noncompact: float
    web_compact: float
    web_noncompact: float

    @property
    def slender_in_compression(self) -> bool:
        return self.flange > self.flange_compression_limit or self.web > self.web_compression_limit

    @property
    def flange_class(self) -> str:
        if self.flange <= self.flange_compact:
            return "compact"
        return "noncompact" if self.flange <= self.flange_noncompact else "slender"

    @property
    def web_class(self) -> str:
        if self.web <= self.web_compact:
            return "compact"
        return "noncompact" if self.web <= self.web_noncompact else "slender"


def slenderness(shape: IShape, steel: Steel) -> Slenderness:
    """Table B4.1a (compression, cases 1 and 5) and B4.1b (flexure, cases 10 and 15).

    A built-up shape's flanges take cases 2 and 11 instead: ``0.64 sqrt(kc E/Fy)``
    in compression and ``0.95 sqrt(kc E/FL)`` in flexure, with ``FL = 0.7 Fy``
    for a doubly symmetric section.
    """
    root = math.sqrt(steel.E / steel.Fy)
    flange_compression = 0.56 * root
    flange_noncompact = 1.0 * root
    if isinstance(shape, BuiltUpIShape):
        kc = shape.kc
        flange_compression = 0.64 * math.sqrt(kc * steel.E / steel.Fy)
        flange_noncompact = 0.95 * math.sqrt(kc * steel.E / (0.7 * steel.Fy))
    return Slenderness(
        flange=shape.flange_ratio,
        web=shape.web_ratio,
        flange_compression_limit=flange_compression,
        web_compression_limit=1.49 * root,
        flange_compact=0.38 * root,
        flange_noncompact=flange_noncompact,
        web_compact=3.76 * root,
        web_noncompact=5.70 * root,
    )


# ──────────────────────────── tension and compression ────────────────────────────
def tension(
    shape: IShape,
    steel: Steel,
    method: Method,
    *,
    net_area: float | None = None,
    shear_lag: float = 1.0,
) -> Strength:
    """D2: yielding in the gross section, and rupture when a net area is given.

    D2-1 is ``Pn = Fy Ag``. D2-2 is ``Pn = Fu Ae`` with ``Ae = U An``; the
    caller supplies the net area and the shear-lag factor, because neither is
    known to a line model. Without them the result is D2-1 only and says so.
    """
    candidates: list[tuple[float, str]] = [(steel.Fy * shape.A, "D2-1 yielding")]
    steps: dict[str, tuple[CalcStep, ...]] = {
        "D2-1 yielding": (
            _step("D2-1 yielding", "Pn = Fy Ag", f"{steel.Fy:g} x {shape.A:g}", steel.Fy * shape.A),
        )
    }
    notes: list[str] = []
    if net_area is None:
        notes.append("Tensile rupture (D2-2) needs the net area and is not checked.")
    elif steel.Fu is None:
        notes.append("Tensile rupture (D2-2) needs Fu and is not checked.")
    else:
        if net_area <= 0.0:
            raise ValueError("net_area must be positive")
        if not 0.0 < shear_lag <= 1.0:
            raise ValueError("shear_lag must be in (0, 1]")
        effective = shear_lag * net_area
        candidates.append((steel.Fu * effective, "D2-2 rupture"))
        steps["D2-2 rupture"] = (
            _step("Effective net area", "Ae = U An", f"{shear_lag:g} x {net_area:g}", effective),
            _step(
                "D2-2 rupture", "Pn = Fu Ae", f"{steel.Fu:g} x {effective:g}", steel.Fu * effective
            ),
        )
        notes.append(f"D2-2 with Ae = U An = {effective:.6g}.")
    nominal, equation = min(candidates)
    return Strength(
        nominal,
        _available(
            nominal, "tension" if equation == "D2-1 yielding" else "tension_rupture", method
        ),
        equation,
        tuple(notes),
        steps[equation],
    )


def _critical_stress(fy: float, fe: float) -> float:
    """E3-2 / E3-3: inelastic or elastic buckling stress."""
    if fy / fe <= 2.25:
        return float(math.pow(0.658, fy / fe)) * fy
    return 0.877 * fe


def _effective_width(
    width: float, ratio: float, limit: float, c1: float, c2: float, fy: float, fcr: float
) -> float:
    """E7-2 / E7-3: effective width of a slender element at the stress ``fcr``."""
    if ratio <= limit * math.sqrt(fy / fcr):
        return width
    fel = (c2 * limit / ratio) ** 2 * fy
    factor = math.sqrt(fel / fcr)
    return min(width, width * (1.0 - c1 * factor) * factor)


def compression(
    shape: IShape,
    steel: Steel,
    method: Method,
    *,
    length_x: float,
    length_y: float,
    length_z: float | None = None,
    k_x: float = 1.0,
    k_y: float = 1.0,
    k_z: float = 1.0,
) -> Strength:
    """E3 flexural and E4 torsional buckling, with the E7 effective area if slender.

    ``length_x`` / ``length_y`` are the unbraced lengths for buckling about the
    major and minor axes, ``length_z`` the torsional one (the minor-axis length
    when not given).
    """
    e, fy = steel.E, steel.Fy
    lcx, lcy = k_x * length_x, k_y * length_y
    lcz = k_z * (length_y if length_z is None else length_z)
    candidates: list[tuple[float, str]] = []
    for lc, r, label in ((lcx, shape.rx, "x"), (lcy, shape.ry, "y")):
        if lc > 0:
            candidates.append((math.pi**2 * e / (lc / r) ** 2, f"E3-4 about {label}"))
    if lcz > 0:
        fe_z = (math.pi**2 * e * shape.Cw / lcz**2 + steel.G * shape.J) / (shape.Ix + shape.Iy)
        candidates.append((fe_z, "E4-2 torsional"))
    if not candidates:
        fe, which = math.inf, "no buckling length"
    else:
        fe, which = min(candidates)
    fcr = fy if math.isinf(fe) else _critical_stress(fy, fe)
    notes: list[str] = []
    area = shape.A
    classes = slenderness(shape, steel)
    equation = f"E3-1 ({which})"
    if classes.slender_in_compression:
        # E7: flange (unstiffened, c1 = 0.22, c2 = 1.49) and web (stiffened, c1 = 0.18,
        # c2 = 1.31) lose their ineffective widths at the buckling stress.
        half_flange = shape.bf / 2.0
        be_flange = _effective_width(
            half_flange,
            classes.flange,
            classes.flange_compression_limit,
            0.22,
            1.49,
            fy,
            fcr,
        )
        he = _effective_width(
            shape.h, classes.web, classes.web_compression_limit, 0.18, 1.31, fy, fcr
        )
        area = shape.A - 4.0 * (half_flange - be_flange) * shape.tf - (shape.h - he) * shape.tw
        if area < shape.A:
            equation = f"E7-1 ({which}, effective area)"
            notes.append(f"Slender element(s): effective area {area / shape.A:.3f} Ag.")
        else:
            notes.append("Slender element(s), fully effective at the buckling stress (E7).")
    nominal = fcr * area
    steps = [
        _step(
            "Elastic buckling",
            "Fe = pi^2 E / (KL/r)^2",
            f"{which}: {fe:.6g}",
            fe,
        ),
        _step(
            "Critical stress",
            "Fcr = 0.658^(Fy/Fe) Fy" if fy / fe <= 2.25 else "Fcr = 0.877 Fe",
            f"{fcr:.6g}",
            fcr,
        ),
    ]
    if area != shape.A:
        steps.insert(1, _step("Effective area", "Ae from E7", f"{area:.6g}", area))
    steps.append(_step("Nominal strength", "Pn = Fcr Ae", f"{fcr:.6g} x {area:.6g}", nominal))
    return Strength(
        nominal,
        _available(nominal, "compression", method),
        equation,
        tuple(notes),
        tuple(steps),
    )


# ──────────────────────────── flexure ────────────────────────────
def lp_lr(shape: IShape, steel: Steel) -> tuple[float, float]:
    """F2-5 and F2-6: the limiting unbraced lengths of lateral-torsional buckling."""
    e, fy = steel.E, steel.Fy
    lp = 1.76 * shape.ry * math.sqrt(e / fy)
    jc = shape.J * shape.c / (shape.Sx * shape.ho)
    lr = (
        1.95
        * shape.rts
        * e
        / (0.7 * fy)
        * math.sqrt(jc + math.sqrt(jc**2 + 6.76 * (0.7 * fy / e) ** 2))
    )
    return lp, lr


def _flexure_major_f4(
    shape: IShape,
    steel: Steel,
    method: Method,
    *,
    unbraced: float,
    cb: float,
    classes: Slenderness,
) -> Strength:
    """F4: a doubly symmetric I-shape with a noncompact web.

    The shape is doubly symmetric, so the compression and tension flanges have
    the same section modulus and ``F_L = 0.7 Fy``. The four limit states of F4
    are compression-flange yielding, lateral-torsional buckling, compression
    flange local buckling and tension-flange yielding.
    """
    e, fy = steel.E, steel.Fy
    sx = shape.Sx
    h = shape.h
    aw = h * shape.tw / (shape.bf * shape.tf)
    rt = shape.bf / math.sqrt(12.0 * (1.0 + aw / 6.0))
    my = fy * sx
    mp = min(fy * shape.Zx, 1.6 * my)
    fl = 0.7 * fy
    jc = shape.J / (sx * shape.ho)
    lp = 1.1 * rt * math.sqrt(e / fy)
    lr = 1.95 * rt * e / fl * math.sqrt(jc + math.sqrt(jc**2 + 6.76 * (fl / e) ** 2))
    ratio = unbraced / rt
    fcr = (
        cb * math.pi**2 * e / ratio**2 * math.sqrt(1.0 + 0.078 * jc * ratio**2)
        if ratio > 0.0
        else 0.0
    )
    mp_my = mp / my
    if classes.web <= classes.web_compact:
        rpc = mp_my
    else:
        rpc = min(
            mp_my
            - (mp_my - 1.0)
            * (classes.web - classes.web_compact)
            / (classes.web_noncompact - classes.web_compact),
            mp_my,
        )
    candidates: list[tuple[float, str]] = [
        (rpc * my, "F4-1 compression flange yielding"),
    ]
    if unbraced <= lp:
        candidates.append((mp, "F4-2 lateral-torsional buckling (Lb <= Lp)"))
    elif unbraced <= lr:
        candidates.append(
            (
                min(
                    cb * (rpc * my - (rpc * my - fl * sx) * (unbraced - lp) / (lr - lp)),
                    mp,
                ),
                "F4-2 inelastic lateral-torsional buckling",
            )
        )
    else:
        candidates.append((min(fcr * sx, mp), "F4-3 elastic lateral-torsional buckling"))
    kc = min(max(4.0 / math.sqrt(h / shape.tw), 0.35), 0.76)
    if classes.flange_class == "compact":
        cflb = mp
    elif classes.flange_class == "noncompact":
        cflb = rpc * my - (rpc * my - fl * sx) * (
            (classes.flange - classes.flange_compact)
            / (classes.flange_noncompact - classes.flange_compact)
        )
    else:
        cflb = 0.9 * e * kc * sx / classes.flange**2
    candidates.append((min(cflb, mp), "F4-13/14 compression flange local buckling"))
    candidates.append((mp, "F4-15 tension flange yielding"))
    nominal, equation = min(candidates)
    steps = (
        _step("Yield moment", "My = Fy Sx", f"{fy:g} x {sx:g}", my),
        _step("Web plastification", "Rpc from F4-9", f"{rpc:.6g}", rpc),
        _step("Plastic moment", "Mp = min(Fy Zx, 1.6 My)", f"{mp:.6g}", mp),
        _step("Lp", "Lp = 1.1 rt sqrt(E/Fy)", f"{lp:.6g}", lp),
        _step("Lr", "Lr from F4-8", f"{lr:.6g}", lr),
        _step("Nominal strength", equation, f"{nominal:.6g}", nominal),
    )
    return Strength(
        nominal,
        _available(nominal, "flexure", method),
        equation,
        ("F4: noncompact web.",),
        steps,
    )


def _flexure_major_f5(
    shape: IShape,
    steel: Steel,
    method: Method,
    *,
    unbraced: float,
    cb: float,
    classes: Slenderness,
) -> Strength:
    """F5: a doubly symmetric I-shape with a slender web.

    ``Rpg`` reduces the bending strength for the slender web; the four limit
    states are compression-flange yielding, lateral-torsional buckling,
    compression-flange local buckling and tension-flange yielding.
    """
    e, fy = steel.E, steel.Fy
    sx = shape.Sx
    h = shape.h
    aw = min(h * shape.tw / (shape.bf * shape.tf), 10.0)
    rt = shape.bf / math.sqrt(12.0 * (1.0 + aw / 6.0))
    rpg = max(
        0.0,
        min(
            1.0,
            1.0 - aw / (1200.0 + 300.0 * aw) * (h / shape.tw - 5.7 * math.sqrt(e / fy)),
        ),
    )
    mp = rpg * fy * sx
    lp = 1.1 * rt * math.sqrt(e / fy)
    lr = math.pi * rt * math.sqrt(e / (0.7 * fy))
    if unbraced <= lp:
        fcr_ltb = fy
    elif unbraced <= lr:
        fcr_ltb = cb * (fy - 0.3 * fy * (unbraced - lp) / (lr - lp))
    else:
        fcr_ltb = cb * math.pi**2 * e / (unbraced / rt) ** 2
    fcr_ltb = min(fcr_ltb, fy)
    kc = min(max(4.0 / math.sqrt(h / shape.tw), 0.35), 0.76)
    if classes.flange_class == "compact":
        fcr_cflb = fy
    elif classes.flange_class == "noncompact":
        fcr_cflb = fy - 0.3 * fy * (
            (classes.flange - classes.flange_compact)
            / (classes.flange_noncompact - classes.flange_compact)
        )
    else:
        fcr_cflb = 0.9 * e * kc / (shape.bf / (2.0 * shape.tf)) ** 2
    candidates: list[tuple[float, str]] = [
        (mp, "F5-1 compression flange yielding"),
        (rpg * fcr_ltb * sx, "F5-2 lateral-torsional buckling"),
        (rpg * fcr_cflb * sx, "F5-7 compression flange local buckling"),
        (fy * sx, "F5-10 tension flange yielding"),
    ]
    nominal, equation = min(candidates)
    steps = (
        _step("Web bending factor", "Rpg from F5-6", f"{rpg:.6g}", rpg),
        _step("Plastic moment", "Mp = Rpg Fy Sx", f"{mp:.6g}", mp),
        _step("Lp", "Lp = 1.1 rt sqrt(E/Fy)", f"{lp:.6g}", lp),
        _step("Lr", "Lr = pi rt sqrt(E/(0.7 Fy))", f"{lr:.6g}", lr),
        _step("Nominal strength", equation, f"{nominal:.6g}", nominal),
    )
    return Strength(
        nominal,
        _available(nominal, "flexure", method),
        equation,
        ("F5: slender web.",),
        steps,
    )


def flexure_major(
    shape: IShape, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
) -> Strength:
    """F2/F3, F4 or F5, by the web classification of the shape."""
    e, fy = steel.E, steel.Fy
    classes = slenderness(shape, steel)
    if classes.web_class == "noncompact":
        return _flexure_major_f4(shape, steel, method, unbraced=unbraced, cb=cb, classes=classes)
    if classes.web_class == "slender":
        return _flexure_major_f5(shape, steel, method, unbraced=unbraced, cb=cb, classes=classes)
    mp = fy * shape.Zx
    steps: dict[str, tuple[CalcStep, ...]] = {
        "F2-1 yielding": (_step("F2-1 yielding", "Mp = Fy Zx", f"{fy:g} x {shape.Zx:g}", mp),)
    }
    notes: list[str] = []
    candidates: list[tuple[float, str]] = [(mp, "F2-1 yielding")]
    lp, lr = lp_lr(shape, steel)
    if unbraced > lp:
        if unbraced <= lr:
            mn = cb * (mp - (mp - 0.7 * fy * shape.Sx) * (unbraced - lp) / (lr - lp))
            candidates.append((min(mn, mp), "F2-2 inelastic LTB"))
            steps["F2-2 inelastic LTB"] = (
                _step("Lp", "Lp = 1.76 ry sqrt(E/Fy)", f"{lp:.6g}", lp),
                _step("Lr", "Lr from F2-6", f"{lr:.6g}", lr),
                _step(
                    "F2-2 inelastic LTB",
                    "Mn = Cb [Mp - (Mp - 0.7 Fy Sx)(Lb - Lp)/(Lr - Lp)]",
                    f"Cb={cb:.4g}, Lb={unbraced:.6g}",
                    mn,
                ),
            )
        else:
            jc = shape.J * shape.c / (shape.Sx * shape.ho)
            ratio = unbraced / shape.rts
            fcr = cb * math.pi**2 * e / ratio**2 * math.sqrt(1.0 + 0.078 * jc * ratio**2)
            candidates.append((min(fcr * shape.Sx, mp), "F2-3 elastic LTB"))
            steps["F2-3 elastic LTB"] = (
                _step("Lp", "Lp = 1.76 ry sqrt(E/Fy)", f"{lp:.6g}", lp),
                _step("Lr", "Lr from F2-6", f"{lr:.6g}", lr),
                _step("Fcr", "Fcr from F2-4", f"{fcr:.6g}", fcr),
                _step(
                    "F2-3 elastic LTB",
                    "Mn = Fcr Sx <= Mp",
                    f"{fcr:.6g} x {shape.Sx:g}",
                    fcr * shape.Sx,
                ),
            )
    if classes.flange_class == "noncompact":
        mn = mp - (mp - 0.7 * fy * shape.Sx) * (
            (classes.flange - classes.flange_compact)
            / (classes.flange_noncompact - classes.flange_compact)
        )
        candidates.append((mn, "F3-1 flange local buckling"))
        steps["F3-1 flange local buckling"] = (
            _step("F3-1", "Mn by flange slenderness interpolation", f"{mn:.6g}", mn),
        )
    elif classes.flange_class == "slender":
        kc = min(max(4.0 / math.sqrt(classes.web), 0.35), 0.76)
        mn = 0.9 * e * kc * shape.Sx / classes.flange**2
        candidates.append((mn, "F3-2 flange local buckling"))
        steps["F3-2 flange local buckling"] = (
            _step("F3-2", "Mn = 0.9 E kc Sx / (b/t)^2", f"{mn:.6g}", mn),
        )
    nominal, equation = min(candidates)
    return Strength(
        nominal,
        _available(nominal, "flexure", method),
        equation,
        tuple(notes),
        steps[equation],
    )


def flexure_minor(shape: IShape, steel: Steel, method: Method) -> Strength:
    """F6: yielding and flange local buckling about the minor axis."""
    e, fy = steel.E, steel.Fy
    mp = min(fy * shape.Zy, 1.6 * fy * shape.Sy)
    steps: dict[str, tuple[CalcStep, ...]] = {
        "F6-1 yielding": (_step("F6-1 yielding", "Mn = min(Fy Zy, 1.6 Fy Sy)", f"{mp:.6g}", mp),)
    }
    classes = slenderness(shape, steel)
    candidates: list[tuple[float, str]] = [(mp, "F6-1 yielding")]
    if classes.flange_class == "noncompact":
        mn = mp - (mp - 0.7 * fy * shape.Sy) * (
            (classes.flange - classes.flange_compact)
            / (classes.flange_noncompact - classes.flange_compact)
        )
        candidates.append((mn, "F6-2 flange local buckling"))
        steps["F6-2 flange local buckling"] = (
            _step("F6-2", "Mn by flange slenderness interpolation", f"{mn:.6g}", mn),
        )
    elif classes.flange_class == "slender":
        fcr = 0.69 * e / classes.flange**2
        candidates.append((fcr * shape.Sy, "F6-3 flange local buckling"))
        steps["F6-3 flange local buckling"] = (
            _step("F6-3", "Mn = 0.69 E Sy / (b/t)^2", f"{fcr * shape.Sy:.6g}", fcr * shape.Sy),
        )
    nominal, equation = min(candidates)
    return Strength(
        nominal,
        _available(nominal, "flexure", method),
        equation,
        (),
        steps[equation],
    )


# ──────────────────────────── shear ────────────────────────────
def shear_major(shape: IShape, steel: Steel, method: Method) -> Strength:
    """G2.1: shear along the web, ``Vn = 0.6 Fy Aw Cv1`` with ``Aw = d tw``.

    A rolled shape with ``h/tw <= 2.24 sqrt(E/Fy)`` takes ``Cv1 = 1`` and
    ``phi = 1.0`` (G2.1(a)). Otherwise, and always for a built-up shape,
    ``Cv1`` comes from ``kv``: 5.34 without stiffeners or with ``a/h > 3``,
    ``5 + 5 / (a/h)^2`` with transverse stiffeners at ``a`` (G2-5). Tension
    field action (G2.2) is not counted, which is conservative.
    """
    e, fy = steel.E, steel.Fy
    ratio = shape.web_ratio
    aw = shape.d * shape.tw
    built_up = isinstance(shape, BuiltUpIShape)
    if not built_up and ratio <= 2.24 * math.sqrt(e / fy):
        nominal = 0.6 * fy * aw
        return Strength(
            nominal,
            _available(nominal, "shear_rolled", method),
            "G2-1 (Cv1 = 1)",
            (),
            (
                _step("Web area", "Aw = d tw", f"{shape.d:g} x {shape.tw:g}", aw),
                _step("G2-1", "Vn = 0.6 Fy Aw Cv1 (Cv1 = 1)", f"{nominal:.6g}", nominal),
            ),
        )
    kv = 5.34  # webs without transverse stiffeners
    notes: list[str] = []
    spacing = shape.stiffener_spacing if built_up else None  # type: ignore[attr-defined]
    if spacing is not None and spacing / shape.h <= 3.0:
        kv = 5.0 + 5.0 / (spacing / shape.h) ** 2
        # F13.2: the web's proportion limit with stiffeners.
        cap = 12.0 * math.sqrt(e / fy) if spacing / shape.h <= 1.5 else 0.40 * e / fy
        if ratio > cap:
            notes.append(f"h/tw = {ratio:.4g} exceeds the F13.2 limit {cap:.4g}.")
    elif built_up and ratio > 260.0:
        notes.append("h/tw > 260: G2.1 requires transverse stiffeners.")
    limit = 1.10 * math.sqrt(kv * e / fy)
    cv1 = 1.0 if ratio <= limit else limit / ratio
    nominal = 0.6 * fy * aw * cv1
    return Strength(
        nominal,
        _available(nominal, "shear", method),
        f"G2-1 (Cv1 = {cv1:.3f}, kv = {kv:.3g})",
        tuple(notes),
        (
            _step("Web area", "Aw = d tw", f"{shape.d:g} x {shape.tw:g}", aw),
            _step("Slenderness", "h/tw", f"{ratio:.6g}", ratio),
            _step("Web plate buckling coefficient", "kv from G2-5", f"{kv:.6g}", kv),
            _step("Shear coefficient", "Cv1 from G2-3/G2-4", f"{cv1:.6g}", cv1),
            _step("G2-1", "Vn = 0.6 Fy Aw Cv1", f"{nominal:.6g}", nominal),
        ),
    )


def shear_minor(shape: IShape, steel: Steel, method: Method) -> Strength:
    """G6: shear along the flanges, ``Vn = 0.6 Fy bf tf Cv2`` for each of the two flanges."""
    e, fy = steel.E, steel.Fy
    ratio = shape.flange_ratio
    kv = 1.2
    limit = 1.10 * math.sqrt(kv * e / fy)
    if ratio <= limit:
        cv2 = 1.0
    elif ratio <= 1.37 * math.sqrt(kv * e / fy):
        cv2 = limit / ratio
    else:
        cv2 = 1.51 * kv * e / (ratio**2 * fy)
    nominal = 0.6 * fy * (2.0 * shape.bf * shape.tf) * cv2
    return Strength(
        nominal,
        _available(nominal, "shear", method),
        f"G6-1 (Cv2 = {cv2:.3f})",
        (),
        (
            _step(
                "Flange area",
                "Aw = 2 bf tf",
                f"{2.0 * shape.bf * shape.tf:.6g}",
                2.0 * shape.bf * shape.tf,
            ),
            _step("Slenderness", "bf/2tf", f"{ratio:.6g}", ratio),
            _step("Shear coefficient", "Cv2 from G6-2 to G6-4", f"{cv2:.6g}", cv2),
            _step("G6-1", "Vn = 0.6 Fy Aw Cv2", f"{nominal:.6g}", nominal),
        ),
    )


# ──────────────────────────── interaction ────────────────────────────
def interaction(
    pr: float, pc: float, mrx: float, mcx: float, mry: float, mcy: float
) -> tuple[float, str]:
    """H1-1a / H1-1b: the combined ratio of axial force and biaxial flexure."""
    p = abs(pr) / pc if pc > 0 else math.inf
    m = (abs(mrx) / mcx if mcx > 0 else 0.0) + (abs(mry) / mcy if mcy > 0 else 0.0)
    if p >= 0.2:
        return p + 8.0 / 9.0 * m, "H1-1a"
    return p / 2.0 + m, "H1-1b"


def cb_from_moments(m_max: float, m_a: float, m_b: float, m_c: float) -> float:
    """F1-1: ``Cb = 12.5 Mmax / (2.5 Mmax + 3 MA + 4 MB + 3 MC)`` (absolute values)."""
    m_max, m_a, m_b, m_c = (abs(v) for v in (m_max, m_a, m_b, m_c))
    denominator = 2.5 * m_max + 3.0 * m_a + 4.0 * m_b + 3.0 * m_c
    if m_max <= 0.0 or denominator <= 0.0:
        return 1.0
    return 12.5 * m_max / denominator


# ──────────────────────────── a member check ────────────────────────────
class SteelShape(Protocol):
    """A shape the check covers: its properties and the limit states of its family.

    ``flexure_major`` is bending about the axis of the larger moment of inertia
    (``Ix``), ``shear_major`` the shear that goes with it; the ``minor`` pair is
    the other axis. Lengths are the member's unbraced lengths.
    """

    @property
    def name(self) -> str:
        """The AISC name of the shape."""

    @property
    def A(self) -> float:
        """Gross area."""

    @property
    def Ix(self) -> float:
        """Moment of inertia about the major axis."""

    @property
    def Iy(self) -> float:
        """Moment of inertia about the minor axis."""

    def tension(self, steel: Steel, method: Method) -> Strength:
        """Available tensile strength (D2)."""

    def compression(
        self,
        steel: Steel,
        method: Method,
        *,
        length_x: float,
        length_y: float,
        k_x: float = 1.0,
        k_y: float = 1.0,
    ) -> Strength:
        """Available compressive strength (E3 to E7) for the unbraced lengths and K."""

    def flexure_major(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        """Available flexural strength about the major axis (chapter F)."""

    def flexure_minor(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        """Available flexural strength about the minor axis (chapter F)."""

    def shear_major(self, steel: Steel, method: Method, *, length: float) -> Strength:
        """Available shear strength along the major-axis shear direction (chapter G)."""

    def shear_minor(self, steel: Steel, method: Method, *, length: float) -> Strength:
        """Available shear strength along the minor-axis shear direction (chapter G)."""


@dataclass(frozen=True)
class Demand:
    """Required strengths of one load set: axial (tension +), moments and shears."""

    axial: float
    moment_major: float
    moment_minor: float
    shear_major: float
    shear_minor: float
    cb: float = 1.0


@dataclass
class MemberCheck:
    """Every ratio of one member under one load set, and the governing one."""

    ratios: dict[str, float] = field(default_factory=dict)
    equations: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    checks: list[LimitStateCheck] = field(default_factory=list)

    @property
    def governing(self) -> tuple[str, float]:
        if not self.ratios:
            return ("", 0.0)
        key = max(self.ratios, key=lambda k: self.ratios[k])
        return key, self.ratios[key]


def _record(check: MemberCheck, name: str, strength: Strength, demand: float) -> None:
    """Keep one limit state with its nominal and available strengths."""
    capacity = strength.available
    ratio = abs(demand) / capacity if capacity > 0.0 else math.inf
    steps = list(strength.steps)
    if not steps:
        steps.append(
            CalcStep(
                "Nominal strength",
                strength.equation,
                f"{strength.nominal:.6g}",
                strength.nominal,
            )
        )
    steps.append(
        CalcStep(
            "Available strength",
            "phi Rn (LRFD) / Rn / Omega (ASD)",
            f"{capacity:.6g}",
            capacity,
        )
    )
    check.checks.append(
        LimitStateCheck(
            name, strength.equation, abs(demand), capacity, ratio, tuple(steps), strength.notes
        )
    )


def check_member(
    shape: SteelShape,
    steel: Steel,
    method: Method,
    demand: Demand,
    *,
    length_x: float,
    length_y: float,
    length_ltb: float,
    k_x: float = 1.0,
    k_y: float = 1.0,
    net_area: float | None = None,
    shear_lag: float = 1.0,
    p_delta: bool = False,
) -> MemberCheck:
    """Ratios of axial, flexure, shear and H1 interaction for one demand.

    With ``p_delta``, a member in compression gets its moments amplified by
    ``B1`` of AISC 360-16 C2.1b (A-8-3 in the 2022 edition): the analysis is
    assumed to capture P-Delta but not the member's own curvature (P-delta).
    ``Pe1`` uses ``EI* = 0.8 tau_b EI`` (C2.3), so the amplifier follows the
    direct analysis method; it is conservative for the effective length method.
    """
    check = MemberCheck()
    mrx = demand.moment_major
    mry = demand.moment_minor
    if p_delta and demand.axial < 0.0:
        alpha = 1.0 if method == "LRFD" else 1.6
        rigidity = 0.8 * tau_b(-demand.axial, steel.Fy * shape.A, alpha=alpha) * steel.E
        b_major = b1(-demand.axial, pe1(rigidity, shape.Ix, length_x, k=k_x), alpha=alpha)
        b_minor = b1(-demand.axial, pe1(rigidity, shape.Iy, length_y, k=k_y), alpha=alpha)
        mrx *= b_major
        mry *= b_minor
        check.notes.append(
            f"P-delta (C2.1b): B1 = {b_major:.3f} major, {b_minor:.3f} minor, Pe1 on 0.8 tau_b EI."
        )
    if demand.axial >= 0.0:
        axial = shape.tension(steel, method)
        if net_area is not None:
            base_notes = tuple(note for note in axial.notes if "Tensile rupture" not in note)
            if steel.Fu is None:
                axial = Strength(
                    axial.nominal,
                    axial.available,
                    axial.equation,
                    (*base_notes, "Tensile rupture (D2-2) needs Fu and is not checked."),
                )
            else:
                if net_area <= 0.0:
                    raise ValueError("net_area must be positive")
                if not 0.0 < shear_lag <= 1.0:
                    raise ValueError("shear_lag must be in (0, 1]")
                effective = shear_lag * net_area
                rupture = Strength(
                    steel.Fu * effective,
                    _available(steel.Fu * effective, "tension_rupture", method),
                    "D2-2 rupture",
                    (f"D2-2 with Ae = U An = {effective:.6g}.",),
                )
                if rupture.available < axial.available:
                    axial = rupture
                else:
                    axial = Strength(
                        axial.nominal,
                        axial.available,
                        axial.equation,
                        (
                            *base_notes,
                            f"D2-2 with Ae = U An = {effective:.6g} does not govern.",
                        ),
                    )
        label = "Tension"
    else:
        axial = shape.compression(
            steel, method, length_x=length_x, length_y=length_y, k_x=k_x, k_y=k_y
        )
        label = "Compression"
    major = shape.flexure_major(steel, method, unbraced=length_ltb, cb=demand.cb)
    minor = shape.flexure_minor(steel, method, unbraced=length_ltb, cb=demand.cb)
    length = max(length_x, length_y)
    v_major = shape.shear_major(steel, method, length=length)
    v_minor = shape.shear_minor(steel, method, length=length)
    check.ratios[label] = abs(demand.axial) / axial.available
    check.equations[label] = axial.equation
    check.ratios["Major flexure"] = abs(mrx) / major.available
    check.equations["Major flexure"] = major.equation
    check.ratios["Minor flexure"] = abs(mry) / minor.available
    check.equations["Minor flexure"] = minor.equation
    check.ratios["Major shear"] = abs(demand.shear_major) / v_major.available
    check.equations["Major shear"] = v_major.equation
    check.ratios["Minor shear"] = abs(demand.shear_minor) / v_minor.available
    check.equations["Minor shear"] = v_minor.equation
    ratio, equation = interaction(
        demand.axial,
        axial.available,
        mrx,
        major.available,
        mry,
        minor.available,
    )
    check.ratios["P-M interaction"] = ratio
    check.equations["P-M interaction"] = equation
    p = abs(demand.axial) / axial.available if axial.available > 0 else math.inf
    m = (abs(mrx) / major.available if major.available > 0 else 0.0) + (
        abs(mry) / minor.available if minor.available > 0 else 0.0
    )
    check.checks.append(
        LimitStateCheck(
            "P-M interaction",
            equation,
            ratio,
            1.0,
            ratio,
            (
                _step("Axial ratio", "p = Pr / Pc", f"{p:.6g}", p),
                _step("Moment ratio", "m = Mrx/Mcx + Mry/Mcy", f"{m:.6g}", m),
                _step("Interaction", equation, f"{ratio:.6g}", ratio),
            ),
        )
    )
    for strength, name, value in (
        (axial, label, demand.axial),
        (major, "Major flexure", mrx),
        (minor, "Minor flexure", mry),
        (v_major, "Major shear", demand.shear_major),
        (v_minor, "Minor shear", demand.shear_minor),
    ):
        _record(check, name, strength, value)
    for strength in (axial, major, minor, v_major, v_minor):
        check.notes.extend(strength.notes)
    return check
