"""The materials every new project starts with, as SAP2000 starts with its own.

File → New (and New Model, the frame and truss wizards) gives the project the
materials an engineer reaches for first, so a section can be given a material
without a trip to the library:

=================  ====================================  ====================
Name               What                                  Source
=================  ====================================  ====================
A36                ASTM A36, Fy 36 / Fu 58 ksi           AISC 360 Table 2-4
A572Gr50           ASTM A572 Gr. 50, Fy 50 / Fu 65 ksi   AISC 360 Table 2-4
A992               ASTM A992, Fy 50 / Fu 65 ksi          AISC 360 Table 2-4
A500GrB            ASTM A500 Gr. B (rectangular HSS),    AISC 360 Table 2-4
                   Fy 46 / Fu 58 ksi
A653SSGr33         ASTM A653 SS Gr. 33 sheet,            AISI S100 Table A3.1
                   Fy 33 / Fu 45 ksi
A653SSGr50         ASTM A653 SS Gr. 50 Class 1 sheet,    AISI S100 Table A3.1
                   Fy 50 / Fu 65 ksi
4000Psi            Normal-weight concrete, f'c 4000 psi  ACI 318 Eq. 19.2.2.1b
3000Psi            Normal-weight concrete, f'c 3000 psi  ACI 318 Eq. 19.2.2.1b
CMU-Grouted1500    Fully grouted concrete block,         TMS 402 §4.2.2
                   f'm 1500 psi
=================  ====================================  ====================

Values are written in US units, as the standards publish them, and converted
to the project's units when the project is made:

* hot-rolled steel E = 29000 ksi, sheet steel (AISI) E = 29500 ksi; ν = 0.3;
  490 lb/ft³;
* concrete Ec = 57000 √f'c (psi, ACI 318 Eq. 19.2.2.1b); ν = 0.2; 150 lb/ft³;
* masonry Em = 900 f'm (concrete units, TMS 402 §4.2.2); Ev = 0.4 Em, so
  ν = 0.25; 140 lb/ft³, the weight of fully grouted normal-weight block.

They are ``ElasticIsotropic`` materials: E, ν and the mass density are what an
elastic section needs (its G and its weight come from them), and the strengths
ride along as design data (``Fy``, ``Fu``, ``fc``). :data:`DEFAULT_MATERIAL_NAME`
is the application's default: a section or a drawn member with nothing else
chosen gets A572 Gr. 50.

No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from opensees_studio.core.materials import ElasticIsotropic
from opensees_studio.core.units import UnitSystem, density_scale, stress_scale

#: The material a new section or drawn member takes when nothing else is chosen.
DEFAULT_MATERIAL_NAME = "A572Gr50"

#: One ksi and one psi in pascals; one lb/ft³ in kg/m³ (all exact).
KSI = 6_894_757.293168361
PSI = KSI / 1000.0
PCF = 16.018463373960138

_E_HOT_ROLLED_KSI = 29_000.0
_E_SHEET_KSI = 29_500.0
_STEEL_PCF = 490.0
_CONCRETE_PCF = 150.0
_GROUTED_CMU_PCF = 140.0


@dataclass(frozen=True)
class DefaultMaterial:
    """One default material, in the units its standard publishes."""

    name: str
    family: str
    """``"steel"``, ``"cold_formed"``, ``"concrete"`` or ``"masonry"``."""
    e_psi: float
    nu: float
    unit_weight_pcf: float
    fy_ksi: float | None = None
    fu_ksi: float | None = None
    fc_psi: float | None = None
    source: str = ""


def _steel(name: str, fy: float, fu: float, source: str) -> DefaultMaterial:
    return DefaultMaterial(
        name, "steel", _E_HOT_ROLLED_KSI * 1000.0, 0.3, _STEEL_PCF, fy, fu, None, source
    )


def _sheet(name: str, fy: float, fu: float) -> DefaultMaterial:
    return DefaultMaterial(
        name,
        "cold_formed",
        _E_SHEET_KSI * 1000.0,
        0.3,
        _STEEL_PCF,
        fy,
        fu,
        None,
        "ASTM A653 structural steel (SS) sheet; AISI S100 Table A3.1, E = 29500 ksi",
    )


def _concrete(fc_psi: float) -> DefaultMaterial:
    return DefaultMaterial(
        f"{fc_psi:.0f}Psi",
        "concrete",
        57_000.0 * math.sqrt(fc_psi),
        0.2,
        _CONCRETE_PCF,
        None,
        None,
        fc_psi,
        "Normal-weight concrete; Ec = 57000 sqrt(f'c), ACI 318 Eq. 19.2.2.1b",
    )


#: Every default material, in the order the project lists them.
DEFAULT_MATERIALS: tuple[DefaultMaterial, ...] = (
    _steel("A36", 36.0, 58.0, "ASTM A36; AISC 360 Table 2-4"),
    _steel("A572Gr50", 50.0, 65.0, "ASTM A572 Gr. 50; AISC 360 Table 2-4"),
    _steel("A992", 50.0, 65.0, "ASTM A992; AISC 360 Table 2-4"),
    _steel("A500GrB", 46.0, 58.0, "ASTM A500 Gr. B, rectangular HSS; AISC 360 Table 2-4"),
    _sheet("A653SSGr33", 33.0, 45.0),
    _sheet("A653SSGr50", 50.0, 65.0),
    _concrete(4000.0),
    _concrete(3000.0),
    DefaultMaterial(
        "CMU-Grouted1500",
        "masonry",
        900.0 * 1500.0,
        0.25,
        _GROUTED_CMU_PCF,
        None,
        None,
        1500.0,
        "Fully grouted normal-weight concrete block; Em = 900 f'm, Ev = 0.4 Em, TMS 402 §4.2.2",
    ),
)


def build_material(entry: DefaultMaterial, material_id: int, units: UnitSystem) -> ElasticIsotropic:
    """``entry`` as a project material, in the project's ``units``."""
    stress = stress_scale(UnitSystem.SI_M_N, units)  # Pa → the project's stress
    density = density_scale(UnitSystem.SI_M_N, units)  # kg/m³ → the project's
    return ElasticIsotropic(
        id=material_id,
        name=entry.name,
        E=entry.e_psi * PSI * stress,
        nu=entry.nu,
        rho=entry.unit_weight_pcf * PCF * density,
        Fy=entry.fy_ksi * KSI * stress if entry.fy_ksi is not None else None,
        Fu=entry.fu_ksi * KSI * stress if entry.fu_ksi is not None else None,
        fc=entry.fc_psi * PSI * stress if entry.fc_psi is not None else None,
    )


def default_materials(first_id: int, units: UnitSystem) -> list[ElasticIsotropic]:
    """Every default material with ids from ``first_id``, in the project's ``units``."""
    return [
        build_material(entry, first_id + index, units)
        for index, entry in enumerate(DEFAULT_MATERIALS)
    ]


def missing_default_materials(project: object, units: UnitSystem) -> list[ElasticIsotropic]:
    """The default materials ``project`` has no material of the same name for.

    Ids continue after the project's own, so a project can be topped up
    (Define → Materials → Add Default Materials) without touching what it has.
    """
    have = {getattr(m, "name", "") for m in getattr(project, "materials", [])}
    next_id = project.next_material_id()  # type: ignore[attr-defined]
    wanted = [entry for entry in DEFAULT_MATERIALS if entry.name not in have]
    return [build_material(entry, next_id + k, units) for k, entry in enumerate(wanted)]


def find_default_material(project: object) -> ElasticIsotropic | None:
    """The project's A572 Gr. 50, the application's default material, if it has one."""
    for material in getattr(project, "materials", []):
        if isinstance(material, ElasticIsotropic) and material.name == DEFAULT_MATERIAL_NAME:
            return material
    return None


__all__ = [
    "DEFAULT_MATERIALS",
    "DEFAULT_MATERIAL_NAME",
    "DefaultMaterial",
    "build_material",
    "default_materials",
    "find_default_material",
    "missing_default_materials",
]
