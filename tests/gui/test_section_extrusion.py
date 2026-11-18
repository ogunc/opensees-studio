"""Smoke tests for the Show Extruded Sections overlay."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
)


def _frame_project() -> Project:
    # Rectangular section 0.3×0.5 m.
    b, h = 0.30, 0.50
    A = b * h
    Iz = b * h**3 / 12.0
    Iy = h * b**3 / 12.0
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, True, True, True, True)),
            Node(id=2, coords=(6.0, 0.0, 0.0)),
        ],
        sections=[
            ElasticSection(
                id=1,
                name="Rect",
                E=200e9,
                A=A,
                Iz=Iz,
                Iy=Iy,
                G=80e9,
                J=1e-6,
            )
        ],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ],
    )


@pytest.mark.gui
def test_toggle_creates_and_removes_extrusion_actor(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_frame_project())

    before = len(canvas._renderer._aux_actors)
    canvas.set_show_section_extrusions(True)
    after_on = len(canvas._renderer._aux_actors)
    assert after_on > before, "Extrusion actor should appear after toggling on"

    canvas.set_show_section_extrusions(False)
    after_off = len(canvas._renderer._aux_actors)
    assert after_off == before, "Extrusion actor must disappear when toggled off"


@pytest.mark.gui
def test_a_truss_is_drawn_as_the_bar_of_its_area(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import ElasticUniaxial, TrussElement
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    p = Project(
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True, True, True, True, True, True)),
            Node(id=2, coords=(3, 0, 0)),
        ],
        materials=[ElasticUniaxial(id=1, E=200e9)],
        elements=[
            TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1),
        ],
    )
    canvas.show_project(p)
    before = len(canvas._renderer._aux_actors)
    canvas.set_show_section_extrusions(True)
    assert len(canvas._renderer._aux_actors) == before + 2


def test_a_template_is_closed_and_follows_the_member() -> None:
    import numpy as np

    from opensees_studio.core.aisc import get_shape, shape_hint
    from opensees_studio.core.section_outline import hint_regions
    from opensees_studio.views.canvas3d.extrusion import SweptMeshes, build_template

    hint = shape_hint(get_shape("HSS10X10X1_2"))
    assert hint is not None
    template = build_template(hint_regions(hint, 3))
    assert template is not None

    swept = SweptMeshes.empty()
    rotation = np.column_stack([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
    origin = np.array([1.0, 2.0, 3.0])
    swept.add(template, origin, rotation, 4.0)
    swept.add(template, origin + 10.0, rotation, 4.0)
    meshes = swept.meshes()
    assert meshes is not None
    surface, outline = meshes
    # A tube: no open edge anywhere, a hole through it, and it runs from z=3 to z=7.
    edges = surface.clean().extract_feature_edges(
        boundary_edges=True, feature_edges=False, manifold_edges=False, non_manifold_edges=False
    )
    assert edges.n_cells == 0
    assert surface.n_cells == 2 * template.n_faces
    assert outline.n_cells == 2 * template.n_edges
    first = surface.extract_cells(range(template.n_faces))
    assert first.bounds[4:6] == pytest.approx((3.0, 7.0))
    assert first.bounds[0:2] == pytest.approx((1.0 - 5.0, 1.0 + 5.0))
