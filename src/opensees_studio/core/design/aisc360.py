"""AISC 360-16 available strengths of steel members.

The equations of *Specification for Structural Steel Buildings* (ANSI/AISC
360-16) a frame check needs. This module holds the doubly symmetric I-shapes
(W, M, S and HP families), the common pieces (factors, buckling stress,
effective width, interaction) and :func:`check_member`, which works on any
shape following :class:`SteelShape`; channels, tees, angles and HSS are in
:mod:`core.design.aisc360_shapes`. For the I-shapes:

* **D2** tension, yielding of the gross section (rupture needs the net area,
  which a model does not know, and is left to the engineer);
* **E3 / E4 / E7** compression: flexural buckling about both axes, torsional
  buckling (E4, doubly symmetric), with the effective area of slender
  elements (E7);
* **F2 / F3** major-axis flexure: yielding, lateral-torsional buckling with
  ``Cb``, and flange local buckling of a noncompact or slender flange (a
  compact web is assumed, as for every rolled shape at ``Fy`` up to 65 ksi;
  a noncompact web is reported as not covered);
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

Method = Literal["LRFD", "ASD"]

#: Families checked with the doubly symmetric I-shape provisions.
I_SHAPE_FAMILIES = frozenset({"W", "M", "S", "HP"})

#: Resistance factor φ and safety factor Ω per limit state (AISC 360-16).
FACTORS: dict[str, tuple[float, float]] = {
    "tension": (0.90, 1.67),
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
class Steel:
    """Material of the check: yield stress, Young's and shear moduli."""

    Fy: float
    E: float
    G: float


@dataclass(frozen=True)
class Strength:
    """One available strength: the nominal value, the factor and the governing equation."""

    nominal: float
    available: float
    equation: str
    notes: tuple[str, ...] = ()


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
    """Table B4.1a (compression, cases 1 and 5) and B4.1b (flexure, cases 10 and 15)."""
    root = math.sqrt(steel.E / steel.Fy)
    return Slenderness(
        flange=shape.flange_ratio,
        web=shape.web_ratio,
        flange_compression_limit=0.56 * root,
        web_compression_limit=1.49 * root,
        flange_compact=0.38 * root,
        flange_noncompact=1.0 * root,
        web_compact=3.76 * root,
        web_noncompact=5.70 * root,
    )


# ──────────────────────────── tension and compression ────────────────────────────
def tension(shape: IShape, steel: Steel, method: Method) -> Strength:
    """D2(a): yielding in the gross section, ``Pn = Fy Ag``."""
    nominal = steel.Fy * shape.A
    return Strength(
        nominal,
        _available(nominal, "tension", method),
        "D2-1",
        ("Tensile rupture (D2-2) needs the net area and is not checked.",),
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
    return Strength(nominal, _available(nominal, "compression", method), equation, tuple(notes))


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


def flexure_major(
    shape: IShape, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
) -> Strength:
    """F2 (yielding, lateral-torsional buckling) and F3 (flange local buckling)."""
    e, fy = steel.E, steel.Fy
    mp = fy * shape.Zx
    classes = slenderness(shape, steel)
    notes: list[str] = []
    if classes.web_class != "compact":
        notes.append(
            f"Noncompact or slender web (h/tw = {classes.web:.1f}): F4/F5 not covered, F2 used."
        )
    candidates: list[tuple[float, str]] = [(mp, "F2-1 yielding")]
    lp, lr = lp_lr(shape, steel)
    if unbraced > lp:
        if unbraced <= lr:
            mn = cb * (mp - (mp - 0.7 * fy * shape.Sx) * (unbraced - lp) / (lr - lp))
            candidates.append((min(mn, mp), "F2-2 inelastic LTB"))
        else:
            jc = shape.J * shape.c / (shape.Sx * shape.ho)
            ratio = unbraced / shape.rts
            fcr = cb * math.pi**2 * e / ratio**2 * math.sqrt(1.0 + 0.078 * jc * ratio**2)
            candidates.append((min(fcr * shape.Sx, mp), "F2-3 elastic LTB"))
    if classes.flange_class == "noncompact":
        mn = mp - (mp - 0.7 * fy * shape.Sx) * (
            (classes.flange - classes.flange_compact)
            / (classes.flange_noncompact - classes.flange_compact)
        )
        candidates.append((mn, "F3-1 flange local buckling"))
    elif classes.flange_class == "slender":
        kc = min(max(4.0 / math.sqrt(classes.web), 0.35), 0.76)
        mn = 0.9 * e * kc * shape.Sx / classes.flange**2
        candidates.append((mn, "F3-2 flange local buckling"))
    nominal, equation = min(candidates)
    return Strength(nominal, _available(nominal, "flexure", method), equation, tuple(notes))


def flexure_minor(shape: IShape, steel: Steel, method: Method) -> Strength:
    """F6: yielding and flange local buckling about the minor axis."""
    e, fy = steel.E, steel.Fy
    mp = min(fy * shape.Zy, 1.6 * fy * shape.Sy)
    classes = slenderness(shape, steel)
    candidates: list[tuple[float, str]] = [(mp, "F6-1 yielding")]
    if classes.flange_class == "noncompact":
        mn = mp - (mp - 0.7 * fy * shape.Sy) * (
            (classes.flange - classes.flange_compact)
            / (classes.flange_noncompact - classes.flange_compact)
        )
        candidates.append((mn, "F6-2 flange local buckling"))
    elif classes.flange_class == "slender":
        fcr = 0.69 * e / classes.flange**2
        candidates.append((fcr * shape.Sy, "F6-3 flange local buckling"))
    nominal, equation = min(candidates)
    return Strength(nominal, _available(nominal, "flexure", method), equation)


# ──────────────────────────── shear ────────────────────────────
def shear_major(shape: IShape, steel: Steel, method: Method) -> Strength:
    """G2.1: shear along the web, ``Vn = 0.6 Fy Aw Cv1`` with ``Aw = d tw``."""
    e, fy = steel.E, steel.Fy
    ratio = shape.web_ratio
    aw = shape.d * shape.tw
    if ratio <= 2.24 * math.sqrt(e / fy):
        nominal = 0.6 * fy * aw
        return Strength(nominal, _available(nominal, "shear_rolled", method), "G2-1 (Cv1 = 1)")
    kv = 5.34  # webs without transverse stiffeners
    limit = 1.10 * math.sqrt(kv * e / fy)
    cv1 = 1.0 if ratio <= limit else limit / ratio
    nominal = 0.6 * fy * aw * cv1
    return Strength(nominal, _available(nominal, "shear", method), f"G2-1 (Cv1 = {cv1:.3f})")


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
    return Strength(nominal, _available(nominal, "shear", method), f"G6-1 (Cv2 = {cv2:.3f})")


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

    @property
    def governing(self) -> tuple[str, float]:
        if not self.ratios:
            return ("", 0.0)
        key = max(self.ratios, key=lambda k: self.ratios[k])
        return key, self.ratios[key]


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
) -> MemberCheck:
    """Ratios of axial, flexure, shear and H1 interaction for one demand."""
    check = MemberCheck()
    if demand.axial >= 0.0:
        axial = shape.tension(steel, method)
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
    check.ratios["Major flexure"] = abs(demand.moment_major) / major.available
    check.equations["Major flexure"] = major.equation
    check.ratios["Minor flexure"] = abs(demand.moment_minor) / minor.available
    check.equations["Minor flexure"] = minor.equation
    check.ratios["Major shear"] = abs(demand.shear_major) / v_major.available
    check.equations["Major shear"] = v_major.equation
    check.ratios["Minor shear"] = abs(demand.shear_minor) / v_minor.available
    check.equations["Minor shear"] = v_minor.equation
    ratio, equation = interaction(
        demand.axial,
        axial.available,
        demand.moment_major,
        major.available,
        demand.moment_minor,
        minor.available,
    )
    check.ratios["P-M interaction"] = ratio
    check.equations["P-M interaction"] = equation
    for strength in (axial, major, minor, v_major, v_minor):
        check.notes.extend(strength.notes)
    return check
