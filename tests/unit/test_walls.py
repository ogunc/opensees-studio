"""RC wall macro-elements (MVLEM): fibres, validation, members to walls."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticUniaxial,
    MVLEMElement,
    Node,
    Project,
    wall_fibres,
)
from opensees_studio.core.geometry.walls import WallSpec, walls_from_members


def _wall(**overrides) -> MVLEMElement:  # type: ignore[no-untyped-def]
    widths, ratios = wall_fibres(1.0, 4, web_ratio=0.003)
    values = {
        "id": 1,
        "nodes": (1, 2),
        "thicknesses": (0.2,) * 4,
        "widths": widths,
        "steel_ratios": ratios,
        "concrete_material_ids": (1,) * 4,
        "steel_material_ids": (2,) * 4,
        "shear_material_id": 3,
    }
    values.update(overrides)
    return MVLEMElement(**values)


def test_uniform_fibres() -> None:
    widths, ratios = wall_fibres(2.0, 8, web_ratio=0.0025)
    assert widths == pytest.approx((0.25,) * 8)
    assert ratios == (0.0025,) * 8


def test_boundary_elements_take_their_own_ratio() -> None:
    widths, ratios = wall_fibres(3.0, 10, boundary_length=0.3, web_ratio=0.003, boundary_ratio=0.02)
    assert sum(widths) == pytest.approx(3.0)
    assert ratios[0] == ratios[-1] == 0.02
    assert ratios[len(ratios) // 2] == 0.003
    assert widths[0] == pytest.approx(0.3)
    with pytest.raises(ValueError):
        wall_fibres(1.0, 8, boundary_length=0.6, web_ratio=0.0)
    with pytest.raises(ValueError):
        wall_fibres(1.0, 1, web_ratio=0.0)


def test_opensees_arguments_in_order() -> None:
    args = _wall().opensees_args()
    assert args[:5] == [0.0, 1, 2, 4, 0.4]
    assert args[5] == "-thick" and args[10] == "-width"
    assert args[-2:] == ["-matShear", 3]
    assert _wall().length == pytest.approx(1.0)


def test_one_value_per_fibre() -> None:
    with pytest.raises(ValueError, match="per fibre"):
        _wall(thicknesses=(0.2,) * 3)
    with pytest.raises(ValueError, match="between 0 and 1"):
        _wall(steel_ratios=(1.5,) * 4)


def _frame_project(ndm: int = 2) -> Project:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(0.0, 0.0, 3.0)),
        Node(id=3, coords=(0.0, 0.0, 4.5)),
        Node(id=4, coords=(4.0, 0.0, 4.5)),
    ]
    elements = [
        ElasticBeamColumn(id=1, nodes=(2, 1), section_id=1),  # top to bottom: reordered
        ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ElasticBeamColumn(id=3, nodes=(3, 4), section_id=1),  # a beam: skipped
    ]
    materials = [ElasticUniaxial(id=1, E=30e9), ElasticUniaxial(id=2, E=200e9)]
    return Project(
        ndm=ndm, ndf=3 if ndm == 2 else 6, nodes=nodes, elements=elements, materials=materials
    )


def test_members_become_walls_with_a_shear_spring_per_height() -> None:
    project = _frame_project()
    spec = WallSpec(
        length=1.0,
        thickness=0.2,
        fibres=8,
        concrete_material_id=1,
        steel_material_id=2,
        web_ratio=0.003,
        shear_modulus=12.5e9,
    )
    out = walls_from_members(project, {1, 2, 3}, spec, first_material_id=10)
    assert [e.id for e in out.elements] == [1, 2]
    assert out.skipped == [3]
    assert out.elements[0].nodes == (1, 2)  # bottom first
    stiffness = {m.id: m.E for m in out.materials}  # type: ignore[attr-defined]
    assert stiffness == pytest.approx({10: 12.5e9 * 0.2 / 3.0, 11: 12.5e9 * 0.2 / 1.5})
    assert out.elements[1].shear_material_id == 11


def test_an_existing_shear_material_is_shared() -> None:
    spec = WallSpec(
        length=1.0,
        thickness=0.2,
        fibres=4,
        concrete_material_id=1,
        steel_material_id=2,
        web_ratio=0.0,
        shear_material_id=2,
    )
    out = walls_from_members(_frame_project(), {1, 2}, spec, first_material_id=10)
    assert not out.materials
    assert {e.shear_material_id for e in out.elements} == {2}
    with pytest.raises(ValueError, match="either"):
        walls_from_members(
            _frame_project(),
            {1},
            WallSpec(
                length=1,
                thickness=0.2,
                fibres=4,
                concrete_material_id=1,
                steel_material_id=2,
                web_ratio=0,
            ),
            first_material_id=10,
        )


def test_walls_need_a_2d_model() -> None:
    project = _frame_project(ndm=3)
    project.materials.append(ElasticUniaxial(id=3, E=1e9))
    project.elements[0] = _wall(id=1, nodes=(1, 2))
    with pytest.raises(ValueError, match="2D model"):
        project.validate_references()
