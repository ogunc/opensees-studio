"""core.section_materials: a section made of a material, and its shear areas."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    Node,
    Project,
    UnitSystem,
    make_default_section,
)
from opensees_studio.core.aisc import load_shapes, shape_to_elastic_section
from opensees_studio.core.default_materials import default_materials
from opensees_studio.core.materials import Concrete01, ElasticUniaxial, Steel02
from opensees_studio.core.section_materials import (
    elastic_constants,
    linkable_materials,
    linked,
    shear_areas,
    sync_material_links,
)
from opensees_studio.core.sections import (
    AngleShape,
    ElasticSection,
    PipeShape,
    RectShape,
    TeeShape,
    TubeShape,
    WideFlangeShape,
)
from opensees_studio.core.units import gravity


def _project(units: UnitSystem = UnitSystem.SI_M_N) -> Project:
    project = Project()
    project.meta.units = units
    project.materials.extend(default_materials(1, units))
    return project


def _material(project: Project, name: str):  # type: ignore[no-untyped-def]
    return next(m for m in project.materials if m.name == name)


def test_a_section_takes_e_g_and_weight_from_its_material() -> None:
    project = _project()
    steel = _material(project, "A572Gr50")
    section = linked(ElasticSection(id=1, E=1.0, A=0.01, Iz=1e-5), steel, project.meta.units)

    assert section.material_id == steel.id
    assert section.E == steel.E
    assert pytest.approx(steel.E / 2.6) == section.G  # nu = 0.3
    assert section.unit_weight == pytest.approx(steel.rho * gravity(UnitSystem.SI_M_N))
    assert section.unit_weight == pytest.approx(76_973.0, rel=1e-3)  # 490 lb/ft³ in N/m³


def test_changing_the_material_changes_its_sections() -> None:
    project = _project()
    steel = _material(project, "A36")
    project.sections.append(
        linked(ElasticSection(id=1, E=1.0, A=0.01, Iz=1e-5), steel, project.meta.units)
    )
    project.sections.append(ElasticSection(id=2, E=5.0, A=0.01, Iz=1e-5))  # no material

    index = project.materials.index(steel)
    project.materials[index] = steel.model_copy(update={"E": 100e9, "nu": 0.25})
    assert sync_material_links(project) == [1]

    assert project.sections[0].E == 100e9
    assert pytest.approx(40e9) == project.sections[0].G
    assert project.sections[1].E == 5.0
    assert sync_material_links(project) == []


def test_which_materials_can_make_a_section() -> None:
    units = UnitSystem.SI_M_N
    assert elastic_constants(ElasticUniaxial(id=1, E=3.0), units) == (3.0, None, None)
    steel02 = Steel02(id=2, Fy=345e6, E0=2e11, b=0.01, R0=18, cR1=0.925, cR2=0.15)
    assert elastic_constants(steel02, units) == (2e11, None, None)
    concrete = Concrete01(id=3, fpc=-28e6, epsc0=-0.002, fpcu=-6e6, epsU=-0.004)
    assert elastic_constants(concrete, units) is None
    project = _project()
    project.materials.append(concrete)
    assert concrete not in linkable_materials(project)
    assert len(linkable_materials(project)) == 9


def test_shear_areas_follow_the_profile_and_the_depth_axis() -> None:
    w = WideFlangeShape(d=0.4, bf=0.2, tw=0.01, tf=0.015)
    web, flanges = 0.4 * 0.01, 5 / 3 * 0.2 * 0.015
    assert shear_areas(w, 2) == pytest.approx((web, flanges))  # depth along local y
    assert shear_areas(w, 3) == pytest.approx((flanges, web))  # depth along local z
    assert shear_areas(RectShape(d=0.5, b=0.3), 2) == pytest.approx((0.125, 0.125))
    a = math.pi * (0.1**2 - 0.09**2)
    assert shear_areas(PipeShape(od=0.2, t=0.01), 3) == pytest.approx((a / 2, a / 2))
    assert shear_areas(TubeShape(d=0.3, b=0.2, t=0.01), 2) == pytest.approx((0.006, 0.004))
    assert shear_areas(TeeShape(d=0.2, bf=0.2, tw=0.01, tf=0.02), 2) == pytest.approx(
        (0.002, 5 / 6 * 0.004)
    )
    assert shear_areas(AngleShape(d=0.1, b=0.08, t=0.01), 2) == pytest.approx(
        (5 / 6 * 0.001, 5 / 6 * 0.0008)
    )


def test_the_section_picker_gives_aisc_shapes_their_shear_areas() -> None:
    w14 = load_shapes()["W14X30"]
    plain = shape_to_elastic_section(w14, elastic_modulus=29000.0, units=UnitSystem.US_IN_KIP)
    assert plain.As2 is None and plain.As3 is None  # scripts and tests keep their member
    with_areas = shape_to_elastic_section(
        w14,
        elastic_modulus=29000.0,
        shear_modulus=11200.0,
        units=UnitSystem.US_IN_KIP,
        ndm=2,
        with_shear_areas=True,
    )
    assert with_areas.As2 == pytest.approx(w14.d * w14.tw)
    assert with_areas.As3 == pytest.approx(5 / 3 * w14.bf * w14.tf)


def test_the_default_section_is_a572_with_zero_shear_areas() -> None:
    project = _project()
    section = make_default_section(1, project)
    assert section.material_id == _material(project, "A572Gr50").id
    assert (section.As2, section.As3) == (0.0, 0.0)
    assert not section.has_shear_deformation
    bare = make_default_section(1)
    assert bare.material_id is None
    assert bare.E == 200e9


def test_zero_shear_areas_and_no_material_save_as_before() -> None:
    old = ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5)
    assert {"material_id", "As2", "As3"}.isdisjoint(old.model_dump())
    zero = ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5, As2=0.0, As3=0.0)
    assert not zero.has_shear_deformation
    assert zero.model_dump()["As2"] == 0.0  # defined: the user gave 0


def test_which_members_run_without_shear_deformation() -> None:
    from opensees_studio.core.loads import (
        LinearTimeSeries,
        PlainLoadPattern,
        PointElementLoad,
        TrapezoidalElementLoad,
        UniformElementLoad,
    )
    from opensees_studio.core.section_materials import (
        frames_with_non_uniform_loads,
        shear_dropped_note,
    )

    project = _project()
    project.time_series = [LinearTimeSeries(id=1)]
    project.load_patterns = [
        PlainLoadPattern(
            id=1,
            time_series_id=1,
            element_loads=[UniformElementLoad(element_id=1, wy=-1.0)],
            point_loads=[PointElementLoad(element_id=2, py=-1.0, x=0.3)],
            distributed_loads=[
                # Full-length and constant: a uniform load, Timoshenko keeps it.
                TrapezoidalElementLoad(element_id=3, wy_start=-1.0, wy_end=-1.0),
                TrapezoidalElementLoad(
                    element_id=4, x_start=0.2, x_end=0.6, wy_start=-1.0, wy_end=-1.0
                ),
                TrapezoidalElementLoad(element_id=5, wy_start=0.0, wy_end=-2.0),
            ],
        )
    ]
    assert frames_with_non_uniform_loads(project) == {2, 4, 5}
    note = shear_dropped_note([5, 2, 4, 2])
    assert note.startswith("Element(s) 2, 4, 5:")
    assert "As2 = As3 = 0" in note


def test_a_missing_material_is_a_reference_problem() -> None:
    project = _project()
    project.nodes = [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))]
    project.sections = [ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5, material_id=99)]
    project.elements = [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)]
    with pytest.raises(ValueError, match="missing material 99"):
        project.validate_references()
