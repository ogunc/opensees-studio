"""Composite steel deck slabs as orthotropic layered shells (Define → Steel Deck Slab…).

A concrete slab cast on a ribbed steel deck is much stiffer along the ribs than
across them. Along the ribs the concrete of the ribs and the deck sheet work
with the topping; across them only the concrete above the ribs is continuous
(the corrugated sheet folds like an accordion and the ribs are separate).
OpenSees' ``ElasticMembranePlateSection`` is isotropic, so the wizard builds a
``section LayeredShell`` of three ``PlateFiber`` layers of
``nDMaterial ElasticOrthotropic`` instead and calibrates the layers so the shell
has exactly the stiffness worked out here.

What is computed, per unit width, in consistent units (the project's):

* **Strong direction** (along the ribs): the uncracked transformed section of
  topping + trapezoidal ribs + deck sheet, ``n = Es / Ec``. ``EA₁`` and ``EI₁``
  about its own centroid.
* **Weak direction** (across the ribs): the topping alone, ``EA₂ = Ec tc`` and
  ``EI₂ = Ec tc³ / 12`` — the usual design assumption (ETABS and SAP2000 take
  the slab above the deck as the continuous part).
* **In-plane shear**: the topping, ``Gc tc``; **twisting**: Huber's orthotropic
  plate, ``√(EI₁ EI₂) / (2 (1 + ν))``.
* **Transverse shear**: ``Gc`` times the concrete area along the ribs, ``Gc tc``
  across them.
* **Weight and mass**: the concrete of the topping and the ribs plus the sheet.

How the layered shell reproduces them. OpenSees integrates a ``LayeredShell``
at the mid-plane of each layer (``Σ E t`` for the membrane, ``Σ E t z²`` for
bending, no ``t³/12`` of the layer itself). With two thin faces of thickness
``a`` at ``z = ±(h - a) / 2`` and a core of thickness ``c`` at ``z = 0`` the core
adds no bending, so for each direction::

    face modulus = EI / (2 a z²)          core modulus = (EA - 2 a · face) / c

which is positive whenever ``EI / EA < z²``. The total thickness is the real
depth ``tc + hr`` unless that ratio needs a deeper equivalent shell. Those
moduli are the layers' ``Ex`` / ``Ey`` and ``νxy = ν √(Ex / Ey)`` (Huber;
``νxy νyx = ν²``), so — as for an isotropic slab — a strip with free edges has
exactly ``EA`` and ``EI`` and a wide plate ``1 / (1 - ν²)`` of them. The z axis
is uncoupled. The section's
``unit_weight`` is the weight per area over ``h``, the layers' ``rho`` the mass
per area over ``h``, so self weight and mass are the real ones.

The ribs run along the shell's local axis 1 (x), from its first node to its
second, unless ``ribs_along`` says local 2. The stiffness is elastic and
uncracked: cracking is left to the engineer, as for any elastic section.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from opensees_studio.core.materials.library import ElasticOrthotropic, PlateFiberMaterial
from opensees_studio.core.sections import LayeredShellSection, ShellLayer
from opensees_studio.core.units import UnitSystem, gravity, length_scale

DeckKind = Literal["trapezoidal", "reentrant"]


@dataclass(frozen=True)
class DeckProfile:
    """A deck profile preset, in millimetres.

    ``rib_bottom`` and ``rib_top`` are the widths of the *concrete* rib at the
    sheet's bottom and at the top of the rib (an open trapezoidal deck widens
    upwards, a re-entrant one narrows).
    """

    name: str
    kind: DeckKind
    rib_height: float
    pitch: float
    rib_bottom: float
    rib_top: float


#: Typical profiles (nominal values; check the manufacturer's table).
DECK_PROFILES: tuple[DeckProfile, ...] = (
    DeckProfile("Trapezoidal 1.5 in (38 mm), 6 in pitch", "trapezoidal", 38.1, 152.4, 44.5, 69.9),
    DeckProfile("Trapezoidal 2 in (51 mm), 12 in pitch", "trapezoidal", 50.8, 304.8, 114.3, 177.8),
    DeckProfile("Trapezoidal 3 in (76 mm), 12 in pitch", "trapezoidal", 76.2, 304.8, 120.7, 184.2),
    DeckProfile("Re-entrant 51 mm, 152.5 mm pitch", "reentrant", 51.0, 152.5, 140.0, 115.0),
)

#: Sheet gauge → base metal thickness, mm (SDI design thicknesses).
DECK_GAUGES: dict[str, float] = {
    "22 ga": 0.75,
    "20 ga": 0.91,
    "18 ga": 1.20,
    "16 ga": 1.52,
}

#: Fraction of the total thickness each face layer takes.
FACE_FRACTION = 0.05
#: The core keeps at least this share of the membrane stiffness.
_CORE_SHARE = 0.05


@dataclass(frozen=True)
class DeckInput:
    """A steel deck slab, every value in the project's consistent units."""

    rib_height: float
    pitch: float
    rib_bottom: float
    rib_top: float
    sheet_thickness: float
    topping: float
    Ec: float
    nu: float
    rho_c: float
    Es: float
    rho_s: float
    ribs_along: Literal["x", "y"] = "x"

    def check(self) -> None:
        """Raise ``ValueError`` on a geometry or material that cannot be a deck."""
        positive = {
            "rib height": self.rib_height,
            "rib spacing": self.pitch,
            "rib bottom width": self.rib_bottom,
            "rib top width": self.rib_top,
            "sheet thickness": self.sheet_thickness,
            "concrete above the ribs": self.topping,
            "concrete modulus": self.Ec,
            "steel modulus": self.Es,
        }
        for label, value in positive.items():
            if not value > 0.0:
                raise ValueError(f"The {label} must be positive.")
        if max(self.rib_bottom, self.rib_top) >= self.pitch:
            raise ValueError("The rib widths must be less than the rib spacing.")
        if self.sheet_thickness >= 0.5 * self.rib_height:
            raise ValueError("The sheet thickness must be small next to the rib height.")
        if not 0.0 <= self.nu < 0.5:
            raise ValueError("The concrete Poisson's ratio must be in [0, 0.5).")
        if self.rho_c < 0.0 or self.rho_s < 0.0:
            raise ValueError("The mass densities cannot be negative.")


@dataclass(frozen=True)
class DeckProperties:
    """Stiffness, weight and mass of a deck slab per unit width."""

    depth: float
    """Total depth ``tc + hr``."""
    concrete_area: float
    """Concrete per unit width (topping + ribs)."""
    steel_area: float
    """Deck sheet per unit width."""
    centroid: float
    """Transformed centroid along the ribs, from the bottom of the deck."""
    EA_strong: float
    EI_strong: float
    EA_weak: float
    EI_weak: float
    GA_inplane: float
    GI_twist: float
    GA_shear_strong: float
    GA_shear_weak: float
    mass_per_area: float
    Ec: float
    nu: float

    @property
    def G(self) -> float:
        return self.Ec / (2.0 * (1.0 + self.nu))

    @property
    def membrane_thickness_strong(self) -> float:
        """Concrete thickness with the strong-direction axial stiffness."""
        return self.EA_strong / self.Ec

    @property
    def membrane_thickness_weak(self) -> float:
        return self.EA_weak / self.Ec

    @property
    def bending_thickness_strong(self) -> float:
        """Solid concrete thickness with the strong-direction bending stiffness."""
        return float((12.0 * self.EI_strong / self.Ec) ** (1.0 / 3.0))

    @property
    def bending_thickness_weak(self) -> float:
        return float((12.0 * self.EI_weak / self.Ec) ** (1.0 / 3.0))

    @property
    def stiffness_ratio(self) -> float:
        """``EI₁ / EI₂``: how much stiffer the slab bends along the ribs."""
        return self.EI_strong / self.EI_weak


def deck_properties(deck: DeckInput) -> DeckProperties:
    """Per-unit-width stiffness, weight and mass of ``deck`` (see the module notes)."""
    deck.check()
    hr, p, wb, wt = deck.rib_height, deck.pitch, deck.rib_bottom, deck.rib_top
    t, tc = deck.sheet_thickness, deck.topping
    n = deck.Es / deck.Ec

    # Concrete per pitch: the topping and one trapezoidal rib.
    a_top = tc * p
    z_top = hr + tc / 2.0
    i_top = p * tc**3 / 12.0
    a_rib = 0.5 * (wb + wt) * hr
    z_rib = hr * (wb + 2.0 * wt) / (3.0 * (wb + wt))
    i_rib = hr**3 * (wb * wb + 4.0 * wb * wt + wt * wt) / (36.0 * (wb + wt))

    # Sheet per pitch: the pan under the rib, the top flanges, two inclined webs.
    web = math.hypot(hr, 0.5 * (wt - wb))
    a_pan, a_flange, a_web = t * wb, t * (p - wt), 2.0 * t * web
    z_pan, z_flange, z_web = 0.0, hr, hr / 2.0
    i_web = a_web * hr * hr / 12.0

    parts = [  # (transformed area, centroid, own second moment), concrete units
        (a_top, z_top, i_top),
        (a_rib, z_rib, i_rib),
        (n * a_pan, z_pan, 0.0),
        (n * a_flange, z_flange, 0.0),
        (n * a_web, z_web, n * i_web),
    ]
    area = sum(a for a, _, _ in parts)
    centroid = sum(a * z for a, z, _ in parts) / area
    inertia = sum(i + a * (z - centroid) ** 2 for a, z, i in parts)

    ec, g = deck.Ec, deck.Ec / (2.0 * (1.0 + deck.nu))
    concrete = (a_top + a_rib) / p
    steel = (a_pan + a_flange + a_web) / p
    ei_strong = ec * inertia / p
    ei_weak = ec * tc**3 / 12.0
    return DeckProperties(
        depth=tc + hr,
        concrete_area=concrete,
        steel_area=steel,
        centroid=centroid,
        EA_strong=ec * area / p,
        EI_strong=ei_strong,
        EA_weak=ec * tc,
        EI_weak=ei_weak,
        GA_inplane=g * tc,
        GI_twist=math.sqrt(ei_strong * ei_weak) / (2.0 * (1.0 + deck.nu)),
        GA_shear_strong=g * concrete,
        GA_shear_weak=g * tc,
        mass_per_area=deck.rho_c * concrete + deck.rho_s * steel,
        Ec=ec,
        nu=deck.nu,
    )


@dataclass(frozen=True)
class DeckLayer:
    """One layer of the equivalent shell: plate moduli in local x and y."""

    thickness: float
    Ex: float
    Ey: float
    Gxy: float
    Gzx: float
    Gyz: float
    vxy: float
    rho: float


def _face_and_core(
    axial: float, bending: float, a: float, c: float, z: float
) -> tuple[float, float]:
    """Face and core moduli giving ``axial = Σ E t`` and ``bending = Σ E t z²``."""
    face = bending / (2.0 * a * z * z)
    core = (axial - 2.0 * a * face) / c
    return face, core


def equivalent_thickness(props: DeckProperties) -> float:
    """Total thickness of the layered shell: the real depth, deeper only if it must be."""
    r2 = max(
        props.EI_strong / props.EA_strong,
        props.EI_weak / props.EA_weak,
        props.GI_twist / props.GA_inplane,
    )
    # The faces sit at z = (1 - a/h) h / 2; the core keeps a share of EA.
    z_needed = math.sqrt(r2 / (1.0 - _CORE_SHARE))
    return max(props.depth, z_needed / (0.5 * (1.0 - FACE_FRACTION)))


def deck_layers(props: DeckProperties, ribs_along: Literal["x", "y"] = "x") -> list[DeckLayer]:
    """The three layers (face, core, face) that reproduce ``props`` exactly."""
    h = equivalent_thickness(props)
    a = FACE_FRACTION * h
    c = h - 2.0 * a
    z = 0.5 * (h - a)
    strong = _face_and_core(props.EA_strong, props.EI_strong, a, c, z)
    weak = _face_and_core(props.EA_weak, props.EI_weak, a, c, z)
    shear = _face_and_core(props.GA_inplane, props.GI_twist, a, c, z)
    rho = props.mass_per_area / h
    # Out-of-plane shear: the same modulus through the thickness.
    g_strong, g_weak = props.GA_shear_strong / h, props.GA_shear_weak / h
    layers = []
    for k, thickness in ((0, a), (1, c), (0, a)):
        e1, e2 = strong[k], weak[k]
        ex, ey = (e1, e2) if ribs_along == "x" else (e2, e1)
        gzx, gyz = (g_strong, g_weak) if ribs_along == "x" else (g_weak, g_strong)
        layers.append(
            DeckLayer(
                thickness=thickness,
                Ex=ex,
                Ey=ey,
                Gxy=shear[k],
                Gzx=gzx,
                Gyz=gyz,
                vxy=props.nu * math.sqrt(ex / ey),
                rho=rho,
            )
        )
    return layers


def layered_stiffness(layers: list[DeckLayer]) -> dict[str, float]:
    """Strip ``EA``, ``EI`` and plate shear of ``layers`` as OpenSees integrates them.

    Mid-plane integration; the direct moduli are those of a strip with free
    edges (``Ex``, ``Ey``), as the targets are.
    """
    h = sum(layer.thickness for layer in layers)
    out = {"EAx": 0.0, "EAy": 0.0, "EIx": 0.0, "EIy": 0.0, "GA": 0.0, "GI": 0.0, "mass": 0.0}
    top = 0.5 * h
    for layer in layers:
        z = top - 0.5 * layer.thickness
        top -= layer.thickness
        qx, qy = layer.Ex, layer.Ey
        out["EAx"] += qx * layer.thickness
        out["EAy"] += qy * layer.thickness
        out["EIx"] += qx * layer.thickness * z * z
        out["EIy"] += qy * layer.thickness * z * z
        out["GA"] += layer.Gxy * layer.thickness
        out["GI"] += layer.Gxy * layer.thickness * z * z
        out["mass"] += layer.rho * layer.thickness
    return out


@dataclass(frozen=True)
class DeckModel:
    """What the wizard adds to the project: two materials per layer kind and the section."""

    materials: list[Any]
    section: LayeredShellSection
    properties: DeckProperties


def build_deck_model(
    deck: DeckInput,
    *,
    name: str,
    first_material_id: int,
    section_id: int,
    units: UnitSystem,
) -> DeckModel:
    """The orthotropic materials and the ``LayeredShell`` of ``deck``.

    Face and core each get an ``ElasticOrthotropic`` and the ``PlateFiber`` that
    wraps it (four materials from ``first_material_id``); the section's three
    layers are face, core, face.
    """
    props = deck_properties(deck)
    layers = deck_layers(props, deck.ribs_along)
    materials: list[Any] = []
    plate_ids: list[int] = []
    next_id = first_material_id
    for label, layer in (("face", layers[0]), ("core", layers[1])):
        ortho = ElasticOrthotropic(
            id=next_id,
            name=f"{name} {label}",
            Ex=layer.Ex,
            Ey=layer.Ey,
            Ez=max(layer.Ex, layer.Ey),
            vxy=layer.vxy,
            vyz=0.0,
            vzx=0.0,
            Gxy=layer.Gxy,
            Gyz=layer.Gyz,
            Gzx=layer.Gzx,
            rho=layer.rho,
        )
        plate = PlateFiberMaterial(
            id=next_id + 1, name=f"{name} {label} plate", material_id=next_id
        )
        materials += [ortho, plate]
        plate_ids.append(plate.id)
        next_id += 2
    h = sum(layer.thickness for layer in layers)
    section = LayeredShellSection(
        id=section_id,
        name=name,
        layers=[
            ShellLayer(material_id=plate_ids[0], thickness=layers[0].thickness),
            ShellLayer(material_id=plate_ids[1], thickness=layers[1].thickness),
            ShellLayer(material_id=plate_ids[0], thickness=layers[2].thickness),
        ],
        unit_weight=props.mass_per_area * gravity(units) / h,
    )
    return DeckModel(materials=materials, section=section, properties=props)


def deck_outline(deck: DeckInput, ribs: int = 2) -> list[tuple[float, float]]:
    """The concrete of ``ribs`` pitches as ``(y, z)`` points: y up from the sheet's bottom.

    The bottom edge follows the deck sheet; the ribs are centred in their pitch.
    """
    p, hr, tc = deck.pitch, deck.rib_height, deck.topping
    hb, ht = 0.5 * deck.rib_bottom, 0.5 * deck.rib_top
    points: list[tuple[float, float]] = [(hr, 0.0)]
    for k in range(ribs):
        mid = (k + 0.5) * p
        points += [(hr, mid - ht), (0.0, mid - hb), (0.0, mid + hb), (hr, mid + ht)]
    points += [(hr, ribs * p), (hr + tc, ribs * p), (hr + tc, 0.0)]
    return points


def profile_in_units(profile: DeckProfile, units: UnitSystem) -> dict[str, float]:
    """A preset's dimensions in the length unit of ``units``."""
    mm = length_scale(UnitSystem.SI_MM_N, units)
    return {
        "rib_height": profile.rib_height * mm,
        "pitch": profile.pitch * mm,
        "rib_bottom": profile.rib_bottom * mm,
        "rib_top": profile.rib_top * mm,
    }


def mm_in_units(value_mm: float, units: UnitSystem) -> float:
    """A length given in millimetres, in the length unit of ``units``."""
    return value_mm * length_scale(UnitSystem.SI_MM_N, units)


__all__ = [
    "DECK_GAUGES",
    "DECK_PROFILES",
    "DeckInput",
    "DeckLayer",
    "DeckModel",
    "DeckProfile",
    "DeckProperties",
    "build_deck_model",
    "deck_layers",
    "deck_outline",
    "deck_properties",
    "equivalent_thickness",
    "layered_stiffness",
    "mm_in_units",
    "profile_in_units",
]
