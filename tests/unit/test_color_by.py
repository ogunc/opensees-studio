"""View → Color By: categories and colours by section, material and group."""

from __future__ import annotations

from opensees_studio.core import (
    BeamWithHingesElement,
    ElasticBeamColumn,
    ElasticUniaxial,
    FiberSection,
    ForceBeamColumn,
    Node,
    Project,
    TrussElement,
    make_default_section,
)
from opensees_studio.core.color_by import PALETTE, element_categories
from opensees_studio.core.groups import Group
from opensees_studio.core.sections import Fibre
from opensees_studio.core.view_settings import ViewSettings

DEFAULT = "#338cd9"


def _project() -> Project:
    beam = make_default_section(1).model_copy(update={"name": "IPE"})
    return Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=i, coords=(float(i), 0.0, 0.0)) for i in range(1, 6)],
        materials=[
            ElasticUniaxial(id=1, name="steel", E=200e9),
            ElasticUniaxial(id=2, name="concrete", E=30e9),
        ],
        sections=[
            beam,
            FiberSection(
                id=2,
                name="RC",
                fibres=[
                    Fibre(y=0, z=0, area=0.1, material_id=2),
                    Fibre(y=0, z=0, area=1e-3, material_id=1),
                ],
            ),
        ],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ForceBeamColumn(id=2, nodes=(2, 3), section_id=2),
            TrussElement(id=3, nodes=(3, 4), area=0.01, material_id=1),
            BeamWithHingesElement(
                id=4,
                nodes=(4, 5),
                section_i_id=1,
                section_j_id=2,
                lp_i=0.2,
                lp_j=0.2,
                E=1.0,
                A=1.0,
                Iz=1.0,
            ),
        ],
        groups=[
            Group(id=1, name="Roof", element_ids=[1, 2], colour="#123456"),
            Group(id=2, name="Walls", element_ids=[2, 3], colour="#abcdef"),
        ],
    )


def test_by_section() -> None:
    cats = element_categories(_project(), "section", DEFAULT)
    label = {e: cats.labels[k] for e, k in cats.index.items()}
    assert label == {
        1: "#1 IPE",
        2: "#2 RC",
        3: "(no section)",
        4: "#1 IPE + #2 RC",
    }
    assert cats.colors[cats.index[3]] == DEFAULT
    assert cats.colors[cats.index[1]] in PALETTE
    assert cats.labels[-1] == "(no section)"  # the "none" category comes last


def test_by_material_follows_the_fibres() -> None:
    cats = element_categories(_project(), "material", DEFAULT)
    label = {e: cats.labels[k] for e, k in cats.index.items()}
    assert label[2] == "#1 steel + #2 concrete"
    assert label[3] == "#1 steel"
    assert label[1] == "(no material)"  # an elastic section carries none


def test_by_group_uses_the_first_group_and_its_colour() -> None:
    cats = element_categories(_project(), "group", DEFAULT)
    label = {e: cats.labels[k] for e, k in cats.index.items()}
    assert label == {1: "#1 Roof", 2: "#1 Roof", 3: "#2 Walls", 4: "(no group)"}
    assert cats.colors[cats.index[1]] == "#123456"
    assert cats.colors[cats.index[3]] == "#abcdef"
    assert cats.colors[cats.index[4]] == DEFAULT


def test_single_colour() -> None:
    cats = element_categories(_project(), "none", DEFAULT)
    assert cats.colors == [DEFAULT] and set(cats.index.values()) == {0}


def test_colours_do_not_shift_when_an_unrelated_element_is_added() -> None:
    project = _project()
    before = element_categories(project, "section", DEFAULT)
    project.elements.append(ElasticBeamColumn(id=9, nodes=(1, 5), section_id=1))
    after = element_categories(project, "section", DEFAULT)
    assert before.legend() == after.legend()


def test_the_setting_saves_byte_identical_when_unused() -> None:
    assert "color_by" not in ViewSettings().model_dump()
    assert ViewSettings().with_changes(color_by="group").model_dump()["color_by"] == "group"
