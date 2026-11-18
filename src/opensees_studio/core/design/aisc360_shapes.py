"""AISC 360-16 available strengths of channels, tees, angles and HSS.

Each class carries the properties of one family, in one consistent unit system
(the caller scales the AISC table once), and the limit states that apply to it,
so :func:`core.design.aisc360.check_member` works on any of them:

* :class:`Channel` (C, MC): E3, E4 flexural-torsional buckling about the axis of
  symmetry, E7; F2 with ``c`` from F2-8b; F6 about the minor axis; G2.1(b) along
  the web and G6 along the flanges (full flange width).
* :class:`Tee` (WT, MT, ST): E3, E4 flexural-torsional buckling, E7 with the stem
  as an unstiffened element; F9 (yielding, lateral-torsional buckling, flange and
  stem local buckling); G2.1(b) along the stem with ``kv = 1.2``. The demand's
  sign is not known, so the major-axis strength is the smaller of the stem in
  tension and the stem in compression.
* :class:`EqualLegAngle` (L with equal legs): E3 about the minor principal axis,
  E4 flexural-torsional buckling about the axis of symmetry, E7; F10 about the
  geometric axes without lateral-torsional restraint (``My`` and ``Sc`` at 0.8 of
  the geometric values, the toe in compression); G3.
* :class:`RectHSS` (rectangular and square HSS): E3, E7 with the walls as
  stiffened elements; F7 (yielding, flange and web local buckling with the
  effective section modulus of F7-3, lateral-torsional buckling); G4.
* :class:`RoundHSS` (round HSS and pipes): E3, E7 (E7-6); F8; G5 with ``Lv``
  half the member length.

HSS and pipe walls are checked with the design thickness ``t = 0.93 tnom``
(B4.2); the tabulated area and moduli already use it. The flat widths of
rectangular walls are ``B - 3t`` and ``H - 3t`` (B4.1b(d)). Torsion is not
checked. Geometric quantities the table does not carry come from it where they
can (the centroid of a channel is ``bf - Iy / Sy``, of a tee ``d - Ix / Sx``) and
otherwise from the plate dimensions, fillets left out: the shear centre of a
channel (a little farther from the web than the published one, which lowers the
E4 stress) and the principal axes of an angle.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from opensees_studio.core.design.aisc360 import (
    Method,
    Steel,
    Strength,
    _available,
    _critical_stress,
    _effective_width,
    flexure_major,
    flexure_minor,
    tension,
)

#: Families with a class here (the AISC table's family codes).
CHANNEL_FAMILIES = frozenset({"C", "MC"})
TEE_FAMILIES = frozenset({"WT", "MT", "ST"})
ANGLE_FAMILIES = frozenset({"L"})
RECT_HSS_FAMILIES = frozenset({"HSS"})
ROUND_HSS_FAMILIES = frozenset({"HSS_R", "PIPE"})

#: Design wall thickness over the nominal one for HSS and pipe (B4.2).
HSS_DESIGN_THICKNESS = 0.93


def _flexural_buckling(
    e: float, candidates: list[tuple[float, float, str]]
) -> tuple[float, str] | None:
    """The lowest E3-4 stress of ``(Lc, r, label)`` with a positive length."""
    out = [
        (math.pi**2 * e / (lc / r) ** 2, f"E3-4 about {label}")
        for lc, r, label in candidates
        if lc > 0
    ]
    return min(out) if out else None


def _flexural_torsional(f_axis: float, f_z: float, h: float) -> float:
    """E4-5 (singly symmetric): ``Fe`` from the buckling stress about the axis of symmetry."""
    total = f_axis + f_z
    return total / (2.0 * h) * (1.0 - math.sqrt(max(0.0, 1.0 - 4.0 * f_axis * f_z * h / total**2)))


def _cv2(ratio: float, kv: float, e: float, fy: float) -> float:
    """G2-9 to G2-11: web shear buckling coefficient ``Cv2``."""
    limit = 1.10 * math.sqrt(kv * e / fy)
    if ratio <= limit:
        return 1.0
    if ratio <= 1.37 * math.sqrt(kv * e / fy):
        return limit / ratio
    return 1.51 * kv * e / (ratio**2 * fy)


def _compression_strength(
    fy: float, fe: float | None, which: str, area: float, effective: float, method: Method
) -> Strength:
    fcr = fy if fe is None or math.isinf(fe) else _critical_stress(fy, fe)
    notes: tuple[str, ...] = ()
    equation = f"E3-1 ({which})"
    if effective < area:
        equation = f"E7-1 ({which}, effective area)"
        notes = (f"Slender element(s): effective area {effective / area:.3f} Ag.",)
    nominal = fcr * effective
    return Strength(nominal, _available(nominal, "compression", method), equation, notes)


# ──────────────────────────── channels ────────────────────────────
@dataclass(frozen=True)
class Channel:
    """A channel (C, MC): symmetric about its major axis ``x``."""

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
        return self.d - 2.0 * self.tf

    @property
    def ho(self) -> float:
        return self.d - self.tf

    @property
    def rts(self) -> float:
        return math.sqrt(math.sqrt(self.Iy * self.Cw) / self.Sx)

    @property
    def c(self) -> float:
        """F2-8b: ``c = (ho / 2) sqrt(Iy / Cw)``."""
        return self.ho / 2.0 * math.sqrt(self.Iy / self.Cw)

    @property
    def flange_ratio(self) -> float:
        """``b / t`` of a channel flange: the full flange width (B4.1)."""
        return self.bf / self.tf

    @property
    def web_ratio(self) -> float:
        return self.h / self.tw

    @property
    def xo(self) -> float:
        """Distance between the centroid and the shear centre, along ``x`` (the flanges)."""
        x_bar = self.bf - self.Iy / self.Sy  # Sy is taken to the flange tips
        b_prime = self.bf - self.tw / 2.0
        e_o = 3.0 * self.tf * b_prime**2 / (6.0 * b_prime * self.tf + self.ho * self.tw)
        return x_bar - self.tw / 2.0 + e_o

    def tension(self, steel: Steel, method: Method) -> Strength:
        return tension(self, steel, method)  # type: ignore[arg-type]

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
        e, fy = steel.E, steel.Fy
        lcx, lcy = k_x * length_x, k_y * length_y
        found = _flexural_buckling(e, [(lcx, self.rx, "x"), (lcy, self.ry, "y")])
        fe, which = found if found is not None else (math.inf, "no buckling length")
        if lcx > 0 and lcy > 0:
            ro2 = self.xo**2 + (self.Ix + self.Iy) / self.A
            h = 1.0 - self.xo**2 / ro2
            fex = math.pi**2 * e / (lcx / self.rx) ** 2
            fez = (math.pi**2 * e * self.Cw / lcy**2 + steel.G * self.J) / (self.A * ro2)
            ftb = _flexural_torsional(fex, fez, h)
            if ftb < fe:
                fe, which = ftb, "E4-5 flexural-torsional"
        fcr = fy if math.isinf(fe) else _critical_stress(fy, fe)
        root = math.sqrt(e / fy)
        b_e = _effective_width(self.bf, self.flange_ratio, 0.56 * root, 0.22, 1.49, fy, fcr)
        h_e = _effective_width(self.h, self.web_ratio, 1.49 * root, 0.18, 1.31, fy, fcr)
        effective = self.A - 2.0 * (self.bf - b_e) * self.tf - (self.h - h_e) * self.tw
        return _compression_strength(fy, fe, which, self.A, effective, method)

    def flexure_major(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        strength = flexure_major(self, steel, method, unbraced=unbraced, cb=cb)  # type: ignore[arg-type]
        if strength.equation.startswith("F3"):
            note = "F3 flange local buckling applied to a channel flange."
            return Strength(
                strength.nominal, strength.available, strength.equation, (*strength.notes, note)
            )
        return strength

    def flexure_minor(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return flexure_minor(self, steel, method)  # type: ignore[arg-type]

    def shear_major(self, steel: Steel, method: Method, *, length: float) -> Strength:
        """G2.1(b): ``Vn = 0.6 Fy d tw Cv1`` with ``kv = 5.34``."""
        e, fy = steel.E, steel.Fy
        limit = 1.10 * math.sqrt(5.34 * e / fy)
        cv1 = 1.0 if self.web_ratio <= limit else limit / self.web_ratio
        nominal = 0.6 * fy * self.d * self.tw * cv1
        return Strength(nominal, _available(nominal, "shear", method), f"G2-1 (Cv1 = {cv1:.3f})")

    def shear_minor(self, steel: Steel, method: Method, *, length: float) -> Strength:
        """G6 with the full flange width, both flanges."""
        cv2 = _cv2(self.flange_ratio, 1.2, steel.E, steel.Fy)
        nominal = 0.6 * steel.Fy * 2.0 * self.bf * self.tf * cv2
        return Strength(nominal, _available(nominal, "shear", method), f"G6-1 (Cv2 = {cv2:.3f})")


# ──────────────────────────── tees ────────────────────────────
@dataclass(frozen=True)
class Tee:
    """A structural tee (WT, MT, ST): flange on top, stem down, symmetric about ``y``."""

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
    def y_bar(self) -> float:
        """Centroid from the outer face of the flange (``Sx`` is taken to the stem tip)."""
        return self.d - self.Ix / self.Sx

    @property
    def Sxc(self) -> float:
        """Elastic section modulus to the flange tip."""
        return self.Ix / self.y_bar

    @property
    def flange_ratio(self) -> float:
        return self.bf / (2.0 * self.tf)

    @property
    def stem_ratio(self) -> float:
        return self.d / self.tw

    def tension(self, steel: Steel, method: Method) -> Strength:
        return tension(self, steel, method)  # type: ignore[arg-type]

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
        e, fy = steel.E, steel.Fy
        lcx, lcy = k_x * length_x, k_y * length_y
        found = _flexural_buckling(e, [(lcx, self.rx, "x"), (lcy, self.ry, "y")])
        fe, which = found if found is not None else (math.inf, "no buckling length")
        if lcy > 0:
            yo = self.y_bar - self.tf / 2.0
            ro2 = yo**2 + (self.Ix + self.Iy) / self.A
            h = 1.0 - yo**2 / ro2
            fey = math.pi**2 * e / (lcy / self.ry) ** 2
            fez = (math.pi**2 * e * self.Cw / lcy**2 + steel.G * self.J) / (self.A * ro2)
            ftb = _flexural_torsional(fey, fez, h)
            if ftb < fe:
                fe, which = ftb, "E4-5 flexural-torsional"
        fcr = fy if math.isinf(fe) else _critical_stress(fy, fe)
        root = math.sqrt(e / fy)
        half = self.bf / 2.0
        b_e = _effective_width(half, self.flange_ratio, 0.56 * root, 0.22, 1.49, fy, fcr)
        d_e = _effective_width(self.d, self.stem_ratio, 0.75 * root, 0.22, 1.49, fy, fcr)
        effective = self.A - 2.0 * (half - b_e) * self.tf - (self.d - d_e) * self.tw
        return _compression_strength(fy, fe, which, self.A, effective, method)

    def _mcr(self, e: float, unbraced: float, sign: float) -> float:
        """F9-10 with ``B`` of F9-11 (stem in tension, ``sign = 1``) or F9-12 (``-1``)."""
        b = sign * 2.3 * (self.d / unbraced) * math.sqrt(self.Iy / self.J)
        return 1.95 * e / unbraced * math.sqrt(self.Iy * self.J) * (b + math.sqrt(1.0 + b * b))

    def flexure_major(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        """F9, the smaller of the stem in tension and the stem in compression."""
        e, fy = steel.E, steel.Fy
        my = fy * self.Sx
        root = math.sqrt(e / fy)
        # Stem in tension: yielding, LTB, flange local buckling.
        tension_side: list[tuple[float, str]] = [(min(fy * self.Zx, 1.6 * my), "F9-2 yielding")]
        if unbraced > 0:
            lp = 1.76 * self.ry * root
            lr = (
                1.95
                * (e / fy)
                * math.sqrt(self.Iy * self.J)
                / self.Sx
                * math.sqrt(2.36 * (fy / e) * self.d * self.Sx / self.J + 1.0)
            )
            mp = tension_side[0][0]
            if lp < unbraced <= lr:
                mn = mp - (mp - my) * (unbraced - lp) / (lr - lp)
                tension_side.append((mn, "F9-6 LTB, stem in tension"))
            elif unbraced > lr:
                tension_side.append((self._mcr(e, unbraced, 1.0), "F9-7 LTB, stem in tension"))
        lam, lpf, lrf = self.flange_ratio, 0.38 * root, 1.0 * root
        mp = tension_side[0][0]
        if lpf < lam <= lrf:
            mn = mp - (mp - 0.7 * fy * self.Sxc) * (lam - lpf) / (lrf - lpf)
            tension_side.append((min(mn, 1.6 * my), "F9-14 flange local buckling"))
        elif lam > lrf:
            tension_side.append((0.7 * e * self.Sxc / lam**2, "F9-15 flange local buckling"))
        # Stem in compression: yielding at My, LTB, stem local buckling.
        compression_side: list[tuple[float, str]] = [(my, "F9-3 yielding, stem in compression")]
        if unbraced > 0:
            compression_side.append((self._mcr(e, unbraced, -1.0), "F9-7 LTB, stem in compression"))
        ratio = self.stem_ratio
        if ratio <= 0.84 * root:
            fcr = fy
        elif ratio <= 1.52 * root:
            fcr = (1.43 - 0.515 * ratio * math.sqrt(fy / e)) * fy
        else:
            fcr = 1.52 * e / ratio**2
        compression_side.append((fcr * self.Sx, "F9-16 stem local buckling"))
        nominal, equation = min(tension_side + compression_side)
        note = "Tee flexure: the smaller of the stem in tension and in compression (F9)."
        return Strength(nominal, _available(nominal, "flexure", method), equation, (note,))

    def flexure_minor(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        """Yielding and flange local buckling about the axis of the stem, as F6."""
        e, fy = steel.E, steel.Fy
        mp = min(fy * self.Zy, 1.6 * fy * self.Sy)
        root = math.sqrt(e / fy)
        lam, lpf, lrf = self.flange_ratio, 0.38 * root, 1.0 * root
        candidates: list[tuple[float, str]] = [(mp, "F6-1 yielding")]
        if lpf < lam <= lrf:
            mn = mp - (mp - 0.7 * fy * self.Sy) * (lam - lpf) / (lrf - lpf)
            candidates.append((mn, "F6-2 flange local buckling"))
        elif lam > lrf:
            candidates.append((0.69 * e / lam**2 * self.Sy, "F6-3 flange local buckling"))
        nominal, equation = min(candidates)
        return Strength(nominal, _available(nominal, "flexure", method), equation)

    def shear_major(self, steel: Steel, method: Method, *, length: float) -> Strength:
        """G2.1(b) along the stem: ``Aw = d tw``, ``kv = 1.2``."""
        e, fy = steel.E, steel.Fy
        limit = 1.10 * math.sqrt(1.2 * e / fy)
        cv1 = 1.0 if self.stem_ratio <= limit else limit / self.stem_ratio
        nominal = 0.6 * fy * self.d * self.tw * cv1
        return Strength(nominal, _available(nominal, "shear", method), f"G2-1 (Cv1 = {cv1:.3f})")

    def shear_minor(self, steel: Steel, method: Method, *, length: float) -> Strength:
        """G6 along the one flange."""
        cv2 = _cv2(self.flange_ratio, 1.2, steel.E, steel.Fy)
        nominal = 0.6 * steel.Fy * self.bf * self.tf * cv2
        return Strength(nominal, _available(nominal, "shear", method), f"G6-1 (Cv2 = {cv2:.3f})")


# ──────────────────────────── equal-leg angles ────────────────────────────
@dataclass(frozen=True)
class EqualLegAngle:
    """A single angle with equal legs ``b`` and thickness ``t``, bent about its geometric axes."""

    name: str
    A: float
    b: float
    t: float
    Ix: float
    Iy: float
    Sx: float
    Sy: float
    rx: float
    ry: float
    J: float
    Cw: float

    @property
    def leg_ratio(self) -> float:
        return self.b / self.t

    @property
    def x_bar(self) -> float:
        """Centroid from the back of either leg."""
        b, t = self.b, self.t
        return (b * t * b / 2.0 + (b - t) * t * t / 2.0) / (t * (2.0 * b - t))

    @property
    def Ixy(self) -> float:
        """Product of inertia about the geometric axes through the centroid (magnitude)."""
        b, t, c = self.b, self.t, self.x_bar
        horizontal = b * t * (b / 2.0 - c) * (t / 2.0 - c)
        vertical = (b - t) * t * (t / 2.0 - c) * ((b + t) / 2.0 - c)
        return abs(horizontal + vertical)

    @property
    def Iw(self) -> float:
        """Major principal moment of inertia (about the axis of symmetry)."""
        mean = (self.Ix + self.Iy) / 2.0
        return mean + math.hypot((self.Ix - self.Iy) / 2.0, self.Ixy)

    @property
    def Iz(self) -> float:
        """Minor principal moment of inertia."""
        mean = (self.Ix + self.Iy) / 2.0
        return mean - math.hypot((self.Ix - self.Iy) / 2.0, self.Ixy)

    @property
    def rz(self) -> float:
        return math.sqrt(self.Iz / self.A)

    @property
    def rw(self) -> float:
        return math.sqrt(self.Iw / self.A)

    def tension(self, steel: Steel, method: Method) -> Strength:
        return tension(self, steel, method)  # type: ignore[arg-type]

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
        e, fy = steel.E, steel.Fy
        lc = max(k_x * length_x, k_y * length_y)
        fe, which = math.inf, "no buckling length"
        if lc > 0:
            fe, which = math.pi**2 * e / (lc / self.rz) ** 2, "E3-4 about z"
            xo = math.sqrt(2.0) * (self.x_bar - self.t / 2.0)
            ro2 = xo**2 + (self.Iw + self.Iz) / self.A
            h = 1.0 - xo**2 / ro2
            few = math.pi**2 * e / (lc / self.rw) ** 2
            fez = (math.pi**2 * e * self.Cw / lc**2 + steel.G * self.J) / (self.A * ro2)
            ftb = _flexural_torsional(few, fez, h)
            if ftb < fe:
                fe, which = ftb, "E4-5 flexural-torsional"
        fcr = fy if math.isinf(fe) else _critical_stress(fy, fe)
        root = math.sqrt(e / fy)
        b_e = _effective_width(self.b, self.leg_ratio, 0.45 * root, 0.22, 1.49, fy, fcr)
        effective = self.A - 2.0 * (self.b - b_e) * self.t
        return _compression_strength(fy, fe, which, self.A, effective, method)

    def _flexure(
        self, s_geometric: float, steel: Steel, method: Method, unbraced: float, cb: float
    ) -> Strength:
        """F10 about a geometric axis, no lateral-torsional restraint, toe in compression."""
        e, fy = steel.E, steel.Fy
        my = 0.8 * fy * s_geometric
        candidates: list[tuple[float, str]] = [(1.5 * my, "F10-1 yielding")]
        if unbraced > 0:
            b, t = self.b, self.t
            mcr = (
                0.58
                * e
                * b**4
                * t
                * cb
                / unbraced**2
                * (math.sqrt(1.0 + 0.88 * (unbraced * t / b**2) ** 2) - 1.0)
            )
            if my / mcr <= 1.0:
                mn = min((1.92 - 1.17 * math.sqrt(my / mcr)) * my, 1.5 * my)
                candidates.append((mn, "F10-2 LTB"))
            else:
                candidates.append(((0.92 - 0.17 * mcr / my) * mcr, "F10-3 LTB"))
        root = math.sqrt(e / fy)
        lam = self.leg_ratio
        sc = 0.8 * s_geometric
        if 0.54 * root < lam <= 0.91 * root:
            mn = fy * sc * (2.43 - 1.72 * lam * math.sqrt(fy / e))
            candidates.append((mn, "F10-6 leg local buckling"))
        elif lam > 0.91 * root:
            candidates.append((0.71 * e / lam**2 * sc, "F10-7 leg local buckling"))
        nominal, equation = min(candidates)
        return Strength(nominal, _available(nominal, "flexure", method), equation)

    def flexure_major(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return self._flexure(self.Sx, steel, method, unbraced, cb)

    def flexure_minor(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return self._flexure(self.Sy, steel, method, unbraced, cb)

    def _shear(self, steel: Steel, method: Method) -> Strength:
        """G3: ``Vn = 0.6 Fy b t Cv2`` with ``kv = 1.2``."""
        cv2 = _cv2(self.leg_ratio, 1.2, steel.E, steel.Fy)
        nominal = 0.6 * steel.Fy * self.b * self.t * cv2
        return Strength(nominal, _available(nominal, "shear", method), f"G3-1 (Cv2 = {cv2:.3f})")

    def shear_major(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return self._shear(steel, method)

    def shear_minor(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return self._shear(steel, method)


# ──────────────────────────── rectangular HSS ────────────────────────────
@dataclass(frozen=True)
class RectHSS:
    """A rectangular or square HSS: depth ``H`` (along the major axis), width ``B``."""

    name: str
    A: float
    H: float
    B: float
    t: float
    """Design wall thickness."""
    Ix: float
    Iy: float
    Zx: float
    Zy: float
    Sx: float
    Sy: float
    rx: float
    ry: float
    J: float

    @property
    def b_flat(self) -> float:
        return self.B - 3.0 * self.t

    @property
    def h_flat(self) -> float:
        return self.H - 3.0 * self.t

    def tension(self, steel: Steel, method: Method) -> Strength:
        return tension(self, steel, method)  # type: ignore[arg-type]

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
        e, fy = steel.E, steel.Fy
        found = _flexural_buckling(
            e, [(k_x * length_x, self.rx, "x"), (k_y * length_y, self.ry, "y")]
        )
        fe, which = found if found is not None else (math.inf, "no buckling length")
        fcr = fy if math.isinf(fe) else _critical_stress(fy, fe)
        limit = 1.40 * math.sqrt(e / fy)
        t = self.t
        b_e = _effective_width(self.b_flat, self.b_flat / t, limit, 0.20, 1.38, fy, fcr)
        h_e = _effective_width(self.h_flat, self.h_flat / t, limit, 0.20, 1.38, fy, fcr)
        effective = self.A - 2.0 * (self.b_flat - b_e) * t - 2.0 * (self.h_flat - h_e) * t
        return _compression_strength(fy, fe, which, self.A, effective, method)

    def _effective_modulus(
        self, flange_flat: float, b_eff: float, depth: float, inertia: float
    ) -> float:
        """F7-3's ``Se``: the section without ``flange_flat - b_eff`` of the compression flange."""
        lost = (flange_flat - b_eff) * self.t
        arm = (depth - self.t) / 2.0
        shift = lost * arm / (self.A - lost)
        reduced = inertia - lost * arm**2 - (self.A - lost) * shift**2
        return reduced / (depth / 2.0 + shift)

    def _flexure(
        self,
        steel: Steel,
        method: Method,
        *,
        z: float,
        s: float,
        inertia: float,
        depth: float,
        flange_flat: float,
        web_flat: float,
        r_minor: float,
        unbraced: float,
        cb: float,
    ) -> Strength:
        e, fy = steel.E, steel.Fy
        root = math.sqrt(e / fy)
        mp = fy * z
        candidates: list[tuple[float, str]] = [(mp, "F7-1 yielding")]
        notes: list[str] = []
        lam_f = flange_flat / self.t
        if 1.12 * root < lam_f <= 1.40 * root:
            mn = mp - (mp - fy * s) * (3.57 * lam_f * math.sqrt(fy / e) - 4.0)
            candidates.append((min(mn, mp), "F7-2 flange local buckling"))
        elif lam_f > 1.40 * root:
            b_eff = min(flange_flat, 1.92 * self.t * root * (1.0 - 0.38 / lam_f * root))
            se = self._effective_modulus(flange_flat, b_eff, depth, inertia)
            candidates.append((fy * se, "F7-3 flange local buckling"))
        lam_w = web_flat / self.t
        if 2.42 * root < lam_w <= 5.70 * root:
            mn = mp - (mp - fy * s) * (0.305 * lam_w * math.sqrt(fy / e) - 0.738)
            candidates.append((min(mn, mp), "F7-5 web local buckling"))
        elif lam_w > 5.70 * root:
            notes.append(f"Slender HSS web (h/t = {lam_w:.1f}): F7-6 not covered.")
        if unbraced > 0 and r_minor > 0:
            root_ja = math.sqrt(self.J * self.A)
            lp = 0.13 * e * r_minor * root_ja / mp
            lr = 2.0 * e * r_minor * root_ja / (0.7 * fy * s)
            if lp < unbraced <= lr:
                mn = cb * (mp - (mp - 0.7 * fy * s) * (unbraced - lp) / (lr - lp))
                candidates.append((min(mn, mp), "F7-10 LTB"))
            elif unbraced > lr:
                mn = 2.0 * e * cb * root_ja / (unbraced / r_minor)
                candidates.append((min(mn, mp), "F7-11 LTB"))
        nominal, equation = min(candidates)
        return Strength(nominal, _available(nominal, "flexure", method), equation, tuple(notes))

    def flexure_major(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return self._flexure(
            steel,
            method,
            z=self.Zx,
            s=self.Sx,
            inertia=self.Ix,
            depth=self.H,
            flange_flat=self.b_flat,
            web_flat=self.h_flat,
            r_minor=self.ry if self.H > self.B else 0.0,
            unbraced=unbraced,
            cb=cb,
        )

    def flexure_minor(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return self._flexure(
            steel,
            method,
            z=self.Zy,
            s=self.Sy,
            inertia=self.Iy,
            depth=self.B,
            flange_flat=self.h_flat,
            web_flat=self.b_flat,
            r_minor=0.0,
            unbraced=unbraced,
            cb=cb,
        )

    def _shear(self, steel: Steel, method: Method, web_flat: float) -> Strength:
        """G4: ``Vn = 0.6 Fy Aw Cv2`` with ``Aw = 2 h t`` and ``kv = 5``."""
        cv2 = _cv2(web_flat / self.t, 5.0, steel.E, steel.Fy)
        nominal = 0.6 * steel.Fy * 2.0 * web_flat * self.t * cv2
        return Strength(nominal, _available(nominal, "shear", method), f"G4-1 (Cv2 = {cv2:.3f})")

    def shear_major(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return self._shear(steel, method, self.h_flat)

    def shear_minor(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return self._shear(steel, method, self.b_flat)


# ──────────────────────────── round HSS and pipe ────────────────────────────
@dataclass(frozen=True)
class RoundHSS:
    """A round HSS or pipe of outside diameter ``D`` and design wall ``t``."""

    name: str
    A: float
    D: float
    t: float
    Ix: float
    Z: float
    S: float
    r: float
    J: float

    @property
    def Iy(self) -> float:
        return self.Ix

    @property
    def slenderness(self) -> float:
        return self.D / self.t

    def tension(self, steel: Steel, method: Method) -> Strength:
        return tension(self, steel, method)  # type: ignore[arg-type]

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
        e, fy = steel.E, steel.Fy
        lc = max(k_x * length_x, k_y * length_y)
        fe = math.pi**2 * e / (lc / self.r) ** 2 if lc > 0 else math.inf
        which = "E3-4" if lc > 0 else "no buckling length"
        ratio = self.slenderness
        effective = self.A
        if ratio > 0.11 * e / fy:
            effective = min(self.A, (0.038 * e / (fy * ratio) + 2.0 / 3.0) * self.A)
        strength = _compression_strength(fy, fe, which, self.A, effective, method)
        if ratio > 0.45 * e / fy:
            note = f"D/t = {ratio:.0f} is above 0.45 E/Fy, outside E7's scope."
            return Strength(
                strength.nominal, strength.available, strength.equation, (*strength.notes, note)
            )
        return strength

    def _flexure(self, steel: Steel, method: Method) -> Strength:
        """F8: yielding and local buckling."""
        e, fy = steel.E, steel.Fy
        ratio = self.slenderness
        notes: tuple[str, ...] = ()
        if ratio <= 0.07 * e / fy:
            nominal, equation = fy * self.Z, "F8-1 yielding"
        elif ratio <= 0.31 * e / fy:
            nominal = min(fy * self.Z, (0.021 * e / ratio + fy) * self.S)
            equation = "F8-2 local buckling"
        else:
            nominal = min(fy * self.Z, 0.33 * e / ratio * self.S)
            equation = "F8-3 local buckling"
        if ratio > 0.45 * e / fy:
            notes = (f"D/t = {ratio:.0f} is above 0.45 E/Fy, outside F8's scope.",)
        return Strength(nominal, _available(nominal, "flexure", method), equation, notes)

    def flexure_major(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return self._flexure(steel, method)

    def flexure_minor(
        self, steel: Steel, method: Method, *, unbraced: float, cb: float = 1.0
    ) -> Strength:
        return self._flexure(steel, method)

    def _shear(self, steel: Steel, method: Method, length: float) -> Strength:
        """G5: ``Vn = Fcr Ag / 2`` with ``Lv`` half the member length."""
        e, fy = steel.E, steel.Fy
        ratio = self.slenderness
        lv = max(length / 2.0, 1e-12)
        fcr = max(1.60 * e / (math.sqrt(lv / self.D) * ratio**1.25), 0.78 * e / ratio**1.5)
        fcr = min(fcr, 0.6 * fy)
        nominal = fcr * self.A / 2.0
        return Strength(nominal, _available(nominal, "shear", method), "G5-1")

    def shear_major(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return self._shear(steel, method, length)

    def shear_minor(self, steel: Steel, method: Method, *, length: float) -> Strength:
        return self._shear(steel, method, length)
