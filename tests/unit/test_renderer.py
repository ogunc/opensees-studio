"""Unit tests for ModelRenderer (high-perf glyphed implementation)."""

from __future__ import annotations

import pytest

pv = pytest.importorskip("pyvista")
import numpy as np  # noqa: E402

from opensees_studio.core import (  # noqa: E402
    CoordinateGridSystem,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    Steel01,
    TrussElement,
    make_grid_lines,
)
from opensees_studio.core.geometry.grid import GridSystem  # noqa: E402
from opensees_studio.services.deformation import (  # noqa: E402
    DeformationSource,
    peak_static_displacement,
)
from opensees_studio.services.results import StaticResults  # noqa: E402
from opensees_studio.views.canvas3d.model_renderer import (  # noqa: E402
    ModelRenderer,
    RendererMode,
    _classify_support,
)


# ──────────────────────────── support classification ────────────────────────────
def test_classify_support_full_fix() -> None:
    assert _classify_support((True,) * 6, (0, 1, 2, 3, 4, 5)) == "fix"


def test_classify_support_pin_3d() -> None:
    assert _classify_support((True, True, True, False, False, False), (0, 1, 2, 3, 4, 5)) == "pin"


def test_classify_support_pin_2d() -> None:
    assert _classify_support((True, True, False, False, False, False), (0, 1)) == "fix"
    assert _classify_support((True, True, False, False, False, False), (0, 1, 5)) == "pin"


def test_classify_support_roller() -> None:
    assert _classify_support((False, True, False, False, False, False), (0, 1, 5)) == "roller"


# ──────────────────────────── renderer fixtures ────────────────────────────
@pytest.fixture
def offscreen_plotter():  # type: ignore[no-untyped-def]
    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True)
    yield p
    p.close()


@pytest.fixture
def small_3d_project() -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 3.0)),
            Node(id=3, coords=(4.0, 0, 3.0), mass=(100, 100, 0, 0, 0, 0)),
        ],
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-6)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(0, 0, -10e3, 0, 0, 0))],
            )
        ],
    )


# ──────────────────────────── core rendering ────────────────────────────
def test_render_empty_project_does_not_raise(offscreen_plotter) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(None)
    r.render(Project())


def test_render_creates_node_and_frame_polydata(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    # One polydata for nodes, one for frames.
    assert r._node_pd is not None
    assert r._frame_pd is not None
    assert len(r._node_ids_ordered) == 3
    assert len(r._frame_ids_ordered) == 2


def test_render_attaches_picking_metadata(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    node_ids = set(np.asarray(r._node_pd["_oss_id"]).tolist())
    frame_ids = set(np.asarray(r._frame_pd.cell_data["_oss_id"]).tolist())
    assert node_ids == {1, 2, 3}
    assert frame_ids == {1, 2}


def test_render_twice_does_not_leak_actors(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    aux1 = len(r._aux_actors)
    r.render(small_3d_project)
    aux2 = len(r._aux_actors)
    assert aux1 == aux2  # not doubled


# ──────────────────────── the origin reference ────────────────────────
def test_the_origin_triad_marks_the_three_axes_from_the_origin(
    offscreen_plotter, small_3d_project
) -> None:  # type: ignore[no-untyped-def]
    """A user looking at an unfamiliar model needs to know which way +Y runs."""
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)

    assert len(r._triad_actors) == 4  # three arrows and their labels
    length = r._origin_triad_length(small_3d_project)
    for axis, actor in enumerate(r._triad_actors[:3]):
        xmin, xmax, ymin, ymax, zmin, zmax = actor.GetBounds()
        spans = [xmax - xmin, ymax - ymin, zmax - zmin]
        assert spans[axis] == pytest.approx(length, rel=1e-6)  # its own axis...
        assert max(spans) == pytest.approx(length, rel=1e-6)  # ...and only that one
        lower = (xmin, ymin, zmin)[axis]
        assert lower == pytest.approx(0.0, abs=1e-9)  # it starts at (0, 0, 0)


def test_the_triad_is_a_reference_not_a_target(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)

    assert all(not actor.GetPickable() for actor in r._triad_actors)


def test_the_triad_scales_with_the_model(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    """Small next to a 100 m frame, visible next to a 100 mm one."""
    r = ModelRenderer(offscreen_plotter)
    small = r._origin_triad_length(small_3d_project)
    large = r._origin_triad_length(
        small_3d_project.model_copy(
            update={
                "nodes": [
                    node.model_copy(update={"coords": tuple(c * 100 for c in node.coords)})
                    for node in small_3d_project.nodes
                ]
            }
        )
    )

    assert small == pytest.approx(0.08 * 5.0)  # the 3-4-5 diagonal of this model
    assert large == pytest.approx(100.0 * small)


def test_an_empty_project_still_gets_a_reference(offscreen_plotter) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(Project())

    assert len(r._triad_actors) == 4
    assert r._origin_triad_length(Project()) == 1.0


def test_the_triad_falls_back_to_the_grid_when_there_are_no_nodes(offscreen_plotter) -> None:  # type: ignore[no-untyped-def]
    project = Project(
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, 10.0]),
                    y_grid_lines=make_grid_lines("Y", [0.0]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            )
        ]
    )
    r = ModelRenderer(offscreen_plotter)
    r.render(project)

    assert r._origin_triad_length(project) == pytest.approx(0.8)  # 8 % of the 10 m grid
    assert len(r._triad_actors) == 4


def test_the_triad_is_rebuilt_and_torn_down_with_the_scene(
    offscreen_plotter, small_3d_project
) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    r.render(small_3d_project)
    assert len(r._triad_actors) == 4  # not accumulated

    r.render(None)
    assert r._triad_actors == []


# ──────────────────────────── selection ────────────────────────────
def test_update_selection_writes_state_array(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    r.update_selection(frozenset({1, 3}), frozenset({2}))

    node_states = np.asarray(r._node_pd["_oss_state"]).tolist()
    frame_states = np.asarray(r._frame_pd.cell_data["_oss_state"]).tolist()
    # Nodes 1 and 3 selected → row 0 and row 2
    assert node_states == [1, 0, 1]
    # Element 2 selected → it's the second frame (index 1 in frame_ids_ordered)
    selected_frame_idx = r._frame_id_to_row[2]
    assert frame_states[selected_frame_idx] == 1


def test_clear_selection(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    r.update_selection(frozenset({1}), frozenset())
    r.update_selection(frozenset(), frozenset())
    assert all(v == 0 for v in np.asarray(r._node_pd["_oss_state"]))


# ──────────────────────────── deformation modes ────────────────────────────
def test_set_deformed_mode_shifts_node_positions(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    # Node 3 gets a 0.5m horizontal disp; others zero.
    disp = np.zeros((3, 3))
    disp[2] = (0.5, 0.0, 0.0)
    src = DeformationSource(
        displacements=disp,
        node_id_to_row={1: 0, 2: 1, 3: 2},
        scale=1.0,
    )
    r.set_mode(RendererMode.DEFORMED, src)
    pts = np.asarray(r._node_pd.points)
    # Node 3 was at x=4.0 → now x=4.5
    assert abs(pts[2, 0] - 4.5) < 1e-9
    # Nodes 1 and 2 unchanged
    assert tuple(pts[0]) == (0.0, 0.0, 0.0)


def test_set_mode_back_to_model_restores_original(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    disp = np.array([[0, 0, 0], [0, 0, 0], [10.0, 0, 0]])
    src = DeformationSource(displacements=disp, node_id_to_row={1: 0, 2: 1, 3: 2}, scale=1.0)
    r.set_mode(RendererMode.DEFORMED, src)
    r.set_mode(RendererMode.MODEL)
    pts = np.asarray(r._node_pd.points)
    # Node 3 back to (4, 0, 3)
    assert tuple(pts[2]) == (4.0, 0.0, 3.0)


def test_deformation_scale_multiplies_displacement(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    disp = np.array([[0, 0, 0], [0, 0, 0], [1.0, 0, 0]])
    src = DeformationSource(displacements=disp, node_id_to_row={1: 0, 2: 1, 3: 2}, scale=10.0)
    r.set_mode(RendererMode.DEFORMED, src)
    pts = np.asarray(r._node_pd.points)
    # Node 3: 4.0 + 10.0 * 1.0 = 14.0
    assert abs(pts[2, 0] - 14.0) < 1e-9


# ──────────────────────────── degenerate geometry ────────────────────────────
def test_diag_handles_degenerate_geometry() -> None:
    pts = np.array([[0, 0, 0], [0, 0, 0]])
    assert ModelRenderer._diag_of_points(pts) == 1.0
    assert ModelRenderer._diag_of_points(None) == 1.0


# ──────────────────────────── grid closures (B023) ────────────────────────────
class _RecordingPlotter:
    """Minimal plotter stand-in: records ``add_mesh`` calls, opens no window."""

    def __init__(self) -> None:
        self.meshes: list[tuple[object, dict[str, object]]] = []

    def add_mesh(self, mesh, **kwargs):  # type: ignore[no-untyped-def]
        self.meshes.append((mesh, kwargs))
        return object()

    def enable_anti_aliasing(self, *_args: object) -> None:
        return None


def test_grid_helpers_use_their_own_coord_system() -> None:
    """Each coord system's grid must use its own plane offset and transform.

    Pins the early binding of the per-iteration helpers in ``_build_grid``:
    a helper that read a later iteration's ``cs`` or plane offset would put
    the second system's active level at the wrong height or origin.
    """
    from opensees_studio.core.geometry.grid import (
        CoordinateGridSystem,
        CoordinateSystem,
        GridSystem,
    )

    project = Project(
        ndm=3,
        ndf=6,
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(x_lines=[0, 1], y_lines=[0, 1], z_lines=[0, 3]),
            ),
            CoordinateGridSystem(
                name="Shifted",
                coord=CoordinateSystem(origin=(10.0, 0.0, 1.0)),
                grid=GridSystem(x_lines=[0, 1], y_lines=[0, 1], z_lines=[0, 2]),
            ),
        ],
    )
    plotter = _RecordingPlotter()
    r = ModelRenderer(plotter)
    r._working_plane = ("XY", 3.0)
    r._build_grid(project)

    # Active-level line actors are the ones drawn at line_width 1.8.
    active = [np.asarray(m.points) for m, kw in plotter.meshes if kw.get("line_width") == 1.8]
    assert len(active) == 2
    global_pts, shifted_pts = active
    # Both active levels sit on world z = 3 (local z = 3 and local z = 2).
    assert np.allclose(global_pts[:, 2], 3.0)
    assert np.allclose(shifted_pts[:, 2], 3.0)
    # Each one is transformed by its own origin.
    assert global_pts[:, 0].min() == 0.0 and global_pts[:, 0].max() == 1.0
    assert shifted_pts[:, 0].min() == 10.0 and shifted_pts[:, 0].max() == 11.0


# ──────────────────── peak displacement (display units) ────────────────────
def test_peak_static_displacement_is_the_largest_node_translation() -> None:
    """The number the deformed-shape panel reports, in model units."""
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(3, 0, 0))],
    )
    results = StaticResults(
        case_id=1,
        case_name="t",
        n_steps=1,
        node_disp={
            1: np.array([[0.0, 0.0, 0.0], [0.003, 0.004, 9.0]]),  # 5 mm translation
            2: np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.25]]),  # rotation only
        },
    )
    # 3-4-5 triangle: the magnitude of (3 mm, 4 mm) is 5 mm, not 4 mm.
    assert peak_static_displacement(project, results) == pytest.approx(0.005)


def test_peak_displacement_is_zero_without_results() -> None:
    project = Project(ndm=3, nodes=[Node(id=1, coords=(0, 0, 0))])
    empty = StaticResults(case_id=1, case_name="t", n_steps=1)
    assert peak_static_displacement(project, empty) == 0.0
