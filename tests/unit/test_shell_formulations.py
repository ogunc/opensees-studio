"""Shell formulations: DKGQ/NLDKGQ quads and DKGT triangles behave as shells everywhere."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    SHELL_ELEMENT_CLASSES,
    ElasticMembranePlateSection,
    Node,
    PlainLoadPattern,
    Project,
    ShellDKGQElement,
    ShellDKGTElement,
    ShellMITC4Element,
    ShellNLDKGTElement,
    SurfaceLoad,
    with_shell_formulation,
)
from opensees_studio.core.area_loads import face_shape_products, surface_nodal_loads
from opensees_studio.core.model_check import check_model
from opensees_studio.core.self_weight import nodal_self_weight_loads

SQUARE = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]


def _project(elements: list, fixed: bool = True) -> Project:
    restraint = (True,) * 6
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(
                id=i,
                coords=(x, y, 0.0),
                restraint=restraint if fixed and i in (1, 2) else (False,) * 6,
            )
            for i, (x, y) in enumerate(SQUARE, 1)
        ],
        sections=[ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2, unit_weight=25e3)],
        elements=elements,
    )


def test_a_dkgq_shell_is_a_shell_and_round_trips() -> None:
    shell = ShellDKGQElement(id=1, nodes=(1, 2, 3, 4), section_id=1)
    assert isinstance(shell, ShellMITC4Element)
    project = _project([shell])
    again = Project.model_validate_json(project.model_dump_json())
    assert type(again.elements[0]) is ShellDKGQElement
    assert '"ShellDKGQ"' in project.model_dump_json()


def test_a_mitc4_shell_still_saves_as_before() -> None:
    assert (
        '"type":"ShellMITC4"'
        in ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1).model_dump_json()
    )


def test_switching_formulation_keeps_id_nodes_and_section() -> None:
    quad = ShellMITC4Element(id=7, nodes=(1, 2, 3, 4), section_id=3)
    dkgq = with_shell_formulation(quad, "ShellNLDKGQ")
    assert (dkgq.type, dkgq.id, dkgq.nodes, dkgq.section_id) == ("ShellNLDKGQ", 7, (1, 2, 3, 4), 3)
    tri = ShellDKGTElement(id=8, nodes=(1, 2, 3), section_id=3)
    assert isinstance(with_shell_formulation(tri, "ShellNLDKGT"), ShellNLDKGTElement)
    with pytest.raises(ValueError, match="quadrilateral"):
        with_shell_formulation(quad, "ShellDKGT")
    with pytest.raises(ValueError, match="triangular"):
        with_shell_formulation(tri, "ShellDKGQ")


def test_a_pressure_on_two_triangles_equals_the_one_on_the_square() -> None:
    quad = _project([ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)])
    tris = _project(
        [
            ShellDKGTElement(id=1, nodes=(1, 2, 3), section_id=1),
            ShellDKGTElement(id=2, nodes=(1, 3, 4), section_id=1),
        ]
    )

    def total(p: Project) -> float:
        loads = [SurfaceLoad(element_id=e.id, value=-5.0, direction="Z") for e in p.elements]
        return float(sum(v[2] for v in surface_nodal_loads(p, loads).values()))

    assert total(quad) == pytest.approx(-20.0)
    assert total(tris) == pytest.approx(-20.0)


def test_triangle_shape_products_sum_to_a_third_of_the_area() -> None:
    points = np.array([(0, 0, 0), (2, 0, 0), (0, 3, 0)], dtype=float)
    products = face_shape_products(points)
    assert products.sum(axis=1) == pytest.approx([1.0, 1.0, 1.0])  # area 3, a third each
    assert products.sum() == pytest.approx(3.0)


def test_self_weight_of_triangles_matches_the_square() -> None:
    tris = _project(
        [
            ShellDKGTElement(id=1, nodes=(1, 2, 3), section_id=1),
            ShellDKGTElement(id=2, nodes=(1, 3, 4), section_id=1),
        ]
    )
    total = sum(v[2] for v in nodal_self_weight_loads(tris).values())
    assert total == pytest.approx(-25e3 * 0.2 * 4.0)


def test_a_triangle_held_at_two_nodes_turns_about_them_and_three_is_enough() -> None:
    def tri(fix: set[int]) -> Project:
        return Project(
            ndm=3,
            ndf=6,
            nodes=[
                Node(
                    id=i,
                    coords=(x, y, 0.0),
                    restraint=(True, True, True, False, False, False) if i in fix else (False,) * 6,
                )
                for i, (x, y) in enumerate(SQUARE[:3], 1)
            ],
            sections=[ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2)],
            elements=[ShellDKGTElement(id=1, nodes=(1, 2, 3), section_id=1)],
        )

    assert check_model(tri({1, 2})).mechanism_count >= 1
    assert check_model(tri({1, 2, 3})).mechanism_count == 0


def test_every_shell_class_is_listed() -> None:
    assert ShellDKGTElement in SHELL_ELEMENT_CLASSES
    assert issubclass(ShellDKGQElement, SHELL_ELEMENT_CLASSES)
    assert PlainLoadPattern  # imported for the surface-load model
