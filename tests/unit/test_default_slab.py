"""The default 20 cm slab of 4000 psi concrete that a drawn shell gets."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    DEFAULT_SLAB_NAME,
    ElasticMembranePlateSection,
    Project,
    UnitSystem,
    ensure_default_slab_section,
    find_default_slab_section,
    make_default_slab_section,
)
from opensees_studio.core.default_materials import PSI, default_materials
from opensees_studio.core.units import gravity


def test_the_default_slab_is_20_cm_of_4000_psi_concrete() -> None:
    project = Project(ndm=3, ndf=6)
    section = make_default_slab_section(1, project)
    assert isinstance(section, ElasticMembranePlateSection)
    assert section.name == DEFAULT_SLAB_NAME
    assert section.h == pytest.approx(0.20)
    assert pytest.approx(57000 * 4000**0.5 * PSI) == section.E
    assert section.nu == 0.2
    assert section.unit_weight == pytest.approx(section.rho * gravity(UnitSystem.SI_M_N))


@pytest.mark.parametrize(
    ("units", "h"),
    [(UnitSystem.SI_MM_N, 200.0), (UnitSystem.MKS_CM_KGF, 20.0), (UnitSystem.US_IN_KIP, 7.874)],
)
def test_the_slab_follows_the_project_units(units: UnitSystem, h: float) -> None:
    project = Project(ndm=3, ndf=6)
    project.meta.units = units
    project.materials.extend(default_materials(1, units))
    concrete = next(m for m in project.materials if m.name == "4000Psi")
    section = make_default_slab_section(1, project)
    assert section.h == pytest.approx(h, rel=1e-4)
    assert section.E == concrete.E
    assert section.rho == concrete.rho


def test_the_project_concrete_is_used_when_it_has_one() -> None:
    project = Project(ndm=3, ndf=6)
    project.materials.extend(default_materials(1, UnitSystem.SI_M_N))
    concrete = next(m for m in project.materials if m.name == "4000Psi")
    project.materials[project.materials.index(concrete)] = concrete.model_copy(update={"E": 1e10})
    assert make_default_slab_section(1, project).E == 1e10


def test_ensure_adds_the_slab_once() -> None:
    project = Project(ndm=3, ndf=6)
    assert find_default_slab_section(project) is None
    first = ensure_default_slab_section(project)
    assert ensure_default_slab_section(project) is first
    assert len(project.sections) == 1
