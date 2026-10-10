"""The shell contour overlay: what it draws, and what it refuses to draw.

A recording plotter stands in for VTK so the scalars, the colour limits, the
colour-bar title and the direction segments can be read exactly; one offscreen
plotter proves the same mesh survives a real render pipeline.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")

import pyvista as pv

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    Project,
    ProjectMeta,
    ShellMITC4Element,
    UnitSystem,
)
from opensees_studio.services.results import StaticResults
from opensees_studio.views.canvas3d.shell_contour_renderer import ShellContourRenderer

pv.OFF_SCREEN = True

#: N11, N22, N12, M11, M22, M12, V13, V23
UNIAXIAL = [1000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
PURE_SHEAR = [0.0, 0.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0]
BENDING = [0.0, 0.0, 0.0, 4000.0, -1000.0, 0.0, 0.0, 0.0]


class _RecordingPlotter:
    """Just enough plotter for the renderer: records instead of drawing."""

    def __init__(self) -> None:
        self.meshes: list[tuple[object, dict]] = []

    def add_mesh(self, mesh: object, **kwargs: object) -> object:
        self.meshes.append((mesh, dict(kwargs)))
        return object()

    def remove_actor(self, *_args: object, **_kwargs: object) -> None:
        pass

    def remove_scalar_bar(self) -> None:
        pass

    @property
    def surface(self) -> tuple[object, dict]:
        return self.meshes[0]

    @property
    def glyphs(self) -> tuple[object, dict] | None:
        return self.meshes[1] if len(self.meshes) > 1 else None


def _project(
    *, with_bar: bool = False, shell_rows: dict[int, list[float]] | None = None
) -> Project:
    elements = [ShellMITC4Element(id=20, nodes=(1, 2, 3, 4), section_id=1)]
    if with_bar:
        elements.append(ElasticBeamColumn(id=30, nodes=(1, 3), section_id=2))
    return Project(
        meta=ProjectMeta(name="contour", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
            Node(id=3, coords=(1.0, 1.0, 0.0)),
            Node(id=4, coords=(0.0, 1.0, 0.0)),
        ],
        sections=[
            ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2, rho=0.0),
            ElasticSection(id=2, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6),
        ],
        elements=elements,
    )


def _two_shells() -> Project:
    """Two shells sharing an edge, so a field can have two different values."""
    project = _project()
    project.nodes = [
        *project.nodes,
        Node(id=5, coords=(2.0, 0.0, 0.0)),
        Node(id=6, coords=(2.0, 1.0, 0.0)),
    ]
    project.elements = [
        ShellMITC4Element(id=20, nodes=(1, 2, 3, 4), section_id=1),
        ShellMITC4Element(id=21, nodes=(2, 5, 6, 3), section_id=1),
    ]
    return project


def _two_shell_results(first: float, second: float) -> StaticResults:
    disp = {node_id: np.zeros((1, 6)) for node_id in (1, 2, 3, 4, 5, 6)}
    return StaticResults(
        case_id=1,
        case_name="two shells",
        n_steps=1,
        node_disp=disp,
        element_stresses={
            20: np.array([[first, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]),
            21: np.array([[second, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]),
        },
    )


def _results(row: list[float], *, uz: float = 0.0) -> StaticResults:
    disp = {node_id: np.zeros((1, 6)) for node_id in (1, 2, 3, 4)}
    disp[3][0, 2] = uz
    return StaticResults(
        case_id=1,
        case_name="contour",
        n_steps=1,
        node_disp=disp,
        element_stresses={20: np.array([row])},
    )


# ───────────────────────── the mesh and its scalars ─────────────────────────
def test_one_point_per_node_and_one_cell_per_shell() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(UNIAXIAL), "N11", units=UnitSystem.SI_M_N)

    mesh, _kwargs = plot.surface
    assert mesh.n_points == 4  # the four corners of the one shell
    assert mesh.n_cells == 1
    assert renderer.points == 4 and renderer.cells == 1
    assert np.allclose(mesh.point_data["value"], 1000.0)


def test_the_colour_range_covers_the_field() -> None:
    """A constant field still gets a band, not a degenerate one."""
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(BENDING), "M11", units=UnitSystem.SI_M_N)
    # 4000 everywhere, padded by its own magnitude so the map is not a single colour.
    assert renderer.range == pytest.approx((0.0, 8000.0))

    renderer.render(_project(), _results(BENDING), "M1", units=UnitSystem.SI_M_N)
    assert renderer.range is not None
    assert renderer.range[0] < renderer.range[1]


def test_a_signed_field_is_centred_on_zero() -> None:
    """A moment or a membrane force is read by sign, so zero is mid-colour."""
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(
        _two_shells(),
        _two_shell_results(1000.0, -3000.0),
        "N11",
        units=UnitSystem.SI_M_N,
    )
    assert renderer.range == pytest.approx((-3000.0, 3000.0))


def test_the_colour_bar_names_the_field_and_the_project_unit() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(BENDING), "M1", units=UnitSystem.US_IN_KIP)
    _mesh, kwargs = plot.surface
    title = kwargs["scalar_bar_args"]["title"]
    assert "M1" in title and "kip·in/in" in title
    assert kwargs["clim"] == renderer.range


def test_a_kip_in_project_paints_the_force_per_length_in_kip_per_inch() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(UNIAXIAL), "N11", units=UnitSystem.US_IN_KIP)
    _mesh, kwargs = plot.surface
    assert "kip/in" in kwargs["scalar_bar_args"]["title"]


# ───────────────────────── warping ─────────────────────────
def test_warping_moves_the_mesh_by_the_displacement_at_scale() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(
        _project(), _results(UNIAXIAL, uz=0.01), "uz", scale=2.0, units=UnitSystem.SI_M_N
    )
    mesh, _kwargs = plot.surface
    # Node 3 is the only one that moved, by 2 x 0.01 m.
    assert np.allclose(mesh.points[2], (1.0, 1.0, 0.02))
    assert np.allclose(mesh.points[0], (0.0, 0.0, 0.0))


def test_no_warp_means_the_model_geometry() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(
        _project(), _results(UNIAXIAL, uz=0.01), "N11", scale=0.0, units=UnitSystem.SI_M_N
    )
    mesh, _kwargs = plot.surface
    assert np.allclose(mesh.points[2], (1.0, 1.0, 0.0))


# ───────────────────────── principal directions ─────────────────────────
def test_a_principal_field_can_draw_its_direction() -> None:
    """Pure shear: the major principal axis sits at +45° from the element's 1-axis."""
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(
        _project(),
        _results(PURE_SHEAR),
        "N1",
        show_directions=True,
        units=UnitSystem.SI_M_N,
    )
    assert plot.glyphs is not None
    lines, _kwargs = plot.glyphs
    assert lines.n_cells == 1
    points = np.asarray(lines.points)
    direction = points[1] - points[0]
    direction = direction / np.linalg.norm(direction)
    assert direction == pytest.approx([2**-0.5, 2**-0.5, 0.0], abs=1e-9)
    # Length: 2 x 0.35 x the element size, since this element is the widest spread.
    assert np.linalg.norm(points[1] - points[0]) == pytest.approx(0.7)
    assert np.allclose(points.mean(axis=0), (0.5, 0.5, 0.0))


def test_a_component_field_draws_no_direction() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(PURE_SHEAR), "N11", show_directions=True)
    assert plot.glyphs is None


def test_directions_are_opt_in() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(PURE_SHEAR), "N1", units=UnitSystem.SI_M_N)
    assert plot.glyphs is None


def test_a_hydrostatic_state_has_no_direction_to_draw() -> None:
    """Equal principals: the spread is zero, so no segment is emitted."""
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(
        _project(),
        _results([500.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        "N1",
        show_directions=True,
        units=UnitSystem.SI_M_N,
    )
    assert renderer.is_drawn
    assert plot.glyphs is None


# ───────────────────────── what is not drawn ─────────────────────────
def test_a_model_of_bars_draws_nothing() -> None:
    project = _project(with_bar=True)
    project.elements = [element for element in project.elements if element.id == 30]
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(project, _results(UNIAXIAL), "N11")
    assert plot.meshes == []
    assert renderer.range is None


def test_a_field_without_values_draws_nothing() -> None:
    results = StaticResults(case_id=1, case_name="bars", n_steps=1, node_disp={1: np.zeros((1, 6))})
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), results, "N11", units=UnitSystem.SI_M_N)
    assert plot.meshes == []
    assert renderer.is_drawn is False


def test_a_zero_field_is_drawn_as_zero_without_blowing_up() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results([0.0] * 8), "N11", units=UnitSystem.SI_M_N)
    assert renderer.is_drawn
    assert renderer.range is not None
    assert renderer.range[0] < renderer.range[1]  # not a degenerate band


def test_clearing_removes_both_actors() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(PURE_SHEAR), "N1", show_directions=True)
    assert renderer.is_drawn
    renderer.clear()
    assert renderer.is_drawn is False
    assert renderer.range is None and renderer.points == 0 and renderer.cells == 0


def test_rendering_twice_replaces_the_previous_contour() -> None:
    plot = _RecordingPlotter()
    renderer = ShellContourRenderer(plot)
    renderer.render(_project(), _results(UNIAXIAL), "N11", units=UnitSystem.SI_M_N)
    first = renderer._actor
    renderer.render(_project(), _results(BENDING), "M11", units=UnitSystem.SI_M_N)
    assert renderer._actor is not first


# ───────────────────────── a real pipeline ─────────────────────────
@pytest.mark.filterwarnings("ignore::UserWarning")
def test_it_renders_in_a_real_offscreen_plotter() -> None:
    plotter = pv.Plotter(off_screen=True)
    try:
        renderer = ShellContourRenderer(plotter)
        renderer.render(
            _project(),
            _results(PURE_SHEAR, uz=0.01),
            "N1",
            scale=5.0,
            show_directions=True,
            units=UnitSystem.SI_M_N,
        )
        assert renderer.is_drawn
        plotter.render()
        assert plotter.scalar_bar is not None
        assert "N1" in plotter.scalar_bar.GetTitle()
        renderer.clear()
        assert not renderer.is_drawn
    finally:
        plotter.close()
