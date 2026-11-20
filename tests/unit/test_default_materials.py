"""core.default_materials: the steels, concretes and masonry of a new project."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import Project, UnitSystem
from opensees_studio.core.default_materials import (
    DEFAULT_MATERIAL_NAME,
    KSI,
    PCF,
    PSI,
    default_materials,
    find_default_material,
    missing_default_materials,
)
from opensees_studio.core.materials import ElasticIsotropic

NAMES = [
    "A36",
    "A572Gr50",
    "A992",
    "A500GrB",
    "A653SSGr33",
    "A653SSGr50",
    "4000Psi",
    "3000Psi",
    "CMU-Grouted1500",
]


def _by_name(units: UnitSystem) -> dict[str, ElasticIsotropic]:
    return {m.name: m for m in default_materials(1, units)}


def test_every_default_material_is_there_with_consecutive_ids() -> None:
    materials = default_materials(5, UnitSystem.SI_M_N)
    assert [m.name for m in materials] == NAMES
    assert [m.id for m in materials] == list(range(5, 5 + len(NAMES)))
    assert DEFAULT_MATERIAL_NAME == "A572Gr50"


def test_the_values_are_the_published_ones_in_si() -> None:
    m = _by_name(UnitSystem.SI_M_N)
    assert pytest.approx(29_000 * KSI) == m["A572Gr50"].E  # 199.95 GPa
    assert pytest.approx(199.948e9, rel=1e-5) == m["A572Gr50"].E
    assert m["A572Gr50"].Fy == pytest.approx(344.738e6, rel=1e-5)
    assert m["A572Gr50"].Fu == pytest.approx(65 * KSI)
    assert m["A36"].Fy == pytest.approx(36 * KSI)
    assert m["A500GrB"].Fy == pytest.approx(46 * KSI)
    assert pytest.approx(29_500 * KSI) == m["A653SSGr33"].E
    assert (m["A653SSGr33"].Fy, m["A653SSGr33"].Fu) == pytest.approx((33 * KSI, 45 * KSI))
    assert m["A572Gr50"].nu == 0.3
    assert m["A572Gr50"].rho == pytest.approx(490 * PCF)  # 7849 kg/m³
    assert m["A572Gr50"].fc is None

    # ACI 318 Eq. 19.2.2.1b: Ec = 57000 sqrt(f'c) psi.
    assert pytest.approx(57_000 * math.sqrt(4000) * PSI) == m["4000Psi"].E  # 24.86 GPa
    assert pytest.approx(24.856e9, rel=1e-4) == m["4000Psi"].E
    assert pytest.approx(21.526e9, rel=1e-4) == m["3000Psi"].E
    assert m["4000Psi"].fc == pytest.approx(4000 * PSI)
    assert (m["4000Psi"].nu, m["4000Psi"].rho) == pytest.approx((0.2, 150 * PCF))
    assert m["4000Psi"].Fy is None

    # TMS 402: Em = 900 f'm, Ev = 0.4 Em -> nu = 0.25; grouted block 140 lb/ft³.
    cmu = m["CMU-Grouted1500"]
    assert pytest.approx(900 * 1500 * PSI) == cmu.E
    assert (cmu.nu, cmu.fc, cmu.rho) == pytest.approx((0.25, 1500 * PSI, 140 * PCF))


def test_the_values_convert_to_the_project_units() -> None:
    m = _by_name(UnitSystem.US_IN_KIP)
    assert pytest.approx(29_000.0) == m["A572Gr50"].E  # ksi
    assert m["A572Gr50"].Fy == pytest.approx(50.0)
    assert m["4000Psi"].fc == pytest.approx(4.0)
    # 490 lb/ft³ as a mass density in kip·s²/in⁴: 0.490/1728 kip/in³ over g.
    assert m["A572Gr50"].rho == pytest.approx(0.490 / 1728 / 386.0886, rel=1e-4)
    mm = _by_name(UnitSystem.SI_MM_N)
    assert pytest.approx(199_948.0, rel=1e-5) == mm["A572Gr50"].E  # MPa


def test_an_older_project_is_topped_up_without_duplicates() -> None:
    project = Project()
    project.materials.append(ElasticIsotropic(id=1, name="A992", E=1.0, nu=0.3))
    missing = missing_default_materials(project, UnitSystem.SI_M_N)
    assert "A992" not in [m.name for m in missing]
    assert [m.id for m in missing] == list(range(2, 2 + len(NAMES) - 1))
    assert find_default_material(project) is None
    project.materials.extend(missing)
    assert find_default_material(project) is not None
    assert missing_default_materials(project, UnitSystem.SI_M_N) == []


def test_a_material_without_design_data_saves_as_before() -> None:
    plain = ElasticIsotropic(id=1, E=200e9, nu=0.3)
    assert set(plain.model_dump()) >= {"E", "nu", "rho"}
    assert {"Fy", "Fu", "fc"}.isdisjoint(plain.model_dump())
    steel = _by_name(UnitSystem.SI_M_N)["A36"]
    assert ElasticIsotropic.model_validate(steel.model_dump()) == steel
