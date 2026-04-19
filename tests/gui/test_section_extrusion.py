"""Smoke tests for the Show Extruded Sections overlay."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
)


def _frame_project() -> Project:
    # Rectangular section 0.3×0.5 m.
    b, h = 0.30, 0.50
    A = b * h
    Iz = b * h ** 3 / 12.0
    Iy = h * b ** 3 / 12.0
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0),
                 restraint=(True, True, True, True, True, True)),
            Node(id=2, coords=(6.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(
            id=1, name="Rect", E=200e9, A=A,
            Iz=Iz, Iy=Iy, G=80e9, J=1e-6,
        )],
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
def test_extrusion_skips_elements_without_section(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A truss element has no section — it must be skipped silently."""
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
    canvas.set_show_section_extrusions(True)
    # No crash, no extra actor (truss has no section_id).
    # (Other aux actors like the grid might exist; only verify nothing blew up.)
    assert canvas._renderer._aux_actors is not None
