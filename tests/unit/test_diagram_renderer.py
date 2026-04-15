"""Smoke tests for the force-diagram overlay renderer.

These verify the renderer doesn't crash on representative inputs and
produces an actor when there's data to draw. Geometry/colour assertions
are kept minimal — they'd be brittle and the visual is the spec anyway.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

# Force pyvista off-screen before any pyvista import in this module's chain.
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")

import pyvista as pv  # noqa: E402

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
)
from opensees_studio.services.element_forces import (  # noqa: E402
    DiagramData,
    ForceComponent,
    extract_diagram_data,
)
from opensees_studio.services.results import StaticResults  # noqa: E402
from opensees_studio.views.canvas3d.diagram_renderer import DiagramRenderer  # noqa: E402

pv.OFF_SCREEN = True


@pytest.fixture
def offscreen_plotter():  # type: ignore[no-untyped-def]
    p = pv.Plotter(off_screen=True)
    yield p
    p.close()


@pytest.fixture
def project_3d() -> Project:
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
            Node(id=3, coords=(6.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5)],
        elements=[
            ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=20, nodes=(2, 3), section_id=1),
        ],
    )


@pytest.fixture
def static_results() -> StaticResults:
    f10 = np.array([[100.0, 5.0, 0.0, 0.0, 0.0, 9.0,
                     -100.0, -5.0, 0.0, 0.0, 0.0, -9.0]])
    f20 = np.array([[-50.0, 2.0, 0.0, 0.0, 0.0, 3.0,
                     50.0, -2.0, 0.0, 0.0, 0.0, -3.0]])
    return StaticResults(case_id=1, case_name="t", n_steps=1,
                         element_forces={10: f10, 20: f20})


def test_render_axial_creates_actor(offscreen_plotter, project_3d, static_results) -> None:  # type: ignore[no-untyped-def]
    r = DiagramRenderer(offscreen_plotter)
    data = extract_diagram_data(project_3d, static_results, ForceComponent.N)
    r.render(project_3d, data, scale=0.01)
    assert r._actor is not None


def test_render_shear_creates_actor(offscreen_plotter, project_3d, static_results) -> None:  # type: ignore[no-untyped-def]
    r = DiagramRenderer(offscreen_plotter)
    data = extract_diagram_data(project_3d, static_results, ForceComponent.V2)
    r.render(project_3d, data, scale=0.05)
    assert r._actor is not None


def test_render_moment_creates_actor(offscreen_plotter, project_3d, static_results) -> None:  # type: ignore[no-untyped-def]
    r = DiagramRenderer(offscreen_plotter)
    data = extract_diagram_data(project_3d, static_results, ForceComponent.M3)
    r.render(project_3d, data, scale=0.05)
    assert r._actor is not None


def test_render_empty_data_does_not_create_actor(offscreen_plotter, project_3d) -> None:  # type: ignore[no-untyped-def]
    r = DiagramRenderer(offscreen_plotter)
    empty = DiagramData(
        component=ForceComponent.N,
        element_ids=np.empty(0, dtype=int),
        values_i=np.empty(0), values_j=np.empty(0), abs_max=0.0,
    )
    r.render(project_3d, empty, scale=1.0)
    assert r._actor is None


def test_clear_removes_actor(offscreen_plotter, project_3d, static_results) -> None:  # type: ignore[no-untyped-def]
    r = DiagramRenderer(offscreen_plotter)
    data = extract_diagram_data(project_3d, static_results, ForceComponent.N)
    r.render(project_3d, data, scale=0.01)
    assert r._actor is not None
    r.clear()
    assert r._actor is None


def test_render_replaces_previous_overlay(offscreen_plotter, project_3d, static_results) -> None:  # type: ignore[no-untyped-def]
    r = DiagramRenderer(offscreen_plotter)
    data_n = extract_diagram_data(project_3d, static_results, ForceComponent.N)
    r.render(project_3d, data_n, scale=0.01)
    first_actor = r._actor
    data_v = extract_diagram_data(project_3d, static_results, ForceComponent.V2)
    r.render(project_3d, data_v, scale=0.05)
    assert r._actor is not first_actor
