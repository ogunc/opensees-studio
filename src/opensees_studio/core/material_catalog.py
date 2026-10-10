"""Typical construction materials: concrete, steel and masonry.

``data/typical_materials.csv`` carries 23 named materials an engineer reaches
for on most jobs — specified concrete strengths, the reinforcing-bar grades
ACI permits, the structural steels AISC tabulates, and masonry at the usual
specified strengths — each one tied to the clause it comes from and to the
OpenSees material the application will insert.

The table is SI: strengths in **MPa** and mass densities in **kg/m³**, the
units its sources publish in (or an exact conversion of them). Nothing is
converted behind the user's back: :func:`converted_parameters` takes the
project's unit system and returns the numbers that will actually be inserted,
and the picker shows the published value beside the converted one before
anything reaches the model.

Provenance, formulas and regeneration are in `data/README.md`; every derived
number is computed by ``tools/build_typical_materials.py`` and re-checked by
``tests/unit/test_material_catalog.py`` against the code equations.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from opensees_studio.core.materials import (
    Concrete01,
    ElasticIsotropic,
    ElasticUniaxial,
    Steel02,
)
from opensees_studio.core.units import (
    UnitSystem,
    density_scale,
    labels_for,
    mass_density_label,
    stress_scale,
)

#: Family code → the heading the picker shows, in display order.
FAMILY_LABELS: dict[str, str] = {
    "concrete": "Concrete",
    "rebar": "Reinforcing steel",
    "structural_steel": "Structural steel",
    "masonry": "Masonry",
}

#: The unit system the table is written in: MPa of stress, kg/m³ of density.
SOURCE_UNITS = UnitSystem.SI_M_N

#: OpenSees material name → the class that carries it into a project.
MODEL_CLASSES: dict[str, type[Any]] = {
    "Concrete01": Concrete01,
    "Steel02": Steel02,
    "ElasticIsotropic": ElasticIsotropic,
    "ElasticUniaxial": ElasticUniaxial,
}

#: What each model cannot be built without, in the table's own units.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "Concrete01": ("fpc_mpa", "epsc0", "fpcu_mpa", "eps_u"),
    "Steel02": ("fy_mpa", "e_mpa", "b", "r0", "cr1", "cr2"),
    "ElasticIsotropic": ("e_mpa", "nu", "rho_kg_m3"),
    "ElasticUniaxial": ("e_mpa",),
}

_DATA = Path(__file__).resolve().parents[1] / "data" / "typical_materials.csv"


class MaterialCatalogError(ValueError):
    """The table is inconsistent, or a material cannot be built from it."""


class TypicalMaterial(BaseModel):
    """One row of the library, in the units the table publishes."""

    model_config = ConfigDict(frozen=True)

    key: str
    family: str
    name: str
    standard: str
    """The clause the values come from, e.g. ``ACI 318-25 §19.2.2.1``."""
    model: str
    """OpenSees material name: ``Concrete01``, ``Steel02``, ``ElasticIsotropic`` …"""

    # Concrete (uniaxial, compression negative as the model wants it)
    fpc_mpa: float | None = None
    fpc_psi: float | None = None
    epsc0: float | None = None
    fpcu_mpa: float | None = None
    eps_u: float | None = None
    ec_mpa: float | None = None
    """Concrete modulus for information; ``Concrete01`` carries no modulus."""

    # Steel (uniaxial)
    fy_mpa: float | None = None
    fy_ksi: float | None = None
    fu_mpa: float | None = None
    fu_ksi: float | None = None
    e_mpa: float | None = None
    e_ksi: float | None = None
    b: float | None = None
    r0: float | None = None
    cr1: float | None = None
    cr2: float | None = None

    # Masonry (elastic isotropic)
    fm_mpa: float | None = None
    fm_psi: float | None = None
    em_mpa: float | None = None
    em_factor: float | None = None

    # Elastic isotropic, and every material that carries a mass density
    nu: float | None = None
    rho_kg_m3: float | None = None
    rho_pcf: float | None = None

    notes: str = ""

    @property
    def family_label(self) -> str:
        return FAMILY_LABELS.get(self.family, self.family)

    @property
    def is_complete(self) -> bool:
        """True when every field this material's model needs is present."""
        return all(getattr(self, name) is not None for name in REQUIRED_FIELDS.get(self.model, ()))


def _optional(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def _entry(row: dict[str, str]) -> TypicalMaterial:
    def value(column: str) -> float | None:
        return _optional(row.get(column, ""))

    return TypicalMaterial(
        key=row["key"].strip(),
        family=row["family"].strip(),
        name=row["name"].strip(),
        standard=row["standard"].strip(),
        model=row["model"].strip(),
        fpc_mpa=value("fpc_MPa"),
        fpc_psi=value("fpc_psi"),
        epsc0=value("epsc0"),
        fpcu_mpa=value("fpcu_MPa"),
        eps_u=value("epsU"),
        ec_mpa=value("Ec_MPa"),
        fy_mpa=value("Fy_MPa"),
        fy_ksi=value("Fy_ksi"),
        fu_mpa=value("Fu_MPa"),
        fu_ksi=value("Fu_ksi"),
        e_mpa=value("E_MPa"),
        e_ksi=value("E_ksi"),
        b=value("b"),
        r0=value("R0"),
        cr1=value("cR1"),
        cr2=value("cR2"),
        fm_mpa=value("fm_MPa"),
        fm_psi=value("fm_psi"),
        em_mpa=value("Em_MPa"),
        em_factor=value("Em_factor"),
        nu=value("nu"),
        rho_kg_m3=value("rho_kg_m3"),
        rho_pcf=value("rho_pcf"),
        notes=row.get("notes", "").strip(),
    )


@lru_cache(maxsize=1)
def load_materials() -> dict[str, TypicalMaterial]:
    """Every entry of the library, keyed by its stable ``key``.

    Raises:
        MaterialCatalogError: if the table names an unknown model or leaves a
            field that model needs empty — a broken data file must fail here
            rather than produce a wrong model.
    """
    with _DATA.open(encoding="utf-8", newline="") as handle:
        entries = {row["key"].strip(): _entry(row) for row in csv.DictReader(handle)}
    for key, entry in entries.items():
        if entry.model not in MODEL_CLASSES:
            raise MaterialCatalogError(f"{key}: unknown material model {entry.model!r}")
        if not entry.is_complete:
            missing = [
                name for name in REQUIRED_FIELDS[entry.model] if getattr(entry, name) is None
            ]
            raise MaterialCatalogError(f"{key}: {entry.model} needs {', '.join(missing)}")
    return entries


def families() -> list[str]:
    """Every family in the table, in the order the picker shows them."""
    present = {entry.family for entry in load_materials().values()}
    ordered = [family for family in FAMILY_LABELS if family in present]
    return ordered + sorted(present - set(ordered))


def materials_of(family: str) -> list[TypicalMaterial]:
    """The entries of one family, in table order."""
    return [entry for entry in load_materials().values() if entry.family == family]


def search(text: str) -> list[TypicalMaterial]:
    """Entries whose name, family, standard or key contains ``text`` (case-insensitive)."""
    needle = text.strip().lower()
    if not needle:
        return list(load_materials().values())
    return [
        entry
        for entry in load_materials().values()
        if needle in entry.name.lower()
        or needle in entry.family_label.lower()
        or needle in entry.standard.lower()
        or needle in entry.key.lower()
    ]


def _stress_mpa_to(value_mpa: float, units: UnitSystem) -> float:
    """Convert an MPa value to the project's stress unit.

    The table's system is MPa, i.e. ``1e6`` of the Pa that
    :func:`~opensees_studio.core.units.stress_scale` converts from.
    """
    return value_mpa * 1e6 * stress_scale(SOURCE_UNITS, units)


def _density_to(value_kg_m3: float, units: UnitSystem) -> float:
    """Convert a kg/m³ value to the project's coherent mass density unit."""
    return value_kg_m3 * density_scale(SOURCE_UNITS, units)


def converted_parameters(entry: TypicalMaterial, units: UnitSystem) -> dict[str, float]:
    """The constructor arguments for ``entry`` as the project's own numbers.

    Strengths and moduli convert as stresses, densities as mass per volume; the
    strains and the dimensionless parameters (``b``, ``nu``, ``R0`` …) are just
    carried across. The keys are the model's arguments, so the caller can build
    the material with ``MODEL_CLASSES[entry.model](id=…, name=…, **values)``.
    """
    if entry.model not in MODEL_CLASSES:
        raise MaterialCatalogError(f"{entry.key}: unknown material model {entry.model!r}")
    if not entry.is_complete:
        raise MaterialCatalogError(f"{entry.key}: incomplete row for {entry.model}")

    def stress(value: float | None) -> float:
        assert value is not None  # guarded by is_complete
        return _stress_mpa_to(value, units)

    if entry.model == "Concrete01":
        # The sign comes from `inserted_value` (Concrete01 wants compression
        # negative); the strains in the table are already negative.
        return {
            "fpc": inserted_value(entry, "fpc_mpa", units)[0],
            "epsc0": float(entry.epsc0 or 0.0),
            "fpcu": inserted_value(entry, "fpcu_mpa", units)[0],
            "epsU": float(entry.eps_u or 0.0),
        }
    if entry.model == "Steel02":
        return {
            "Fy": stress(entry.fy_mpa),
            "E0": stress(entry.e_mpa),
            "b": float(entry.b or 0.0),
            "R0": float(entry.r0 or 0.0),
            "cR1": float(entry.cr1 or 0.0),
            "cR2": float(entry.cr2 or 0.0),
        }
    if entry.model == "ElasticIsotropic":
        assert entry.rho_kg_m3 is not None
        return {
            "E": stress(entry.e_mpa),
            "nu": float(entry.nu or 0.0),
            "rho": _density_to(entry.rho_kg_m3, units),
        }
    return {"E": stress(entry.e_mpa)}  # ElasticUniaxial


def to_material(
    entry: TypicalMaterial,
    material_id: int,
    units: UnitSystem,
    name: str | None = None,
) -> Any:
    """Build the project material ``entry`` describes, in the project's units."""
    cls = MODEL_CLASSES.get(entry.model)
    if cls is None:
        raise MaterialCatalogError(f"{entry.key}: unknown material model {entry.model!r}")
    return cls(
        id=material_id,
        name=name if name is not None else entry.name,
        **converted_parameters(entry, units),
    )


#: Which parameter the picker lists, per model, as ``(label, attribute)``.
_LISTED_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "Concrete01": (
        ("f'c", "fpc_mpa"),
        ("εc0", "epsc0"),
        ("f'cu", "fpcu_mpa"),
        ("εcu", "eps_u"),
        ("Ec (for information)", "ec_mpa"),
        ("ρ", "rho_kg_m3"),
    ),
    "Steel02": (
        ("Fy", "fy_mpa"),
        ("Fu", "fu_mpa"),
        ("E", "e_mpa"),
        ("b", "b"),
        ("R0", "r0"),
    ),
    "ElasticIsotropic": (("E", "e_mpa"), ("ν", "nu"), ("ρ", "rho_kg_m3")),
    "ElasticUniaxial": (("E", "e_mpa"),),
}

#: How each listed parameter converts: as a stress, as a density, or not at all.
_PARAMETER_KIND: dict[str, str] = {
    "fpc_mpa": "stress",
    "fpcu_mpa": "stress",
    "ec_mpa": "stress",
    "fy_mpa": "stress",
    "fu_mpa": "stress",
    "e_mpa": "stress",
    "fm_mpa": "stress",
    "em_mpa": "stress",
    "rho_kg_m3": "density",
    "epsc0": "plain",
    "eps_u": "plain",
    "b": "plain",
    "r0": "plain",
    "nu": "plain",
}

#: The unit the table itself publishes each parameter in.
_PUBLISHED_UNIT: dict[str, str] = {
    "stress": "MPa",
    "density": "kg/m³",
    "plain": "",
}


def listed_values(entry: TypicalMaterial) -> list[tuple[str, float | None]]:
    """The ``(label, published value)`` pairs the picker shows for ``entry``.

    Published means the table's own units: MPa for stresses, kg/m³ for
    densities, and the dimensionless numbers as they are.
    """
    return [(label, getattr(entry, attribute)) for label, attribute in _LISTED_FIELDS[entry.model]]


#: Parameters a model stores with the opposite sign to the published one.
_NEGATED_BY_MODEL: dict[str, frozenset[str]] = {
    # Concrete01 takes compression as a negative stress, while ACI publishes a
    # positive specified strength.
    "Concrete01": frozenset({"fpc_mpa", "fpcu_mpa"}),
}


def inserted_value(entry: TypicalMaterial, attribute: str, units: UnitSystem) -> tuple[float, str]:
    """``(value as it enters the model, unit label)`` for one listed parameter.

    The single place that knows both the conversions and the sign conventions:
    stresses and moduli convert as stresses, densities as mass per volume, and
    a parameter in :data:`_NEGATED_BY_MODEL` arrives with a minus sign.
    """
    value = getattr(entry, attribute)
    if value is None:
        raise MaterialCatalogError(f"{entry.key}: no {attribute}")
    sign = -1.0 if attribute in _NEGATED_BY_MODEL.get(entry.model, frozenset()) else 1.0
    kind = _PARAMETER_KIND[attribute]
    if kind == "stress":
        return sign * _stress_mpa_to(value, units), labels_for(units).stress
    if kind == "density":
        return _density_to(value, units), mass_density_label(units)
    return sign * value, ""


def preview_rows(entry: TypicalMaterial, units: UnitSystem) -> list[tuple[str, str, str]]:
    """``(parameter, published value, value to insert)`` rows for the picker.

    Text is formatted here so the dialog, the tests and any future export all
    read the same numbers with the same unit labels.
    """
    rows: list[tuple[str, str, str]] = []
    for label, attribute in _LISTED_FIELDS[entry.model]:
        published = getattr(entry, attribute)
        if published is None:
            continue
        converted, unit = inserted_value(entry, attribute, units)
        published_unit = _PUBLISHED_UNIT[_PARAMETER_KIND[attribute]]
        rows.append(
            (
                label,
                f"{published:.6g} {published_unit}".strip(),
                f"{converted:.6g} {unit}".strip(),
            )
        )
    return rows


def unit_note(entry: TypicalMaterial) -> str:
    """One line naming the published unit of each listed parameter."""
    parts = []
    for label, attribute in _LISTED_FIELDS[entry.model]:
        if getattr(entry, attribute) is None:
            continue
        unit = _PUBLISHED_UNIT[_PARAMETER_KIND[attribute]]
        parts.append(f"{label} [{unit}]" if unit else f"{label} [—]")
    return "Published: " + ", ".join(parts)


def field_summary(entry: TypicalMaterial) -> str:
    """A one-line, unit-free summary of the entry, for the picker's list."""
    if entry.model == "Concrete01":
        return f"f'c = {entry.fpc_mpa:.4g} MPa, Ec ≈ {entry.ec_mpa:.4g} MPa"
    if entry.model == "Steel02":
        fu = f", Fu = {entry.fu_mpa:.4g} MPa" if entry.fu_mpa else ""
        return f"Fy = {entry.fy_mpa:.4g} MPa{fu}, E = {entry.e_mpa:.4g} MPa"
    if entry.model == "ElasticIsotropic":
        return (
            f"f'm = {entry.fm_mpa:.4g} MPa, Em = {entry.em_mpa:.4g} MPa "
            f"({entry.em_factor:.0f} f'm), ρ = {entry.rho_kg_m3:.4g} kg/m³"
        )
    return f"E = {entry.e_mpa:.4g} MPa"


__all__ = [
    "FAMILY_LABELS",
    "MODEL_CLASSES",
    "SOURCE_UNITS",
    "MaterialCatalogError",
    "TypicalMaterial",
    "converted_parameters",
    "families",
    "field_summary",
    "inserted_value",
    "listed_values",
    "load_materials",
    "materials_of",
    "preview_rows",
    "search",
    "to_material",
    "unit_note",
]
