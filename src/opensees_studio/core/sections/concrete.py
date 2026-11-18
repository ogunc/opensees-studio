"""Reinforced concrete sections from a few engineering inputs (Define → Concrete Section Wizard).

A :class:`ConcreteSectionSpec` describes the section as an engineer specifies
it: the shape (rectangle, circle, T or L), its dimensions, the clear cover to the
ties, the bar sizes and counts, the tie spacing and the material strengths.
:func:`build_concrete_section` turns it into what OpenSees needs:

* three materials: the **cover** concrete (``Concrete02``, unconfined: strength
  ``f'c`` at ``2 f'c / Ec``, spalled to zero at a strain of 0.005), the **core**
  concrete (``Concrete02``, confined by the ties after Mander, Priestley and
  Park 1988 when asked, otherwise the same as the cover) and the **bars**
  (``Steel02``, 1 % hardening). With ``concrete_model = "ConcreteCM"`` both
  concretes are Chang and Mander's cyclic model instead: the cover with their
  unconfined ``εc = f'c^(1/4) / 1150`` and ``r = f'c / 5.2 - 1.9`` (MPa), the
  core on Mander's confined curve exactly (``rc = Ec / (Ec - f'cc / εcc)``);
* a **fibre section**: core inside the bar centrelines, cover around it, bars as
  layers, so a nonlinear frame member reads the section directly;
* optionally an **elastic section** with the gross properties and ``Ec`` of
  ACI 318-19 (``4700 sqrt(f'c)`` MPa), with the moment of inertia multiplied by
  the cracked-section factor of ACI 318-19 Table 6.6.3.1.1 (0.70 for a column,
  0.35 for a beam) — for a linear model of the same member.

Depth ``h`` runs along local y and width ``b`` along local z; the flange of a T
or an L is at ``+y``, the L's flange overhangs towards ``+z``.

Mander's confinement: the effective lateral pressure is ``f'l = ke ρs fyh / 2``
with the volumetric ratio of the ties ``ρs`` and ``ke`` 0.75 for rectangular
hoops (0.95 for a spiral); ``f'cc = f'c (-1.254 + 2.254 sqrt(1 + 7.94 f'l / f'c)
- 2 f'l / f'c)``, ``εcc = εco (1 + 5 (f'cc / f'c - 1))`` and the ultimate strain
``εcu = 0.004 + 1.4 ρs fyh εsu / f'cc`` with ``εsu = 0.09``. A rectangle's tie
ratio counts two legs each way, a circle's is ``4 Asp / (ds s)``.

No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from opensees_studio.core.materials import Concrete02, Steel02
from opensees_studio.core.materials.library import ConcreteCM
from opensees_studio.core.sections import (
    CircularPatch,
    ElasticSection,
    FiberSection,
    RectangularPatch,
    RectShape,
    StraightLayer,
    rc_circular_fibres,
    rc_rectangular_fibres,
)
from opensees_studio.core.sections.geometry import (
    CircleRegion,
    PolygonRegion,
    Region,
    SectionProperties,
    rectangle,
    section_properties,
)
from opensees_studio.core.units import UnitSystem, length_scale, stress_scale

ShapeKind = Literal["rect", "circ", "tee", "ell"]
Role = Literal["column", "beam"]
ConcreteModel = Literal["Concrete02", "ConcreteCM"]

#: Nominal bar diameter (in) and area (in²), ASTM A615.
US_BARS: dict[str, tuple[float, float]] = {
    "#3": (0.375, 0.11),
    "#4": (0.500, 0.20),
    "#5": (0.625, 0.31),
    "#6": (0.750, 0.44),
    "#7": (0.875, 0.60),
    "#8": (1.000, 0.79),
    "#9": (1.128, 1.00),
    "#10": (1.270, 1.27),
    "#11": (1.410, 1.56),
    "#14": (1.693, 2.25),
    "#18": (2.257, 4.00),
}

#: Metric bars: nominal diameter in mm (the area is π d² / 4).
METRIC_BARS: tuple[int, ...] = (6, 8, 10, 12, 16, 18, 20, 22, 25, 28, 32, 36, 40)

#: ACI 318-19 Table 6.6.3.1.1: moment of inertia factor of a cracked member.
CRACKED_FACTOR: dict[str, float] = {"column": 0.70, "beam": 0.35}

#: Mander's confinement effectiveness of rectangular hoops and of a spiral.
KE_RECT, KE_SPIRAL = 0.75, 0.95


def bar_names(system: Literal["US", "metric"]) -> list[str]:
    return list(US_BARS) if system == "US" else [f"φ{d}" for d in METRIC_BARS]


def bar_size(name: str, units: UnitSystem) -> tuple[float, float]:
    """Diameter and area of the bar ``name`` (``#5``, ``φ16``) in the project's units.

    Raises:
        KeyError: an unknown bar name.
    """
    if name in US_BARS:
        diameter, area = US_BARS[name]
        f = length_scale(UnitSystem.US_IN_KIP, units)
        return diameter * f, area * f**2
    digits = name.lstrip("φØø ").removesuffix("mm")
    if digits.isdigit() and int(digits) in METRIC_BARS:
        f = length_scale(UnitSystem.SI_MM_N, units)
        diameter = int(digits) * f
        return diameter, math.pi * diameter**2 / 4.0
    raise KeyError(f"{name!r} is not a bar size (US #3 to #18, metric φ6 to φ40).")


@dataclass
class ConcreteSectionSpec:
    """A reinforced concrete section as an engineer specifies it, in the project's units."""

    shape: ShapeKind = "rect"
    h: float = 0.5
    """Total depth along local y (the diameter of a circle)."""
    b: float = 0.3
    """Width along local z (the web of a T or an L)."""
    bf: float = 1.0
    """Flange width of a T or an L."""
    hf: float = 0.12
    """Flange thickness of a T or an L."""
    clear_cover: float = 0.04
    """From the concrete face to the outside of the ties."""
    bar: str = "φ20"
    tie: str = "φ10"
    tie_spacing: float = 0.15
    n_top: int = 3
    n_bottom: int = 3
    n_side: int = 1
    """Intermediate bars on each side face (rectangle, T, L)."""
    n_bars: int = 8
    """Bars of a circular section."""
    fc: float = 30e6
    """Specified compressive strength (positive)."""
    fy: float = 420e6
    fyh: float = 420e6
    Es: float = 200e9
    confined: bool = True
    concrete_model: ConcreteModel = "Concrete02"
    """``Concrete02`` (monotonic envelope, linear unloading) or ``ConcreteCM`` (cyclic)."""
    role: Role = "column"
    units: UnitSystem = UnitSystem.SI_M_N
    name: str = ""

    # ── derived ──────────────────────────────────────────────────────
    @property
    def bar_diameter(self) -> float:
        return bar_size(self.bar, self.units)[0]

    @property
    def bar_area(self) -> float:
        return bar_size(self.bar, self.units)[1]

    @property
    def tie_diameter(self) -> float:
        return bar_size(self.tie, self.units)[0]

    @property
    def tie_area(self) -> float:
        return bar_size(self.tie, self.units)[1]

    @property
    def cover_to_bars(self) -> float:
        """From the concrete face to the centre of the longitudinal bars."""
        return self.clear_cover + self.tie_diameter + self.bar_diameter / 2.0

    @property
    def bar_count(self) -> int:
        if self.shape == "circ":
            return self.n_bars
        return self.n_top + self.n_bottom + 2 * self.n_side

    @property
    def steel_area(self) -> float:
        return self.bar_count * self.bar_area

    def regions(self) -> list[Region]:
        """The concrete outline (solid regions only)."""
        if self.shape == "circ":
            return [CircleRegion(0.0, 0.0, self.h / 2.0)]
        web = rectangle(self.b, self.h)
        if self.shape == "rect":
            return [web]
        top, flange_mid = self.h / 2.0, self.h / 2.0 - self.hf / 2.0
        if self.shape == "tee":
            overhang = (self.bf - self.b) / 2.0
            return [
                web,
                rectangle(overhang, self.hf, flange_mid, -(self.b + overhang) / 2.0),
                rectangle(overhang, self.hf, flange_mid, (self.b + overhang) / 2.0),
            ]
        overhang = self.bf - self.b
        z0 = self.b / 2.0
        return [
            web,
            PolygonRegion(
                (
                    (top - self.hf, z0),
                    (top - self.hf, z0 + overhang),
                    (top, z0 + overhang),
                    (top, z0),
                )
            ),
        ]

    def validate(self) -> list[str]:
        """Problems that stop the section from being built (empty when it can be)."""
        problems: list[str] = []
        try:
            bar_size(self.bar, self.units)
            bar_size(self.tie, self.units)
        except KeyError as exc:
            return [str(exc.args[0])]
        if (
            min(self.h, self.clear_cover, self.tie_spacing, self.fc, self.fy, self.fyh, self.Es)
            <= 0
        ):
            problems.append("Dimensions, cover, spacing and strengths must be positive.")
            return problems
        if self.shape != "circ" and self.b <= 0:
            problems.append("The width must be positive.")
            return problems
        smallest = self.h if self.shape == "circ" else min(self.h, self.b)
        if 2.0 * self.cover_to_bars >= smallest:
            problems.append("The cover and the bars do not fit in the section.")
        if self.shape in ("tee", "ell"):
            if self.bf <= self.b:
                problems.append("The flange must be wider than the web.")
            if not 0 < self.hf < self.h:
                problems.append("The flange thickness must be between 0 and the depth.")
        if self.shape == "circ" and self.n_bars < 3:
            problems.append("A circular section needs at least three bars.")
        if self.shape != "circ" and (self.n_top < 2 or self.n_bottom < 2 or self.n_side < 0):
            problems.append("Top and bottom need at least two bars each.")
        return problems


# ──────────────────────────── confinement ────────────────────────────
@dataclass(frozen=True)
class Confinement:
    """Mander's confined concrete for the spec's ties."""

    rho_s: float
    fl: float
    fcc: float
    eps_cc: float
    eps_cu: float


def tie_ratio(spec: ConcreteSectionSpec) -> float:
    """Volumetric ratio of the transverse reinforcement ``ρs``."""
    a, s = spec.tie_area, spec.tie_spacing
    if spec.shape == "circ":
        ds = spec.h - 2.0 * spec.clear_cover - spec.tie_diameter
        return 4.0 * a / (ds * s)
    bc = spec.b - 2.0 * spec.clear_cover - spec.tie_diameter
    dc = spec.h - 2.0 * spec.clear_cover - spec.tie_diameter
    return 2.0 * a / (s * dc) + 2.0 * a / (s * bc)


def mander(spec: ConcreteSectionSpec, eps_co: float) -> Confinement:
    """Confined strength and strains of the core (Mander, Priestley and Park 1988)."""
    rho = tie_ratio(spec)
    ke = KE_SPIRAL if spec.shape == "circ" else KE_RECT
    fl = 0.5 * ke * rho * spec.fyh
    ratio = fl / spec.fc
    fcc = spec.fc * (-1.254 + 2.254 * math.sqrt(1.0 + 7.94 * ratio) - 2.0 * ratio)
    eps_cc = eps_co * (1.0 + 5.0 * (fcc / spec.fc - 1.0))
    eps_cu = 0.004 + 1.4 * rho * spec.fyh * 0.09 / fcc
    return Confinement(rho, fl, fcc, eps_cc, max(eps_cu, eps_cc * 1.5))


def concrete_modulus(fc: float, units: UnitSystem) -> float:
    """ACI 318-19 19.2.2.1(b): ``Ec = 4700 sqrt(f'c)`` with ``f'c`` in MPa, in the project's units."""
    to_mpa = stress_scale(units, UnitSystem.SI_MM_N)
    return 4700.0 * math.sqrt(fc * to_mpa) / to_mpa


# ──────────────────────────── the result ────────────────────────────
@dataclass
class ConcreteSection:
    """What the wizard adds to the project."""

    materials: list[object] = field(default_factory=list)
    fiber: FiberSection | None = None
    elastic: ElasticSection | None = None
    properties: SectionProperties | None = None
    confinement: Confinement | None = None
    Ec: float = 0.0
    notes: list[str] = field(default_factory=list)


def build_concrete_section(
    spec: ConcreteSectionSpec,
    *,
    material_id: int,
    section_id: int,
    fiber: bool = True,
    elastic: bool = False,
    cracked_factor: float | None = None,
) -> ConcreteSection:
    """Materials and sections of ``spec``; ids count up from ``material_id`` and ``section_id``.

    Raises:
        ValueError: the spec cannot be built (see :meth:`ConcreteSectionSpec.validate`).
    """
    problems = spec.validate()
    if problems:
        raise ValueError(" ".join(problems))
    out = ConcreteSection()
    ec = concrete_modulus(spec.fc, spec.units)
    out.Ec = ec
    eps_co = 2.0 * spec.fc / ec
    name = spec.name or _default_name(spec)
    to_ft = math.sqrt(spec.fc * stress_scale(spec.units, UnitSystem.SI_MM_N))
    ft = 0.33 * to_ft / stress_scale(spec.units, UnitSystem.SI_MM_N)
    if spec.concrete_model == "ConcreteCM":
        cm_cover, cm_core, out.confinement = _chang_mander(spec, name, material_id, ec, ft)
        bars = Steel02(id=material_id + 2, name=f"{name} bars", Fy=spec.fy, E0=spec.Es, b=0.01)
        out.materials = [cm_cover, cm_core, bars]
        return _sections(
            spec, out, name, ec, material_id, section_id, fiber, elastic, cracked_factor
        )
    cover = _concrete02(
        id=material_id,
        name=f"{name} cover",
        fpc=-spec.fc,
        epsc0=-eps_co,
        fpcu=0.0,
        epsU=-0.005,
        ft=ft,
        Ets=ft / 0.002,
    )
    if spec.confined:
        conf = mander(spec, eps_co)
        out.confinement = conf
        core = _concrete02(
            id=material_id + 1,
            name=f"{name} core",
            fpc=-conf.fcc,
            epsc0=-conf.eps_cc,
            fpcu=-0.2 * conf.fcc,
            epsU=-conf.eps_cu,
            ft=ft,
            Ets=ft / 0.002,
        )
    else:
        core = cover.model_copy(update={"id": material_id + 1, "name": f"{name} core"})
    steel = Steel02(id=material_id + 2, name=f"{name} bars", Fy=spec.fy, E0=spec.Es, b=0.01)
    out.materials = [cover, core, steel]
    return _sections(spec, out, name, ec, material_id, section_id, fiber, elastic, cracked_factor)


def _sections(
    spec: ConcreteSectionSpec,
    out: ConcreteSection,
    name: str,
    ec: float,
    material_id: int,
    section_id: int,
    fiber: bool,
    elastic: bool,
    cracked_factor: float | None,
) -> ConcreteSection:
    """The fibre and elastic sections over the cover, core and steel at ``material_id`` + 0, 1, 2."""
    props = section_properties(spec.regions())
    out.properties = props
    if fiber:
        out.fiber = FiberSection(
            id=section_id,
            name=name,
            patches=_patches(spec, material_id, material_id + 1),
            layers=_layers(spec, material_id + 2),
            GJ=(ec / 2.4) * _torsion(spec, props),
        )
    if elastic:
        factor = cracked_factor if cracked_factor is not None else CRACKED_FACTOR[spec.role]
        out.elastic = ElasticSection(
            id=section_id + (1 if fiber else 0),
            name=f"{name} (elastic, {factor:g} Ig)",
            E=ec,
            A=props.A,
            Iz=factor * props.Iz,
            Iy=factor * props.Iy,
            G=ec / 2.4,
            J=_torsion(spec, props),
            shape=RectShape(d=spec.h, b=spec.b) if spec.shape == "rect" else None,
        )
        out.notes.append(
            f"Elastic section: Ec = 4700 sqrt(f'c) MPa, I = {factor:g} Ig "
            f"(ACI 318-19 Table 6.6.3.1.1, {spec.role}), G = Ec / 2.4 (ν = 0.2)."
        )
    rho_l = spec.steel_area / props.A
    if not 0.01 <= rho_l <= 0.08 and spec.role == "column":
        out.notes.append(f"Longitudinal ratio {rho_l:.2%} is outside ACI's 1 % to 8 % for columns.")
    return out


def chang_mander_strain(fc: float, units: UnitSystem) -> float:
    """Chang and Mander's strain at peak of unconfined concrete: ``f'c^(1/4) / 1150`` (MPa)."""
    to_mpa = stress_scale(units, UnitSystem.SI_MM_N)
    return float((fc * to_mpa) ** 0.25 / 1150.0)


def chang_mander_r(fc: float, units: UnitSystem) -> float:
    """Chang and Mander's shape parameter of unconfined concrete: ``f'c / 5.2 - 1.9`` (MPa)."""
    to_mpa = stress_scale(units, UnitSystem.SI_MM_N)
    return max(1.1, fc * to_mpa / 5.2 - 1.9)


def _chang_mander(
    spec: ConcreteSectionSpec, name: str, material_id: int, ec: float, ft: float
) -> tuple[ConcreteCM, ConcreteCM, Confinement | None]:
    """Cover and core as ``ConcreteCM``: Chang-Mander unconfined, Mander-confined core.

    The core's envelope is Mander's curve exactly: ``rc = Ec / (Ec - f'cc / εcc)``.
    Tension follows Tsai's curve with ``n = rt = 1.2`` to ``ft`` (0.33 sqrt(f'c) MPa).
    """
    eps_c = chang_mander_strain(spec.fc, spec.units)
    et = 1.2 * ft / ec
    cover = ConcreteCM(
        id=material_id,
        name=f"{name} cover",
        fpcc=-spec.fc,
        epcc=-eps_c,
        Ec=ec,
        rc=chang_mander_r(spec.fc, spec.units),
        xcrn=1.035,
        ft=ft,
        et=et,
        rt=1.2,
        xcrp=10000.0,
    )
    if not spec.confined:
        return cover, cover.model_copy(update={"id": material_id + 1, "name": f"{name} core"}), None
    conf = mander(spec, eps_c)
    secant = conf.fcc / conf.eps_cc
    core = ConcreteCM(
        id=material_id + 1,
        name=f"{name} core",
        fpcc=-conf.fcc,
        epcc=-conf.eps_cc,
        Ec=ec,
        rc=ec / (ec - secant),
        xcrn=max(1.035, conf.eps_cu / conf.eps_cc),
        ft=ft,
        et=et,
        rt=1.2,
        xcrp=10000.0,
    )
    return cover, core, conf


def _concrete02(**fields: object) -> Concrete02:
    """A ``Concrete02`` with the unloading ratio λ = 0.1 (``lambda`` is a keyword)."""
    return Concrete02.model_validate({**fields, "lambda": 0.1})


def _default_name(spec: ConcreteSectionSpec) -> str:
    from opensees_studio.core.units import labels_for

    unit = labels_for(spec.units).length
    if spec.shape == "circ":
        size = f"D{spec.h:g}"
    elif spec.shape == "rect":
        size = f"{spec.b:g}x{spec.h:g}"
    else:
        size = f"{spec.shape.upper()} {spec.bf:g}x{spec.h:g}"
    return f"RC {size}{unit} {spec.bar_count}{spec.bar}"


def _torsion(spec: ConcreteSectionSpec, props: SectionProperties) -> float:
    """Gross torsional constant: exact for a rectangle and a circle, a sum of rectangles for T and L."""
    if spec.shape == "circ":
        return math.pi * spec.h**4 / 32.0
    parts = [(spec.h, spec.b)]
    if spec.shape in ("tee", "ell"):
        parts.append((spec.bf - spec.b, spec.hf))
    total = 0.0
    for long, short in parts:
        long, short = max(long, short), min(long, short)
        total += (
            long
            * short**3
            * (1.0 / 3.0 - 0.21 * short / long * (1.0 - short**4 / (12.0 * long**4)))
        )
    del props
    return total


def _patches(
    spec: ConcreteSectionSpec, cover_id: int, core_id: int
) -> list[RectangularPatch | CircularPatch]:
    c = spec.cover_to_bars
    if spec.shape == "circ":
        rings, _ = rc_circular_fibres(
            core_material_id=core_id,
            cover_material_id=cover_id,
            steel_material_id=core_id,
            diameter=spec.h,
            cover=c,
            n_bars=3,
            bar_area=1.0,
        )
        return [*rings]
    patches, _ = rc_rectangular_fibres(
        core_material_id=core_id,
        cover_material_id=cover_id,
        steel_material_id=core_id,
        h=spec.h,
        b=spec.b,
        cover=c,
        n_top=2,
        n_bottom=2,
        n_side=0,
        bar_area=1.0,
    )
    out: list[RectangularPatch | CircularPatch] = [*patches]
    if spec.shape in ("tee", "ell"):
        top, bottom = spec.h / 2.0, spec.h / 2.0 - spec.hf
        n_y = max(2, round(8 * spec.hf / spec.h))
        sides = (
            [(-spec.bf / 2.0, -spec.b / 2.0), (spec.b / 2.0, spec.bf / 2.0)]
            if spec.shape == "tee"
            else [(spec.b / 2.0, spec.bf - spec.b / 2.0)]
        )
        for z_i, z_j in sides:
            n_z = max(2, round(10 * (z_j - z_i) / spec.bf))
            out.append(
                RectangularPatch(
                    material_id=cover_id,
                    n_fib_y=n_y,
                    n_fib_z=n_z,
                    y_i=bottom,
                    z_i=z_i,
                    y_j=top,
                    z_j=z_j,
                )
            )
    return out


def _layers(spec: ConcreteSectionSpec, steel_id: int) -> list[StraightLayer]:
    c = spec.cover_to_bars
    if spec.shape == "circ":
        _, bars = rc_circular_fibres(
            core_material_id=steel_id,
            cover_material_id=steel_id,
            steel_material_id=steel_id,
            diameter=spec.h,
            cover=c,
            n_bars=spec.n_bars,
            bar_area=spec.bar_area,
        )
        return list(bars)
    _, layers = rc_rectangular_fibres(
        core_material_id=steel_id,
        cover_material_id=steel_id,
        steel_material_id=steel_id,
        h=spec.h,
        b=spec.b,
        cover=c,
        n_top=spec.n_top,
        n_bottom=spec.n_bottom,
        n_side=spec.n_side,
        bar_area=spec.bar_area,
    )
    return list(layers)


def bar_positions(spec: ConcreteSectionSpec) -> list[tuple[float, float]]:
    """Centres ``(y, z)`` of every longitudinal bar, for drawing."""
    out: list[tuple[float, float]] = []
    for layer in _layers(spec, 1):
        n = layer.n_bars
        for k in range(n):
            t = 0.5 if n == 1 else k / (n - 1)
            out.append(
                (
                    layer.y_start + (layer.y_end - layer.y_start) * t,
                    layer.z_start + (layer.z_end - layer.z_start) * t,
                )
            )
    return out
