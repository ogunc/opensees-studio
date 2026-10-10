"""Smoke tests for the force-diagram overlay renderer.

These verify the renderer doesn't crash on representative inputs and
produces an actor when there's data to draw. Geometry/colour assertions
are kept minimal — they'd be brittle and the visual is the spec anyway.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pytest

# Force pyvista off-screen before any pyvista import in this module's chain.
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")

import pyvista as pv

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    Project,
    ShellMITC4Element,
    UnitSystem,
)
from opensees_studio.services.element_forces import (
    DiagramData,
    ForceComponent,
    extract_diagram_data,
)
from opensees_studio.services.results import StaticResults
from opensees_studio.views.canvas3d.diagram_renderer import DiagramRenderer

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
    f10 = np.array([[100.0, 5.0, 0.0, 0.0, 0.0, 9.0, -100.0, -5.0, 0.0, 0.0, 0.0, -9.0]])
    f20 = np.array([[-50.0, 2.0, 0.0, 0.0, 0.0, 3.0, 50.0, -2.0, 0.0, 0.0, 0.0, -3.0]])
    return StaticResults(case_id=1, case_name="t", n_steps=1, element_forces={10: f10, 20: f20})


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
        values_i=np.empty(0),
        values_j=np.empty(0),
        abs_max=0.0,
    )
    r.render(project_3d, empty, scale=1.0)
    assert r._actor is None


def test_render_zero_magnitude_data_does_not_create_actor(
    offscreen_plotter,
    project_3d,
) -> None:  # type: ignore[no-untyped-def]
    """A diagram for a component that's identically zero shouldn't render
    an empty mesh + scalar bar — that's misleading visual noise."""
    r = DiagramRenderer(offscreen_plotter)
    zero_for_two_elems = DiagramData(
        component=ForceComponent.T,
        element_ids=np.array([10, 20], dtype=int),
        values_i=np.zeros(2),
        values_j=np.zeros(2),
        abs_max=0.0,
    )
    r.render(project_3d, zero_for_two_elems, scale=1.0)
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


# ──────────────── face elements: the crash of 2026-10-06 ────────────────
# A shell returns a 24-component element force vector, which the beam index
# map happily read as a beam's: the diagram then drew garbage and the renderer
# died on `n_i, n_j = elem.nodes` inside a Qt slot, which took the running
# application down.
def _beam_and_shell() -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
            Node(id=3, coords=(4.0, 0.0, 0.0)),
            Node(id=4, coords=(4.0, 1.0, 0.0)),
            Node(id=5, coords=(3.0, 1.0, 0.0)),
        ],
        sections=[
            ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5),
            ElasticMembranePlateSection(id=2, E=30e9, nu=0.2, h=0.2, rho=2500.0),
        ],
        elements=[
            ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1),
            ShellMITC4Element(id=20, nodes=(2, 3, 4, 5), section_id=2),
        ],
    )


def _results_with_a_shell_force_vector() -> StaticResults:
    beam = np.array([[100.0, 5.0, 0.0, 0.0, 0.0, 9.0, -100.0, -5.0, 0.0, 0.0, 0.0, -9.0]])
    shell = np.arange(24, dtype=float).reshape(1, 24)  # what OpenSees returns
    return StaticResults(case_id=1, case_name="t", n_steps=1, element_forces={10: beam, 20: shell})


def test_the_extractor_skips_face_elements() -> None:
    data = extract_diagram_data(
        _beam_and_shell(), _results_with_a_shell_force_vector(), ForceComponent.M3
    )
    assert list(data.element_ids) == [10]
    # And the beam's own numbers survive intact.
    assert data.values_i == [9.0]
    assert data.values_j == [9.0]


def test_the_extractor_is_left_with_nothing_when_only_faces_return_forces() -> None:
    project = _beam_and_shell()
    project.elements = [el for el in project.elements if el.id == 20]
    data = extract_diagram_data(project, _results_with_a_shell_force_vector(), ForceComponent.M3)
    assert data.element_ids.size == 0
    assert data.abs_max == 0.0


def test_the_renderer_tolerates_a_face_element_in_the_data(offscreen_plotter) -> None:  # type: ignore[no-untyped-def]
    """Defence in depth: a `DiagramData` naming a shell must not kill the app."""
    project = _beam_and_shell()
    r = DiagramRenderer(offscreen_plotter)
    stale = DiagramData(
        component=ForceComponent.M3,
        element_ids=np.array([10, 20], dtype=int),  # 20 is the shell
        values_i=np.array([9.0, 1.0]),
        values_j=np.array([9.0, 1.0]),
        abs_max=9.0,
    )
    r.render(project, stale, scale=0.05)
    assert r._actor is not None  # the beam still draws


# ──────────────── display units: what the diagram reads ────────────────
# The drawn ribbon is a geometric multiplier on the model values, so its size
# must not move when the display units do; the colour bar and the end labels
# carry the numbers, and those convert. Exact definitions, not copied factors:
# 1 in = 25.4 mm, 1 kip = 4448.2216152605 N.
IN_M = 0.0254
KIP_N = 4448.2216152605
N_PER_KIP = 1.0 / KIP_N


class _RecordingPlotter:
    """Just enough plotter for `DiagramRenderer`: records instead of drawing."""

    def __init__(self) -> None:
        self.mesh: Any = None
        self.mesh_kwargs: dict[str, Any] = {}
        self.label_texts: list[str] = []
        self.label_positions: Any = None

    def add_mesh(self, mesh: Any, **kwargs: Any) -> object:
        self.mesh = mesh
        self.mesh_kwargs = kwargs
        return object()

    def add_point_labels(self, positions: Any, labels: list[str], **_kwargs: Any) -> object:
        self.label_positions = positions
        self.label_texts = list(labels)
        return object()

    def remove_actor(self, *_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
        pass

    def remove_scalar_bar(self) -> None:  # pragma: no cover
        pass


def _shown_in_us(project: Project) -> Project:
    project.meta.display_units = UnitSystem.US_IN_KIP
    return project


def test_a_moment_diagram_reads_in_kip_in_when_the_display_is_us() -> None:
    project = _shown_in_us(
        Project(
            nodes=[
                Node(id=1, coords=(0.0, 0.0, 0.0)),
                Node(id=2, coords=(3.0, 0.0, 0.0)),
            ],
            sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5)],
            elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
        )
    )
    forces = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 1000.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1000.0]])
    results = StaticResults(case_id=1, case_name="t", n_steps=1, element_forces={10: forces})

    recorded = _RecordingPlotter()
    data = extract_diagram_data(project, results, ForceComponent.M3)
    DiagramRenderer(recorded).render(project, data, scale=0.01)

    # 1000 N·m = 1000 · (1/4448.2216) kip · 39.3701 in = 8.8507 kip·in
    expected = 1000.0 * N_PER_KIP / IN_M
    assert recorded.mesh_kwargs["scalar_bar_args"]["title"] == "M3 [kip·in]"
    assert recorded.mesh.cell_data["value"][0] == pytest.approx(expected)
    assert recorded.mesh_kwargs["clim"] == pytest.approx((-expected, expected))
    assert recorded.label_texts[0] == "8.85"
    assert all("kip" not in text for text in recorded.label_texts)  # the title carries it


def test_an_axial_diagram_converts_as_a_force_not_a_moment() -> None:
    project = Project(
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(3.0, 0.0, 0.0))],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5)],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
    )
    project.meta.display_units = UnitSystem.US_IN_KIP
    forces = np.array([[1e6, 0, 0, 0, 0, 0, -1e6, 0, 0, 0, 0, 0]])
    results = StaticResults(case_id=1, case_name="t", n_steps=1, element_forces={10: forces})

    recorded = _RecordingPlotter()
    data = extract_diagram_data(project, results, ForceComponent.N)
    DiagramRenderer(recorded).render(project, data, scale=1e-4)

    assert recorded.mesh_kwargs["scalar_bar_args"]["title"] == "N [kip]"
    assert recorded.mesh.cell_data["value"][0] == pytest.approx(1e6 * N_PER_KIP)


def test_the_drawn_geometry_does_not_move_when_the_display_units_change() -> None:
    """Two models, same values, different display systems: identical points."""

    def build(display):  # type: ignore[no-untyped-def]
        project = Project(
            nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(3.0, 0.0, 0.0))],
            sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5)],
            elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
        )
        project.meta.display_units = display
        return project

    forces = np.array([[0, 0, 0, 0, 0, 5000.0, 0, 0, 0, 0, 0, -5000.0]])
    results = StaticResults(case_id=1, case_name="t", n_steps=1, element_forces={10: forces})

    model_units = build(None)
    us_units = build(UnitSystem.US_IN_KIP)
    plain = _RecordingPlotter()
    converted = _RecordingPlotter()
    DiagramRenderer(plain).render(
        model_units, extract_diagram_data(model_units, results, ForceComponent.M3), 0.01
    )
    DiagramRenderer(converted).render(
        us_units, extract_diagram_data(us_units, results, ForceComponent.M3), 0.01
    )

    assert np.allclose(plain.mesh.points, converted.mesh.points)
    # ...while the number the user reads did change, by the moment factor.
    assert converted.mesh.cell_data["value"][0] == pytest.approx(
        plain.mesh.cell_data["value"][0] * N_PER_KIP / IN_M,
    )


def test_component_quantity_kinds() -> None:
    assert ForceComponent.N.quantity_kind == "force"
    assert ForceComponent.V2.quantity_kind == "force"
    assert ForceComponent.V3.quantity_kind == "force"
    assert ForceComponent.T.quantity_kind == "moment"
    assert ForceComponent.M2.quantity_kind == "moment"
    assert ForceComponent.M3.quantity_kind == "moment"
    assert ForceComponent.M3.is_moment is True
    assert ForceComponent.N.is_moment is False
